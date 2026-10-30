"""Real public-vector crypto + rendered PDF recovery (never generate entropy).

Sources: https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki
and https://github.com/trezor/python-mnemonic/blob/master/vectors.json
(English zero-entropy 128-bit / 256-bit vectors). Test-only public material.

Independent recovery deliberately does NOT call bip_utils: stdlib PBKDF2/HMAC,
explicit BIP32 private child derivation with python-ecdsa secp256k1 arithmetic,
and independent BIP173 witness-v0 encoding. Poppler extracts actual PDF text
and rasterizes actual vector QR; system libzbar decodes those pixels.
Requires pdftotext, pdftoppm (poppler-utils) and libzbar0 on Linux.
"""
import ctypes as ct
import ctypes.util
import builtins
import hashlib
import hmac
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from ecdsa import SECP256k1
from PIL import Image
import pytest

from test_generator_security import gen, deny_random_generation


PUBLIC_12 = ' '.join(['abandon'] * 11 + ['about'])
PUBLIC_24 = ' '.join(['abandon'] * 23 + ['art'])
BIP84_ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'


def recover_independently(words):
    seed = hashlib.pbkdf2_hmac('sha512', unicodedata.normalize('NFKD', words).encode(), b'mnemonic', 2048)
    digest = hmac.digest(b'Bitcoin seed', seed, 'sha512')
    key, chain = int.from_bytes(digest[:32], 'big'), digest[32:]
    def compressed(k):
        point = SECP256k1.generator * k
        return bytes([2 + (point.y() & 1)]) + point.x().to_bytes(32, 'big')
    for index in (0x80000054, 0x80000000, 0x80000000, 0, 0):
        data = (b'\0' + key.to_bytes(32, 'big')) if index & 0x80000000 else compressed(key)
        digest = hmac.digest(chain, data + index.to_bytes(4, 'big'), 'sha512')
        tweak = int.from_bytes(digest[:32], 'big')
        assert tweak < SECP256k1.order
        key, chain = (key + tweak) % SECP256k1.order, digest[32:]
        assert key
    witness = hashlib.new('ripemd160', hashlib.sha256(compressed(key)).digest()).digest()
    acc = bits = 0
    data = [0]  # witness version zero
    for byte in witness:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    values = [ord(c) >> 5 for c in 'bc'] + [0] + [ord(c) & 31 for c in 'bc'] + data + [0] * 6
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1ffffff) << 5) ^ value
        for bit, poly in enumerate((0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)):
            if (top >> bit) & 1:
                checksum ^= poly
    checksum ^= 1
    data += [(checksum >> (5 * (5 - i))) & 31 for i in range(6)]
    alphabet = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
    return 'bc1' + ''.join(alphabet[v] for v in data)


def decode_qrs(image):
    library = ctypes.util.find_library('zbar')
    assert library, 'Install libzbar0: QR decoding must not silently skip'
    zbar = ct.CDLL(library)
    signatures = {
        'zbar_image_scanner_create': (ct.c_void_p, []),
        'zbar_image_create': (ct.c_void_p, []),
        'zbar_image_set_format': (None, [ct.c_void_p, ct.c_ulong]),
        'zbar_image_set_size': (None, [ct.c_void_p, ct.c_uint, ct.c_uint]),
        'zbar_image_set_data': (None, [ct.c_void_p, ct.c_void_p, ct.c_ulong, ct.c_void_p]),
        'zbar_scan_image': (ct.c_int, [ct.c_void_p, ct.c_void_p]),
        'zbar_image_first_symbol': (ct.c_void_p, [ct.c_void_p]),
        'zbar_symbol_next': (ct.c_void_p, [ct.c_void_p]),
        'zbar_symbol_get_data': (ct.c_char_p, [ct.c_void_p]),
        'zbar_image_destroy': (None, [ct.c_void_p]),
        'zbar_image_scanner_destroy': (None, [ct.c_void_p]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(zbar, name)
        function.restype, function.argtypes = result, args
    scanner, handle = zbar.zbar_image_scanner_create(), zbar.zbar_image_create()
    try:
        image = image.convert('L')
        pixels = ct.create_string_buffer(image.tobytes())
        zbar.zbar_image_set_format(handle, int.from_bytes(b'Y800', 'little'))
        zbar.zbar_image_set_size(handle, *image.size)
        zbar.zbar_image_set_data(handle, pixels, len(image.tobytes()), None)
        assert zbar.zbar_scan_image(scanner, handle) >= 0
        symbol = zbar.zbar_image_first_symbol(handle)
        decoded = []
        while symbol:
            decoded.append(zbar.zbar_symbol_get_data(symbol).decode())
            symbol = zbar.zbar_symbol_next(symbol)
        return decoded
    finally:
        zbar.zbar_image_destroy(handle)
        zbar.zbar_image_scanner_destroy(scanner)


def test_official_bip84_vector_real_library():
    assert gen.derive_address(PUBLIC_12) == BIP84_ADDRESS
    assert recover_independently(PUBLIC_12) == BIP84_ADDRESS
    gen.self_test()


@pytest.mark.parametrize('phrase', [PUBLIC_12, PUBLIC_24], ids=['official-bip84-12', 'public-bip39-24'])
@pytest.mark.parametrize('layout', ['pairs', 'separate'])
def test_rendered_private_qr_matches_printed_words_and_independent_recovery(tmp_path, monkeypatch, phrase, layout):
    assert tmp_path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    cfg = dict(gen.DEFAULTS, _logo=None, words=len(phrase.split()), layout=layout)
    gen.register_fonts(cfg)
    plan = gen.make_plan(cfg)
    wallet = gen.Wallet('PUBLIC-TEST-DO-NOT-FUND', gen.derive_address(phrase), phrase)
    keys = ['public', 'private'] if layout == 'separate' else ['sheet']
    targets = {key: tmp_path / (key + '.pdf') for key in keys}
    # Observe the actual PDF descriptor immediately after open, before any bytes.
    original_open = builtins.open
    modes_at_open = []
    def observe_open(file, mode='r', *args, **kwargs):
        stream = original_open(file, mode, *args, **kwargs)
        if 'w' in mode and str(file).endswith('.pdf'):
            modes_at_open.append(os.fstat(stream.fileno()).st_mode & 0o777)
        return stream
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', observe_open)
        previous = os.umask(0)
        try:
            with gen.private_creation():
                gen.render_sheets(cfg, plan, [wallet], targets, True)
        finally:
            os.umask(previous)
    assert modes_at_open == [0o600] * len(targets)
    printed, decoded = {}, {}
    for key, pdf in targets.items():
        printed[key] = subprocess.run(['pdftotext', '-raw', str(pdf), '-'], check=True, capture_output=True, text=True).stdout
        subprocess.run(['pdftoppm', '-scale-to', '3500', '-singlefile', '-png', str(pdf), str(tmp_path / key)], check=True, capture_output=True)
        with Image.open(tmp_path / (key + '.png')) as image:
            decoded[key] = decode_qrs(image)
        assert 'SAMPLE - DO NOT FUND' in printed[key]
    private = 'private' if layout == 'separate' else 'sheet'
    public = 'public' if layout == 'separate' else 'sheet'
    numbered = re.findall(r'(?m)^(\d+)\.\s*\n?([a-z]+)\s*$', printed[private])
    assert [int(n) for n, _ in numbered] == list(range(1, cfg['words'] + 1))
    recovered_words = ' '.join(word for _, word in numbered)
    assert recovered_words == phrase
    assert recovered_words in decoded[private], 'Pixel-decoded private QR differs from printed mnemonic'
    # Public address is physically printed in two lines, not read from Wallet.
    printed_address = re.search(r'bc1q[a-z0-9]+\s*\n[a-z0-9]+', printed[public])
    assert printed_address
    address = ''.join(printed_address.group().split())
    assert recover_independently(recovered_words) == address
    assert address in decoded[public]
    if layout == 'separate':
        assert phrase not in decoded[public]
        assert not re.search(r'(?m)^1\.\s*', printed[public])
