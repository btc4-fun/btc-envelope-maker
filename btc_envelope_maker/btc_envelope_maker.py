#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
btc_envelope_maker.py - OFFLINE generator of bitcoin cards printed on A4/A5 sheets.

Every wallet gets two cards in bank-card size (85.6 x 54 mm):
  * PUBLIC card  : logo, serial, address, QR  (goes on the OUTSIDE of the envelope)
  * PRIVATE card : recovery words              (goes INSIDE the envelope - SECRET)
The cards are packed edge to edge on the sheet so that as little paper as possible is wasted.

  --count N   = number of SHEETS (each sheet is filled completely)

Serial = Persian date/time of the run + wallet number, e.g. 0587k45300
  yy  month  day  hour  minute  second  wallet-no.
Run it only on an offline computer.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import os
import re
import socket
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    sys.exit("Python 3.11 or newer is required.")

try:
    import arabic_reshaper
    try:
        from bidi import get_display            # python-bidi >= 0.5
    except ImportError:
        from bidi.algorithm import get_display  # python-bidi 0.4.x
    from bip_utils import (
        Bip39MnemonicGenerator,
        Bip39SeedGenerator,
        Bip39WordsNum,
        Bip44Changes,
        Bip84,
        Bip84Coins,
    )
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError as e:
    sys.exit(f"Missing Python package '{e.name}'.\nSee DEPENDENCIES.md for the offline "
             "--require-hashes installation of requirements-runtime.txt.")

# --------------------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------------------
# Official BIP-84 test vector (a PUBLIC phrase - never put money on it).
TEST_MNEMONIC = " ".join(["abandon"] * 11 + ["about"])
TEST_ADDRESS = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
TEST_MNEMONIC_24 = " ".join(["abandon"] * 23 + ["art"])    # public 24-word test phrase (preview only)

GRAY = HexColor("#666666")
LIGHT = HexColor("#bbbbbb")
CUT = HexColor("#a8a8a8")
RED = HexColor("#b00020")
BLACK = HexColor("#111111")

SHEETS = {"A3": (297, 420), "A4": (210, 297), "A5": (148, 210), "A6": (105, 148), "LETTER": (215.9, 279.4)}

DEFAULTS = {
    "brand_name": "btc4.fun",
    "tagline": "",
    "contact": "btc4.fun   |   09113458375@btc4.fun",
    "logo": "",
    "accent_color": "#1f3a5f",
    "serial_prefix": "",
    "serial_minsec": "digits",
    "timezone": "Asia/Tehran",
    "words": 12,
    "explorer_url": "https://mempool.space/address/",
    "amount_label": "",
    "sheet_size": "A4",
    "sheet_margin_mm": 5,
    "card_width_mm": 85.6,
    "card_height_mm": 54,
    "card_gap_mm": 0,
    "layout": "pairs",
    "pair_direction": "auto",
    "font_regular": "",
    "font_bold": "",
    "outside_notice": "",
    "inside_title": "SECRET",
    "inside_instructions": [],
    "label_address": "Bitcoin address",
    "label_verify": "Check balance",
    "private_qr": "words",
    "label_private_qr": "QR",
    "db_url": "",
    "db_table": "wallets",
}

HERE = Path(__file__).resolve().parent
# (regular, bold) font pairs that contain Persian letters. First hit wins.
FONT_PAIRS = [
    # bundled Vazir Code (monospace, has no bold weight; bold is simulated)
    (HERE / "fonts" / "Vazir-Code-Hack.ttf", HERE / "fonts" / "Vazir-Code-Hack.ttf"),
    (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
     Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
]


class LayoutError(Exception):
    pass


@dataclass
class Wallet:
    serial: str
    address: str
    mnemonic: str = field(repr=False)   # repr=False: never leak secrets into tracebacks/logs
    sheet: int = 0
    slot: int = 0


# --------------------------------------------------------------------------------------
# config + fonts
# --------------------------------------------------------------------------------------
def sheet_dims(spec) -> tuple[float, float]:
    s = str(spec).strip().upper().replace(" ", "")
    if s in SHEETS:
        return SHEETS[s]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)[X×](\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    sys.exit(f"config: unknown sheet_size '{spec}'. Use one of {', '.join(SHEETS)} or e.g. '200x300' (mm).")


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Config file not found: {path}")
    cfg = dict(DEFAULTS)
    with open(path, "rb") as f:
        cfg.update(tomllib.load(f))
    cfg["_dir"] = path.resolve().parent

    def need(cond, msg):
        if not cond:
            sys.exit("config: " + msg)

    need(cfg["words"] in (12, 24), "'words' must be 12 or 24.")
    need(cfg["layout"] in ("pairs", "separate"), "'layout' must be \"pairs\" or \"separate\".")
    need(cfg["pair_direction"] in ("auto", "side", "stack"), "'pair_direction' must be auto, side or stack.")
    need(cfg["serial_minsec"] in ("digits", "compact"), "'serial_minsec' must be \"digits\" or \"compact\".")
    need(cfg["private_qr"] in ("words", "none"), "'private_qr' must be \"words\" or \"none\".")
    for k, lo in (("card_width_mm", 80), ("card_height_mm", 50), ("sheet_margin_mm", 0), ("card_gap_mm", 0)):
        need(isinstance(cfg[k], (int, float)) and cfg[k] >= lo, f"'{k}' must be a number >= {lo}.")
    need(isinstance(cfg["inside_instructions"], (list, str)), "'inside_instructions' must be a list of strings.")
    sheet_dims(cfg["sheet_size"])

    cfg["_logo"] = None
    if cfg.get("logo"):
        p = Path(cfg["logo"])
        p = p if p.is_absolute() else cfg["_dir"] / p
        if p.exists():
            cfg["_logo"] = p
        else:
            print(f"warning: logo file not found ({p}) - continuing without a logo.")
    return cfg


def register_fonts(cfg: dict) -> None:
    reg = Path(cfg["font_regular"]) if cfg["font_regular"] else None
    bold = Path(cfg["font_bold"]) if cfg["font_bold"] else None
    if not reg:
        for r, b in FONT_PAIRS:
            if r.exists():
                reg, bold = r, (b if b.exists() else r)
                break
    if not reg or not reg.exists():
        sys.exit("No font with Persian letters found.\n"
                 "The folder 'fonts' (with Vazir-Code-Hack.ttf) must stay next to this script, "
                 "or set font_regular / font_bold in config.toml.")
    pdfmetrics.registerFont(TTFont("Body", str(reg)))
    pdfmetrics.registerFont(TTFont("Body-Bold", str(bold if bold and bold.exists() else reg)))


# --------------------------------------------------------------------------------------
# crypto (all heavy lifting is done by the audited bip_utils library)
# --------------------------------------------------------------------------------------
def derive_address(mnemonic: str) -> str:
    """mnemonic -> first BIP84 (Native SegWit) address, path m/84'/0'/0'/0/0."""
    seed = Bip39SeedGenerator(mnemonic).Generate()
    node = (
        Bip84.FromSeed(seed, Bip84Coins.BITCOIN)
        .Purpose().Coin().Account(0)
        .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
    )
    return node.PublicKey().ToAddress()


def new_mnemonic(n_words: int) -> str:
    num = Bip39WordsNum.WORDS_NUM_12 if n_words == 12 else Bip39WordsNum.WORDS_NUM_24
    m = Bip39MnemonicGenerator().FromWordsNumber(num)   # entropy comes from os.urandom
    return m.ToStr() if hasattr(m, "ToStr") else str(m)


def self_test() -> None:
    """Refuse to run if the library does not reproduce the official BIP-84 test vector."""
    addr = derive_address(TEST_MNEMONIC)
    if addr != TEST_ADDRESS:
        sys.exit(
            "SELF-TEST FAILED: derived address does not match the official BIP-84 test vector.\n"
            f"  expected {TEST_ADDRESS}\n  got      {addr}\n"
            "Do NOT use this tool for real money until this is resolved."
        )
    print("Self-test OK (official BIP-84 test vector reproduced).")


def looks_online() -> bool:
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("9.9.9.9", 443)):
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------------------
# Persian (Jalali) date  ->  serial number
# --------------------------------------------------------------------------------------
def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


# value 1..9 -> '1'..'9', 10 -> '0', 11.. -> 'a','b','c',...   (so month 12 = 'b', day 31 = 'u')
_ALPHA = "1234567890abcdefghijklmnopqrstuvwxyz"
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_B60 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX"   # 0..59, case sensitive


def enc1(v: int) -> str:
    return _ALPHA[v - 1]


def enc_hour(h: int) -> str:
    return "z" if h == 0 else enc1(h)      # 0 (midnight) has no symbol in the 1..9,0,a.. scheme -> 'z'


def enc_ms(v: int, mode: str) -> str:
    return f"{v:02d}" if mode == "digits" else _B60[v]


def to_b36(n: int, width: int) -> str:
    if width < 1 or n < 0 or n >= 36 ** width:
        raise ValueError("base36 value does not fit the requested width")
    s = ""
    for _ in range(width):
        n, r = divmod(n, 36)
        s = _B36[r] + s
    return s


def serial_stem(now: dt.datetime, mode: str = "digits") -> tuple[str, str]:
    """Second-resolution identifier, NOT globally unique across runs.

    Same-second runs with the same prefix/mode can collide, especially with
    separate output roots or machines. Exclusive batch-folder creation only
    protects a shared output root; keep distinct prefixes for independent runs.
    """
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    stem = f"{jy % 100:02d}{enc1(jm)}{enc1(jd)}{enc_hour(now.hour)}{enc_ms(now.minute, mode)}{enc_ms(now.second, mode)}"
    human = f"{jy:04d}/{jm:02d}/{jd:02d} {now:%H:%M:%S}"
    return stem, human


def now_local(cfg: dict) -> dt.datetime:
    name = cfg["timezone"]
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(name)
    except Exception:
        if name == "Asia/Tehran":
            tz = dt.timezone(dt.timedelta(hours=3, minutes=30))   # Iran has no DST since 2022
        else:
            sys.exit(f"Time zone '{name}' not available. See DEPENDENCIES.md for the offline "
                     "--require-hashes installation of requirements-runtime.txt (includes tzdata).")
    return dt.datetime.now(tz)


def serial_width(total: int) -> int:
    """Keep historical widths, extending only when the entire batch needs it."""
    width = 1
    while total > 36 ** width:
        width += 1
    return width


def make_wallets(cfg: dict, total: int, stem: str) -> list[Wallet]:
    width = serial_width(total)
    wallets: list[Wallet] = []
    seen_addr: set[str] = set()
    seen_words: set[str] = set()
    for i in range(total):
        mn = " ".join(new_mnemonic(cfg["words"]).split())
        addr = derive_address(mn)
        if len(mn.split()) != cfg["words"] or not addr.startswith("bc1q") or len(addr) != 42:
            sys.exit("Sanity check failed for a generated wallet - aborting, nothing was written.")
        if addr in seen_addr or mn in seen_words:
            sys.exit("Duplicate wallet generated - this must never happen. Aborting.")
        seen_addr.add(addr)
        seen_words.add(mn)
        wallets.append(Wallet(f"{cfg['serial_prefix']}{stem}{to_b36(i, width)}", addr, mn))
    return wallets


# --------------------------------------------------------------------------------------
# sheet planning: pack as many cards as possible
# --------------------------------------------------------------------------------------
@dataclass
class Plan:
    page_w: float
    page_h: float
    cols: int
    rows: int
    direction: str            # single | side | stack
    cw: float
    ch: float
    gap: float
    ox: float
    oy: float
    landscape: bool

    @property
    def uw(self) -> float:
        return 2 * self.cw + self.gap if self.direction == "side" else self.cw

    @property
    def uh(self) -> float:
        return 2 * self.ch + self.gap if self.direction == "stack" else self.ch

    @property
    def per_sheet(self) -> int:       # wallets per sheet
        return self.cols * self.rows

    def cards(self, i: int) -> list[tuple[str, float, float]]:
        r, c = divmod(i, self.cols)
        x = self.ox + c * (self.uw + self.gap)
        y = self.oy + r * (self.uh + self.gap)
        if self.direction == "single":
            return [("public", x, y), ("private", x, y)]
        if self.direction == "side":
            return [("public", x, y), ("private", x + self.cw + self.gap, y)]
        return [("public", x, y), ("private", x, y + self.ch + self.gap)]

    def used_percent(self) -> float:
        n_cards = self.per_sheet * (2 if self.direction != "single" else 1)
        return 100.0 * n_cards * self.cw * self.ch / (self.page_w * self.page_h)

    def describe(self, cfg: dict) -> str:
        orient = "landscape" if self.landscape else "portrait"
        if self.direction == "single":
            how = "separate sheets: public cards on one, private cards on the other (same positions)"
            cards = self.per_sheet
        else:
            how = ("public | private side by side" if self.direction == "side"
                   else "public above private")
            cards = 2 * self.per_sheet
        return (f"{str(cfg['sheet_size']).upper()} {orient}, {how}\n"
                f"  {self.per_sheet} wallets per sheet ({cards} cards per sheet), paper used: {self.used_percent():.0f}%")


def make_plan(cfg: dict) -> Plan:
    sw, sh = sheet_dims(cfg["sheet_size"])
    M, g = float(cfg["sheet_margin_mm"]), float(cfg["card_gap_mm"])
    cw, ch = float(cfg["card_width_mm"]), float(cfg["card_height_mm"])
    if cfg["layout"] == "separate":
        dirs = ["single"]
    elif cfg["pair_direction"] == "auto":
        dirs = ["stack", "side"]          # on equal paper use, 'stack' (public above private) wins
    else:
        dirs = [cfg["pair_direction"]]
    best = None
    for landscape, (pw, ph) in ((False, (sw, sh)), (True, (sh, sw))):
        for d in dirs:
            uw = 2 * cw + g if d == "side" else cw
            uh = 2 * ch + g if d == "stack" else ch
            cols = int((pw - 2 * M + g + 1e-9) // (uw + g))
            rows = int((ph - 2 * M + g + 1e-9) // (uh + g))
            if cols < 1 or rows < 1:
                continue
            if best is None or cols * rows > best[0]:
                used_w = cols * uw + (cols - 1) * g
                used_h = rows * uh + (rows - 1) * g
                best = (cols * rows, Plan(pw, ph, cols, rows, d, cw, ch, g,
                                          (pw - used_w) / 2, (ph - used_h) / 2, landscape))
    if best is None:
        sys.exit("The cards do not fit on this sheet size (check sheet_size, margins and card size in config.toml).")
    return best[1]


# --------------------------------------------------------------------------------------
# text helpers (Persian shaping + bidi + wrapping)
# --------------------------------------------------------------------------------------
_RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")


def is_rtl(s: str) -> bool:
    return bool(_RTL.search(s))


def shape(s: str) -> str:
    return get_display(arabic_reshaper.reshape(s)) if is_rtl(s) else s


def text_width(s: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(shape(s), font, size)


def fit_size(s: str, font: str, max_w: float, size: float, min_size: float = 4.0) -> float:
    w = text_width(s, font, size)
    return size if w <= max_w else max(min_size, size * max_w / w)


def put(c, s, x, y, font, size, *, align="left", color=BLACK, bold=False) -> None:
    """Draw one line. bold = simulated (the bundled monospace font has a single weight)."""
    t = shape(s)
    w = pdfmetrics.stringWidth(t, font, size)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    c.saveState()
    to = c.beginText()
    to.setTextOrigin(x, y)
    to.setFont(font, size)
    to.setFillColor(color)
    if bold:
        to.setTextRenderMode(2)
        c.setStrokeColor(color)
        c.setLineWidth(max(0.15, size * 0.035))
    to.textOut(t)
    c.drawText(to)
    c.restoreState()


def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            cand = f"{cur} {w}".strip()
            if text_width(cand, font, size) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def draw_block(c, text, x, top, max_w, max_h, font, size, *, color=BLACK, align="auto", bold=False,
               min_size=5.0, leading=1.3, para_gap=0.35) -> float:
    """Wrapped text (str or list of paragraphs) in a box; the font shrinks to fit.
    Returns the y of the bottom of the text. Raises LayoutError if it can never fit."""
    paras = [text] if isinstance(text, str) else list(text)
    paras = [p for p in paras if p and p.strip()]
    if not paras:
        return top
    s = float(size)
    while True:
        wrapped = [wrap(p, font, s, max_w) for p in paras]
        h = sum(len(w) for w in wrapped) * s * leading + para_gap * s * (len(paras) - 1)
        if h <= max_h + 0.01:
            break
        s -= 0.2
        if s < min_size:
            raise LayoutError(
                f"Text does not fit its area ({max_w / mm:.0f} x {max_h / mm:.1f} mm): '{paras[0][:45]}...'\n"
                f"Shorten that text in config.toml.")
    y = top - s * 0.95
    for para, lines in zip(paras, wrapped):
        mode = align if align != "auto" else ("right" if is_rtl(para) else "left")
        for ln in lines:
            if mode == "right":
                put(c, ln, x + max_w, y, font, s, align="right", color=color, bold=bold)
            elif mode == "center":
                put(c, ln, x + max_w / 2, y, font, s, align="center", color=color, bold=bold)
            else:
                put(c, ln, x, y, font, s, color=color, bold=bold)
            y -= s * leading
        y -= s * para_gap
    return top - h


def draw_qr(c, data: str, x: float, y: float, size: float) -> None:
    w = QrCodeWidget(data, barLevel="M", barBorder=1)
    x0, y0, x1, y1 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def draw_logo(c, path, x: float, y: float, max_w: float, max_h: float) -> None:
    if not path:
        return
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    k = min(max_w / iw, max_h / ih)
    c.drawImage(img, x, y + (max_h - ih * k) / 2, iw * k, ih * k, mask="auto")


def watermark(c, W: float, H: float) -> None:
    c.saveState()
    c.setFillColor(RED)
    c.setFillAlpha(0.16)
    c.setFont("Helvetica-Bold", min(W, H) / 8)
    c.translate(W / 2, H / 2)
    c.rotate(25)
    c.drawCentredString(0, 0, "SAMPLE - DO NOT FUND")
    c.restoreState()


# --------------------------------------------------------------------------------------
# the two cards (designed for 85.6 x 54 mm; origin = bottom-left corner of the card)
# --------------------------------------------------------------------------------------
def draw_public(c, cfg: dict, rec: Wallet, W: float, H: float) -> None:
    M = 3 * mm
    accent = HexColor(cfg["accent_color"])

    # header: logo left, brand right
    logo_w = 22 * mm if cfg["_logo"] else 0
    draw_logo(c, cfg["_logo"], M, H - 2.5 * mm - 8.5 * mm, logo_w, 8.5 * mm)
    hx = M + (logo_w + 2 * mm if logo_w else 0)
    hw = W - M - hx
    draw_block(c, cfg["brand_name"], hx, H - 2.5 * mm, hw, 5 * mm, "Body", 10.5, color=accent, align="right", bold=True)
    draw_block(c, cfg["tagline"], hx, H - 7.4 * mm, hw, 3.6 * mm, "Body", 6.5, color=GRAY, align="right")
    c.setStrokeColor(accent)
    c.setLineWidth(0.9)
    c.line(M, H - 12.5 * mm, W - M, H - 12.5 * mm)

    # body: QR | serial + address | explorer QR
    top = H - 14.5 * mm
    q1 = 26 * mm
    draw_qr(c, rec.address, M, top - q1, q1)
    q2 = 20 * mm if cfg["explorer_url"] else 0
    col_x = M + q1 + 2 * mm
    col_w = (W - M - (q2 + 2 * mm if q2 else 0)) - col_x
    cx = col_x + col_w / 2

    y = top
    s1 = fit_size(rec.serial, "Body", col_w, 11.0)
    put(c, rec.serial, cx, y - s1 * 0.9, "Body", s1, align="center", bold=True)
    y -= s1 * 1.4
    if cfg["amount_label"]:
        put(c, cfg["amount_label"], cx, y - 8.5 * 0.9, "Body", 8.5, align="center", bold=True)
        y -= 8.5 * 1.4
    y = draw_block(c, cfg["label_address"], col_x, y, col_w, 8 * mm, "Body", 6.0, color=GRAY, align="center") - 1.0 * mm
    half = (len(rec.address) + 1) // 2
    l1, l2 = rec.address[:half], rec.address[half:]
    sa = min(7.2, fit_size(l1, "Body", col_w, 7.2))
    put(c, l1, cx, y - sa * 0.9, "Body", sa, align="center")
    put(c, l2, cx, y - sa * 2.15, "Body", sa, align="center")

    if q2:
        qx = W - M - q2
        draw_qr(c, cfg["explorer_url"] + rec.address, qx, top - q2, q2)
        cy = draw_block(c, cfg["label_verify"], qx, top - q2 - 0.6 * mm, q2, 3.6 * mm, "Body", 5.8,
                        color=GRAY, align="center")
        put(c, urlparse(cfg["explorer_url"]).netloc, qx + q2 / 2, cy - 5.0 * 0.95, "Body", 5.0,
            align="center", color=GRAY)

    # footer
    c.setStrokeColor(LIGHT)
    c.setLineWidth(0.4)
    c.line(M, 12.2 * mm, W - M, 12.2 * mm)
    draw_block(c, cfg["outside_notice"], M, 11.5 * mm, W - 2 * M, 6.0 * mm, "Body", 6.2, align="center")
    draw_block(c, cfg["contact"], M, 5.2 * mm, W - 2 * M, 3.2 * mm, "Body", 6.2, color=GRAY, align="center")


def draw_private(c, cfg: dict, rec: Wallet, W: float, H: float) -> None:
    M = 3 * mm
    n = cfg["words"]
    inner_w = W - 2 * M

    # header: logo left, red title + serial right
    logo_w = 22 * mm if cfg["_logo"] else 0
    draw_logo(c, cfg["_logo"], M, H - 2.5 * mm - 8.5 * mm, logo_w, 8.5 * mm)
    hx = M + (logo_w + 2 * mm if logo_w else 0)
    hw = W - M - hx
    draw_block(c, cfg["inside_title"], hx, H - 2.5 * mm, hw, 5 * mm, "Body", 9.5, color=RED, align="right", bold=True)
    draw_block(c, rec.serial, hx, H - 7.4 * mm, hw, 3.6 * mm, "Body", 7.5, align="right", bold=True)
    c.setStrokeColor(RED)
    c.setLineWidth(0.9)
    c.line(M, H - 12.5 * mm, W - M, H - 12.5 * mm)

    # recovery words (left) + QR of the words (right)
    qr_on = cfg["private_qr"] == "words"
    qr = (21 if n == 12 else 26) * mm if qr_on else 0
    left_w = inner_w - (qr + 2 * mm if qr_on else 0)
    cols = 3 if qr_on else 4
    rows = n // cols
    col_w = (left_w - 4 * mm) / cols
    fs = min(8.5, fit_size("24. xxxxxxxx", "Body", col_w - 0.3 * mm, 8.5))     # worst case -> same size on every card
    row_h = fs * (1.5 if n == 12 else 1.38)
    box_top = H - 14 * mm
    box_h = rows * row_h + 2.4 * mm
    c.setStrokeColor(RED)
    c.setLineWidth(0.7)
    c.roundRect(M, box_top - box_h, left_w, box_h, 1.5 * mm, stroke=1, fill=0)
    if qr_on:
        qx = W - M - qr
        draw_qr(c, rec.mnemonic, qx, box_top - qr, qr)       # plain text: the words separated by single spaces
        draw_block(c, cfg["label_private_qr"], qx, box_top - qr - 0.6 * mm, qr, 6 * mm, "Body", 5.8,
                   color=GRAY, align="center")
    num_w = text_width("24.", "Body", fs)
    sp_w = text_width("24. ", "Body", fs)
    for i, word in enumerate(rec.mnemonic.split()):
        k, r = divmod(i, rows)                       # fill column by column: 1-3 | 4-6 | ...
        x0 = M + 2 * mm + k * col_w
        yb = box_top - 1.2 * mm - r * row_h - fs * 0.95
        put(c, f"{i + 1}.", x0 + num_w, yb, "Body", fs, align="right", color=GRAY)
        put(c, word, x0 + sp_w, yb, "Body", fs)

    # address (only 12-word cards without QR have the room) + instructions
    y = box_top - box_h
    if n == 12 and not qr_on:
        sa = min(7.5, fit_size(rec.address, "Body", inner_w, 7.5))
        put(c, rec.address, W / 2, y - 1.2 * mm - sa * 0.9, "Body", sa, align="center", color=GRAY)
        y -= 1.2 * mm + sa * 1.3
    ins_top = y - 1.5 * mm
    draw_block(c, cfg["inside_instructions"], M, ins_top, left_w, ins_top - 5.0 * mm, "Body", 6.4, para_gap=0.3)
    draw_block(c, cfg["contact"], M, 4.6 * mm, inner_w, 3.0 * mm, "Body", 6.0, color=GRAY, align="center")


def place_card(c, cfg: dict, rec: Wallet, kind: str, x_mm: float, ytop_mm: float, page_h_mm: float,
               preview: bool) -> None:
    cw, ch = cfg["card_width_mm"], cfg["card_height_mm"]
    W, H = cw * mm, ch * mm
    x, y = x_mm * mm, (page_h_mm - ytop_mm - ch) * mm
    c.saveState()
    c.translate(x, y)
    p = c.beginPath()
    p.rect(0, 0, W, H)
    c.clipPath(p, stroke=0, fill=0)
    (draw_public if kind == "public" else draw_private)(c, cfg, rec, W, H)
    if preview:
        watermark(c, W, H)
    c.restoreState()
    c.setStrokeColor(CUT)                 # cutting guide
    c.setLineWidth(0.25)
    c.rect(x, y, W, H, stroke=1, fill=0)


def render_sheets(cfg: dict, plan: Plan, wallets: list[Wallet], targets: dict, preview: bool) -> int:
    """targets: {'sheet': path} for pairs, {'public': path, 'private': path} for separate. Returns #sheets."""
    separate = cfg["layout"] == "separate"
    canv = {}
    for key, tgt in targets.items():
        cv = canvas.Canvas(tgt if isinstance(tgt, io.BytesIO) else str(tgt),
                           pagesize=(plan.page_w * mm, plan.page_h * mm))
        cv.setTitle({"sheet": "Cards (public + private) - SECRET", "public": "Public cards",
                     "private": "Private cards - SECRET"}[key])
        canv[key] = cv
    per = plan.per_sheet
    n_sheets = math.ceil(len(wallets) / per)
    for s in range(n_sheets):
        for i, rec in enumerate(wallets[s * per:(s + 1) * per]):
            for kind, x, y in plan.cards(i):
                cv = canv[kind] if separate else canv["sheet"]
                place_card(cv, cfg, rec, kind, x, y, plan.page_h, preview)
        for cv in canv.values():
            cv.showPage()
    for cv in canv.values():
        cv.save()
    return n_sheets


def write_ledger(path: Path, cfg: dict, wallets: list[Wallet], human_dt: str, now: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["serial", "address", "jalali_datetime", "created_utc", "sheet", "slot", "explorer_link",
                    "status", "sold_to", "funding_txid", "notes"])
        for r in wallets:
            link = (cfg["explorer_url"] + r.address) if cfg["explorer_url"] else ""
            w.writerow([r.serial, r.address, human_dt, now, r.sheet, r.slot, link, "", "", "", ""])


@contextmanager
def private_creation():
    """Restrict creation from the first write; CLI is single-threaded.

    Process-wide umask is restored even on failure. This is NOT a defense
    against a hostile output parent being renamed/replaced with a symlink.
    """
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse messages can contain credential-bearing argument values.
        super().error("invalid command-line arguments; use --help")


# --------------------------------------------------------------------------------------
def main() -> None:
    ap = _PrivateArgumentParser(description="Offline bitcoin card sheet generator")
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--count", type=int, help="number of SHEETS to make (each is filled completely)")
    ap.add_argument("--out", default="out", help="output folder (default ./out)")
    ap.add_argument("--preview", action="store_true",
                    help="make ONE sample sheet with a PUBLIC test phrase to check the design")
    ap.add_argument("--allow-online", action="store_true",
                    help="skip advisory connectivity probes; still requires --acknowledge-offline")
    ap.add_argument("--acknowledge-offline", action="store_true",
                    help="confirm you disconnected networking and use a trusted offline machine/printer")
    ap.add_argument("--db", help="database connection string: sqlite:///wallets.db or postgresql://user:pass@host/db "
                                 "(stores serial + public address only). Also read from env BTC_DB_URL or config db_url")
    ap.add_argument("--db-table", help="table name (default from config: wallets)")
    args = ap.parse_args()

    if not args.preview and not args.acknowledge_offline:
        sys.exit("Real generation requires --acknowledge-offline after disconnecting networking.\n"
                 "Failed connectivity probes do NOT prove isolation. Use a trusted offline live environment "
                 "and an offline printer; this is not a guarantee of security.")

    cfg = load_config(Path(args.config))
    register_fonts(cfg)
    plan = make_plan(cfg)
    self_test()
    print("Layout:", plan.describe(cfg))

    # database (optional): validate the string now, connect later
    btc_db = None
    db_url = db_table = ""
    if not args.preview:
        # Resolve without importing the optional database layer.
        db_url = (args.db or os.environ.get("BTC_DB_URL") or cfg["db_url"] or "").strip()
        if db_url:
            sys.path.insert(0, str(HERE))
            import btc_db as _db
            btc_db = _db
            db_table = args.db_table or cfg["db_table"]
    elif args.db or os.environ.get("BTC_DB_URL") or cfg["db_url"]:
        print("(preview: the database is not touched)")
    if db_url:
        try:
            btc_db.check_table(db_table)
            print(f"Database: {btc_db.describe(db_url)}, table '{db_table}'")
        except btc_db.DbError as e:
            sys.exit(f"Database setting problem: {e}")

    now = now_local(cfg)
    stem, human = serial_stem(now, cfg["serial_minsec"])
    width = serial_width(plan.per_sheet)

    def samples(n: int) -> list[Wallet]:
        mn = TEST_MNEMONIC if cfg["words"] == 12 else TEST_MNEMONIC_24
        addr = derive_address(mn)
        return [Wallet(f"{cfg['serial_prefix']}{stem}{to_b36(i, width)}", addr, mn) for i in range(n)]

    separate = cfg["layout"] == "separate"
    keys = ["public", "private"] if separate else ["sheet"]
    try:   # dry run: catches layout / config / logo problems before any real key exists
        render_sheets(cfg, plan, samples(plan.per_sheet), {k: io.BytesIO() for k in keys}, True)
    except LayoutError as e:
        sys.exit(f"Layout problem: {e}")

    if args.preview:
        wallets, folder = samples(plan.per_sheet), Path(args.out) / f"preview_{stem}"
        n_sheets_wanted = 1
    else:
        if not args.count or not (1 <= args.count <= 500):
            sys.exit("Give the number of sheets, e.g.  --count 1")
        if not args.allow_online and looks_online():
            sys.exit("Connectivity detected. Real keys must be made offline.\n"
                     "Disconnect Wi-Fi / unplug the network cable and run again.")
        print("Offline acknowledgement received; probes cannot prove network isolation.")
        n_sheets_wanted = args.count
        if db_url:   # pre-flight: a remote database is normally NOT reachable from an offline computer
            try:
                btc_db.check(db_url, db_table)
                print("Database reachable.")
            except btc_db.DbError as e:
                print(f"Database NOT reachable right now ({e}).\n"
                      f"  The wallets will still be created; load them later with btc_db.py import.")
        wallets = make_wallets(cfg, args.count * plan.per_sheet, stem)
        folder = Path(args.out) / f"batch_{stem}"
    if len({r.serial for r in wallets}) != len(wallets):
        sys.exit("Duplicate serial in batch - aborting, nothing was written.")
    for i, r in enumerate(wallets):
        r.sheet, r.slot = i // plan.per_sheet + 1, i % plan.per_sheet + 1

    files = ({"public": folder / "public_sheets.pdf", "private": folder / "private_sheets.pdf"}
             if separate else {"sheet": folder / "sheets.pdf"})
    with private_creation():
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            sys.exit(f"Folder already exists, refusing to overwrite: {folder}")
        try:
            os.chmod(folder, 0o700)
            render_sheets(cfg, plan, wallets, files, args.preview)
            created = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            for p in files.values():
                os.chmod(p, 0o600)
            if not args.preview:
                write_ledger(folder / "ledger.csv", cfg, wallets, human, created)
        except BaseException as error:
            cleanup_failed = False
            # Only our named artifacts, never recursive removal of an output tree.
            for p in [*files.values(), folder / "ledger.csv"]:
                try:
                    p.unlink(missing_ok=True)
                except BaseException:
                    cleanup_failed = True
            try:
                folder.rmdir()
            except BaseException:
                cleanup_failed = True
            message = ("Output failed; no successful batch was recorded."
                       + (" Cleanup incomplete: treat the output folder as SECRET and do not use it."
                          if cleanup_failed else " Partial files removed."))
            if (isinstance(error, (OSError, LayoutError))
                    or isinstance(error, SystemExit) and error.code in (None, 0)):
                sys.exit(message)
            try:
                print(message, file=sys.stderr)
            except BaseException:
                pass  # Warning delivery must not replace the primary failure.
            raise

    db_failed = False
    db_msg = ""
    if db_url and not args.preview:      # only AFTER the files exist; only serial + public address are passed
        try:
            rows = [btc_db.Row(r.serial, r.address, human, created) for r in wallets]
            n_ins, _ = btc_db.save_rows(db_url, db_table, rows)
            db_msg = f"Database: {n_ins} wallet(s) saved to table '{db_table}' ({btc_db.describe(db_url)})"
        except btc_db.DbError as e:
            db_failed = True
            db_msg = (f"Database: NOT saved - {e}\n"
                      f"  The files above are complete. Save the records later (any computer):\n"
                      f"    python btc_db.py import \"{folder / 'ledger.csv'}\" --db \"<connection string>\" "
                      f"--table {db_table}")

    print(f"\nCreated {len(wallets)} wallet(s) on {n_sheets_wanted} sheet(s) in: {folder}")
    print(f"Serial prefix (Jalali {human}): {cfg['serial_prefix']}{stem}")
    for r in wallets:
        print(f"  {r.serial}  {r.address}   (sheet {r.sheet}, slot {r.slot})")
    if separate:
        print("\n  public_sheets.pdf  : address + QR cards - safe to print anywhere\n"
              "  private_sheets.pdf : SECRET - print on an offline printer (USB), then delete the file\n"
              "  (card k on the public sheet matches card k, same position, on the private sheet)")
    else:
        print("\n  sheets.pdf : SECRET (contains the recovery words) - print on an offline printer (USB), "
              "then delete the file")
    if not args.preview:
        print("  ledger.csv : your record, contains no secrets")
    if db_msg:
        print("\n" + db_msg)
    print()
    if args.preview:
        print("This was a PREVIEW with a public test phrase. Nothing here is a real wallet.")
    else:
        print("Next: restore ONE private card in Sparrow/Electrum and confirm it shows the same address "
              "BEFORE funding any card.")
    if db_failed:
        sys.exit(3)


if __name__ == "__main__":
    main()
