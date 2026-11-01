"""Exact, offline Bitcoin amount conversion and envelope pricing."""

import re
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, localcontext

SATOSHIS_PER_BTC = 100_000_000
MAX_SATOSHIS = 21_000_000 * SATOSHIS_PER_BTC


def btc_to_sats(text: str) -> int:
    """Convert unsigned ASCII BTC text (at most eight decimals), without rounding.

    Whitespace, signs, scientific notation, text over 64 characters and amounts
    above 21 million BTC raise ValueError. Zero is valid; no normalization.
    """
    if (not isinstance(text, str) or len(text) > 64
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,8})?", text)):
        raise ValueError("BTC must be unsigned ASCII decimal text, at most 64 characters and 8 decimals")
    amount = Decimal(text)
    if amount > Decimal("21000000"):
        raise ValueError("BTC exceeds the 21 million supply limit")
    with localcontext(Context(prec=32)):
        return int(amount * SATOSHIS_PER_BTC)


def sats_to_btc(value: int | str) -> str:
    """Format unsigned satoshis as BTC with eight decimals, without rounding.

    Accept an int (not bool) or <=64 ASCII digits in the supply range.
    All invalid inputs raise ValueError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Satoshis must be an integer or unsigned ASCII digit string")
    if isinstance(value, str) and (len(value) > 64 or not re.fullmatch(r"[0-9]+", value)):
        raise ValueError("Satoshis must be unsigned ASCII digits, at most 64 characters")
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
               satoshi_toman: Decimal, budget: int | None = None, tag: int = 0) -> dict:
    operator = _ceil(Decimal("0.15") * (principal + network + printing + tag))
    total_sats = principal + network + printing + tag + operator
    total_toman = _ceil(total_sats * satoshi_toman)
    return {
        "principal_sats": principal, "btc": sats_to_btc(principal),
        "network_sats": network, "print_sats": printing, "tag_sats": tag,
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
    if not isinstance(exponent, int) or not -18 <= exponent <= 0:
        raise ValueError(f"{name} must have at most 18 fractional places and no positive exponent")
    return amount


def _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag=False):
    """Prepare the shared adjusted rates and fixed costs in a private context."""
    if type(include_tag) is not bool:
        raise ValueError("include_tag must be a boolean")
    raw_btc = _rate(btc_toman, Decimal("1e15"), "btc_toman")
    raw_usdt = _rate(usdt_toman, Decimal("1e15"), "usdt_toman")
    rate = _rate(fee_rate, Decimal("10000"), "fee_rate")
    with localcontext(Context(prec=128)):
        adjusted_btc = raw_btc * Decimal("1.005")
        adjusted_usdt = raw_usdt * Decimal("1.005")
        satoshi_toman = adjusted_btc / SATOSHIS_PER_BTC
        network_sats = _ceil(rate * 141)
        print_sats = _ceil(Decimal("0.15") * adjusted_usdt / satoshi_toman)
        tag_sats = _ceil(Decimal("0.12") * adjusted_usdt / satoshi_toman) if include_tag else 0
        metadata = {
            "rates": {
                "btc_toman": _decimal_text(adjusted_btc),
                "usdt_toman": _decimal_text(adjusted_usdt),
                "satoshi_toman": _decimal_text(satoshi_toman),
            },
            "assumptions": {
                "exchange_fee_percent": "0.5", "operator_fee_percent": "15",
                "print_usd": "0.15", "tag_usd": "0.12", "include_tag": include_tag,
                "transaction_vbytes": 141,
                "network_fee_rate": _decimal_text(rate),
            },
            "costs": {"network_sats": network_sats, "print_sats": print_sats, "tag_sats": tag_sats},
        }
    return satoshi_toman, network_sats, print_sats, tag_sats, metadata


def _unsigned_integer(value, name: str, minimum: int, maximum: int) -> int:
    """Parse a bounded integer without normalizing signs, spaces or exponents."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be an int or unsigned ASCII digit string")
    if isinstance(value, str):
        if len(value) > 64 or not re.fullmatch(r"[0-9]+", value):
            raise ValueError(f"{name} must be unsigned ASCII digits, at most 64 characters")
        value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def raw_asset_toman(raw_btc, principal_sats) -> str:
    """Exact raw BTC asset value in toman as decimal text, without any fees.

    The rate follows quote_table validation, before its 0.5% exchange markup.
    Principal is an int or <=64 ASCII digits in [0, MAX_SATOSHIS]; zero and
    sub-package amounts are valid. No currency rounding is applied.
    """
    raw = _rate(raw_btc, Decimal("1e15"), "raw_btc")
    principal = _unsigned_integer(principal_sats, "principal_sats", 0, MAX_SATOSHIS)
    with localcontext(Context(prec=128)):
        return _decimal_text(raw * principal / SATOSHIS_PER_BTC)


def quote_for_principal(btc_toman, usdt_toman, fee_rate, principal_sats, *, include_tag=False) -> dict:
    """Quote one supply-bounded package; row fields keep the v1 numeric types.

    The returned row also includes the table's rates, assumptions and costs.
    Rates follow quote_table. Principal accepts int (not bool) or unsigned ASCII
    digits, at most 64 characters, in [500, MAX_SATOSHIS]. Otherwise ValueError.
    """
    principal = _unsigned_integer(principal_sats, "principal_sats", 500, MAX_SATOSHIS)
    satoshi_toman, network, printing, tag, metadata = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag)
    with localcontext(Context(prec=128)):
        row = _quote_row(principal, network, printing, satoshi_toman, tag=tag)
    return {**row, **metadata}


def quote_for_budget(btc_toman, usdt_toman, fee_rate, budget_toman, *, include_tag=False) -> dict:
    """Return the largest principal in [500, MAX_SATOSHIS] fitting the budget.

    Budget is a whole toman amount: int (not bool) or unsigned ASCII digits,
    at most 64 digits. There is no table's 2,000,000-toman cap. If 500 satoshis
    cannot be afforded, ValueError is raised (no fictitious principal or row).
    Successful rows include rates/assumptions/costs and the unspent remainder.
    """
    budget = _unsigned_integer(budget_toman, "budget_toman", 0, 10**64 - 1)
    satoshi_toman, network, printing, tag, metadata = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag)
    with localcontext(Context(prec=128)):
        minimum = _quote_row(500, network, printing, satoshi_toman, tag=tag)
        if minimum["total_toman"] > budget:
            raise ValueError(
                f"budget_toman insufficient for minimum 500-satoshi package; "
                f"requires {minimum['total_toman']} toman"
            )
        low, high = 500, MAX_SATOSHIS
        while low < high:
            middle = (low + high + 1) // 2
            candidate = _quote_row(middle, network, printing, satoshi_toman, tag=tag)
            if candidate["total_toman"] <= budget:
                low = middle
            else:
                high = middle - 1
        row = _quote_row(low, network, printing, satoshi_toman, budget, tag=tag)
    return {**row, **metadata}


def quote_table(btc_toman, usdt_toman, fee_rate, *, include_tag=False) -> dict:
    """Return an offline quote using the selected fee in sat/vbyte.

    Rates accept int, Decimal or unsigned ASCII decimal text, never float/bool.
    Raw prices are positive and <= 1e15 toman; fee is positive and <= 10,000
    sat/vbyte. Rates have at most 18 decimal places (minimum positive 1e-18).
    Malformed/out-of-bounds inputs raise ValueError. include_tag must be bool;
    it defaults to False. Tag cost uses the same USD/USDT assumption as print
    and is included in the operator subtotal, not the envelope principal.

    Both raw prices are multiplied by 1.005 before costing. Every following
    ceiling is explicit (no intermediate currency rounding):
      network_sats = ceil(fee_rate * 141)
      print_sats = ceil(0.15 * adjusted_usdt / adjusted_satoshi_toman)
      tag_sats = ceil(0.12 * adjusted_usdt / adjusted_satoshi_toman) if include_tag else 0
      operator_sats = ceil(0.15 * (principal + network_sats + print_sats + tag_sats))
      total_toman = ceil((principal + network_sats + print_sats + tag_sats + operator_sats)
                         * adjusted_satoshi_toman)
      total_rial = total_toman * 10
    The 141 vB estimate assumes one P2WPKH input and two P2WPKH outputs.
    A first 500-satoshi quote is always shown, even above 2,000,000 toman.
    Budget rows begin at the next strictly greater 100,000-toman multiple;
    binary search finds the largest supply-bounded principal that fits each
    ceiling. Remainder is budget minus actual rounded cost (zero without a
    budget); it is never hidden by pretending the whole budget was spent.
    """
    satoshi_toman, network_sats, print_sats, tag, metadata = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag)
    with localcontext(Context(prec=128)):
        first = _quote_row(500, network_sats, print_sats, satoshi_toman, tag=tag)
        rows = [first]
        first_budget = (first["total_toman"] // 100_000 + 1) * 100_000
        for budget in range(first_budget, 2_000_001, 100_000):
            low, high = 500, MAX_SATOSHIS
            while low < high:
                middle = (low + high + 1) // 2
                candidate = _quote_row(middle, network_sats, print_sats, satoshi_toman, tag=tag)
                if candidate["total_toman"] <= budget:
                    low = middle
                else:
                    high = middle - 1
            rows.append(_quote_row(low, network_sats, print_sats, satoshi_toman, budget, tag=tag))
        return {**metadata, "rows": rows}
