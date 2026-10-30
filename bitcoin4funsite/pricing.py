"""Exact, offline Bitcoin amount conversion and envelope pricing."""

import re
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, localcontext

SATOSHIS_PER_BTC = 100_000_000
MAX_SATOSHIS = 21_000_000 * SATOSHIS_PER_BTC


def btc_to_sats(text: str) -> int:
    """Convert unsigned ASCII BTC text (at most eight decimals), without rounding.

    Whitespace, signs, scientific notation and amounts above 21 million BTC
    raise ValueError. Zero is valid; no input normalization is performed.
    """
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,8})?", text):
        raise ValueError("BTC must be unsigned ASCII decimal text with at most 8 decimals")
    amount = Decimal(text)
    if amount > Decimal("21000000"):
        raise ValueError("BTC exceeds the 21 million supply limit")
    with localcontext(Context(prec=32)):
        return int(amount * SATOSHIS_PER_BTC)


def sats_to_btc(value: int | str) -> str:
    """Format unsigned satoshis as BTC with eight decimals, without rounding.

    Accept an int (not bool) or ASCII digit-only string in the supply range.
    All invalid inputs raise ValueError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Satoshis must be an integer or unsigned ASCII digit string")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Satoshis must be an integer or unsigned ASCII digit string")
    amount = Decimal(value)
    if not 0 <= amount <= MAX_SATOSHIS:
        raise ValueError("Satoshis must be within the 21 million BTC supply limit")
    with localcontext(Context(prec=32)):
        return format(amount / SATOSHIS_PER_BTC, ".8f")


def _decimal_text(value: Decimal) -> str:
    """Render JSON-safe non-exponential decimal text without redundant zeros."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _quote_row(principal: int, network: int, printing: int,
               satoshi_toman: Decimal, budget: int | None = None) -> dict:
    operator = _ceil(Decimal("0.15") * (principal + network + printing))
    total_sats = principal + network + printing + operator
    total_toman = _ceil(total_sats * satoshi_toman)
    return {
        "principal_sats": principal, "btc": sats_to_btc(principal),
        "network_sats": network, "print_sats": printing,
        "operator_sats": operator, "total_sats": total_sats,
        "total_toman": total_toman, "total_rial": total_toman * 10,
        "budget_toman": budget,
        "remainder_toman": 0 if budget is None else budget - total_toman,
    }


def _rate(value, maximum: Decimal, name: str) -> Decimal:
    """Validate exact decimal rates, bounded to 18 fractional places."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{name} must be decimal text, int or Decimal (not float/bool)")
    if isinstance(value, str) and (
        len(value) > 64
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,18})?", value)
    ):
        raise ValueError(f"{name} must be unsigned ASCII decimal text, at most 18 decimals")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a finite decimal") from error
    if not amount.is_finite() or not 0 < amount <= maximum:
        raise ValueError(f"{name} must be positive and no greater than {maximum}")
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -18:
        raise ValueError(f"{name} must have at most 18 fractional places")
    return amount


def quote_table(btc_toman, usdt_toman, fee_rate) -> dict:
    """Return an offline quote using the supplied economy fee in sat/vbyte.

    Rates accept int, Decimal or unsigned ASCII decimal text, never float/bool.
    Raw prices are positive and <= 1e15 toman; fee is positive and <= 10,000
    sat/vbyte. Rates have at most 18 decimal places (minimum positive 1e-18).
    Malformed/out-of-bounds inputs raise ValueError.

    Both raw prices are multiplied by 1.005 before costing. Every following
    ceiling is explicit (no intermediate currency rounding):
      network_sats = ceil(fee_rate * 141)
      print_sats = ceil(0.15 * adjusted_usdt / adjusted_satoshi_toman)
      operator_sats = ceil(0.15 * (principal + network_sats + print_sats))
      total_toman = ceil((principal + network_sats + print_sats + operator_sats)
                         * adjusted_satoshi_toman)
      total_rial = total_toman * 10
    The 141 vB estimate assumes one P2WPKH input and two P2WPKH outputs.
    A first 500-satoshi quote is always shown, even above 2,000,000 toman.
    Budget rows begin at the next strictly greater 100,000-toman multiple;
    binary search finds the largest supply-bounded principal that fits each
    ceiling. Remainder is budget minus actual rounded cost (zero without a
    budget); it is never hidden by pretending the whole budget was spent.
    """
    raw_btc = _rate(btc_toman, Decimal("1e15"), "btc_toman")
    raw_usdt = _rate(usdt_toman, Decimal("1e15"), "usdt_toman")
    rate = _rate(fee_rate, Decimal("10000"), "fee_rate")
    with localcontext(Context(prec=128)):
        adjusted_btc = raw_btc * Decimal("1.005")
        adjusted_usdt = raw_usdt * Decimal("1.005")
        satoshi_toman = adjusted_btc / SATOSHIS_PER_BTC
        network_sats = _ceil(rate * 141)
        print_sats = _ceil(Decimal("0.15") * adjusted_usdt / satoshi_toman)
        first = _quote_row(500, network_sats, print_sats, satoshi_toman)
        rows = [first]
        first_budget = (first["total_toman"] // 100_000 + 1) * 100_000
        for budget in range(first_budget, 2_000_001, 100_000):
            low, high = 500, MAX_SATOSHIS
            while low < high:
                middle = (low + high + 1) // 2
                candidate = _quote_row(middle, network_sats, print_sats, satoshi_toman)
                if candidate["total_toman"] <= budget:
                    low = middle
                else:
                    high = middle - 1
            rows.append(_quote_row(low, network_sats, print_sats, satoshi_toman, budget))
        return {
            "rates": {
                "btc_toman": _decimal_text(adjusted_btc),
                "usdt_toman": _decimal_text(adjusted_usdt),
                "satoshi_toman": _decimal_text(satoshi_toman),
            },
            "assumptions": {
                "exchange_fee_percent": "0.5", "operator_fee_percent": "15",
                "print_usd": "0.15", "transaction_vbytes": 141,
                "network_fee_rate": _decimal_text(rate),
            },
            "costs": {"network_sats": network_sats, "print_sats": print_sats},
            "rows": rows,
        }
