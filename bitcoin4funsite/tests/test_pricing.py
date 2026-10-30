"""Offline unit tests for exact Bitcoin conversion and envelope pricing."""

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

# Keep discovery and direct execution independent of the caller's directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BitcoinConversionTests(unittest.TestCase):
    def test_btc_to_sats_preserves_smallest_unit_and_supply_limit(self):
        self.assertIsNotNone(importlib.util.find_spec("pricing"), "pricing must exist")
        pricing = importlib.import_module("pricing")
        convert = getattr(pricing, "btc_to_sats", None)
        self.assertTrue(callable(convert), "btc_to_sats must be implemented")
        for text, expected in (
            ("0", 0),
            ("0.00000001", 1),
            ("0.00000500", 500),
            ("1.12345678", 112345678),
            ("21000000.00000000", 2100000000000000),
        ):
            with self.subTest(text=text):
                self.assertEqual(convert(text), expected)

    def test_btc_to_sats_rejects_noncanonical_or_out_of_range_input(self):
        from pricing import btc_to_sats

        invalid = (
            "", " ", " 1", "1 ", "1\n", "+1", "-1", "-0", "1e-8",
            "NaN", "Infinity", "inf", ".1", "1.", "1_000", "1,000",
            "0.000000001", "1.000000000", "21000000.00000001",
            "21000001", "١", "１", "1.١", None, True, 1, 0.1,
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    btc_to_sats(value)

    def test_sats_to_btc_formats_fixed_eight_decimals_and_round_trips(self):
        pricing = importlib.import_module("pricing")
        convert = getattr(pricing, "sats_to_btc", None)
        self.assertTrue(callable(convert), "sats_to_btc must be implemented")
        for value, expected in (
            (0, "0.00000000"),
            (1, "0.00000001"),
            ("000500", "0.00000500"),
            (112345678, "1.12345678"),
            (2100000000000000, "21000000.00000000"),
        ):
            with self.subTest(value=value):
                self.assertEqual(convert(value), expected)
                self.assertEqual(pricing.btc_to_sats(expected), int(value))

    def test_sats_to_btc_rejects_fractional_signed_unicode_or_excess_amounts(self):
        from decimal import Decimal
        from pricing import sats_to_btc

        invalid = (
            -1, True, False, None, 1.0, Decimal("1"), "", " 1", "1 ",
            "1\n", "+1", "-0", "-1", "1.0", "1e3", "NaN", "Infinity",
            "1_000", "١", "１", 2100000000000001, "2100000000000001",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sats_to_btc(value)


class QuoteTableTests(unittest.TestCase):
    def test_first_quote_exposes_adjusted_rates_and_each_rounded_cost(self):
        pricing = importlib.import_module("pricing")
        quote_table = getattr(pricing, "quote_table", None)
        self.assertTrue(callable(quote_table), "quote_table must be implemented")
        quote = quote_table("10000000000", "100000", "1.1")
        self.assertEqual(quote["rates"], {
            "btc_toman": "10050000000", "usdt_toman": "100500",
            "satoshi_toman": "100.5",
        })
        self.assertEqual(quote["assumptions"], {
            "exchange_fee_percent": "0.5", "operator_fee_percent": "15",
            "print_usd": "0.15", "transaction_vbytes": 141,
            "network_fee_rate": "1.1",
        })
        self.assertEqual(quote["costs"], {"network_sats": 156, "print_sats": 150})
        self.assertEqual(quote["rows"][0], {
            "principal_sats": 500, "btc": "0.00000500", "network_sats": 156,
            "print_sats": 150, "operator_sats": 121, "total_sats": 927,
            "total_toman": 93164, "total_rial": 931640,
            "budget_toman": None, "remainder_toman": 0,
        })

    def test_budget_rows_maximize_principal_without_claiming_exact_utilization(self):
        from decimal import Decimal, ROUND_CEILING
        from pricing import quote_table

        quote = quote_table("10000000000", "100000", "1.1")
        rows = quote["rows"]
        budgets = list(range(100000, 2000001, 100000))
        self.assertEqual([row["budget_toman"] for row in rows[1:]], budgets)
        self.assertEqual(len(rows), 21)
        self.assertTrue(any(row["remainder_toman"] > 0 for row in rows[1:]))
        previous = rows[0]
        for row in rows[1:]:
            with self.subTest(budget=row["budget_toman"]):
                self.assertGreaterEqual(row["principal_sats"], 500)
                self.assertGreaterEqual(row["principal_sats"], previous["principal_sats"])
                self.assertGreaterEqual(row["total_toman"], previous["total_toman"])
                self.assertLessEqual(row["total_toman"], row["budget_toman"])
                self.assertEqual(row["remainder_toman"], row["budget_toman"] - row["total_toman"])
                next_principal = row["principal_sats"] + 1
                next_subtotal = next_principal + 156 + 150
                next_operator = int((Decimal(next_subtotal) * Decimal("0.15")).to_integral_value(rounding=ROUND_CEILING))
                next_total = int((Decimal(next_subtotal + next_operator) * Decimal("100.5")).to_integral_value(rounding=ROUND_CEILING))
                self.assertGreater(next_total, row["budget_toman"])
                previous = row

    def test_quote_rejects_nonpositive_nonfinite_and_out_of_bound_rates(self):
        from decimal import Decimal
        from pricing import quote_table

        shared_invalid = (0, -1, True, False, None, 1.0, "", "bad", " 1",
                          "1 ", "١", "NaN", "sNaN", "Infinity", "-Infinity",
                          Decimal("NaN"), Decimal("Infinity"), "1e-10000000",
                          Decimal("1e-10000000"), "1.0000000000000000001")
        for index in range(3):
            maximum = "10000.0001" if index == 2 else "1000000000000000.01"
            for value in (*shared_invalid, maximum):
                values = ["10000000000", "100000", "1"]
                values[index] = value
                with self.subTest(index=index, value=value):
                    with self.assertRaises(ValueError):
                        quote_table(*values)

    def test_quote_ignores_callers_decimal_precision_rounding_and_traps(self):
        from decimal import Decimal, Inexact, ROUND_DOWN, Rounded, localcontext
        from pricing import btc_to_sats, quote_table, sats_to_btc

        expected = quote_table("12345678901.12345678", "98765.4321", "1.23456789")
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(btc_to_sats("1.12345678"), 112345678)
            self.assertEqual(sats_to_btc(112345678), "1.12345678")
            actual = quote_table(Decimal("12345678901.12345678"), Decimal("98765.4321"), Decimal("1.23456789"))
        self.assertEqual(actual, expected)

    def test_budgets_start_strictly_above_initial_total_including_exact_multiple(self):
        from pricing import quote_table

        quote = quote_table("17214963246", "1", "0.001")
        self.assertEqual(quote["rows"][0]["total_toman"], 100000)
        self.assertEqual(quote["rows"][1]["budget_toman"], 200000)
        self.assertEqual(quote["rows"][-1]["budget_toman"], 2000000)

    def test_first_quote_survives_when_no_budget_row_is_affordable(self):
        from pricing import quote_table

        quote = quote_table(1000000000000000, 1000000000000000, 10000)
        self.assertEqual(len(quote["rows"]), 1)
        self.assertEqual(quote["rows"][0]["principal_sats"], 500)
        self.assertGreater(quote["rows"][0]["total_toman"], 2000000)

    def test_fractional_rates_match_exact_rational_ceiling_oracle_and_json(self):
        from decimal import Decimal
        from fractions import Fraction
        import json
        from pricing import btc_to_sats, quote_table

        def ceiling(value):
            return -(-value.numerator // value.denominator)

        for btc, usdt, fee in (
            ("12345678901.12345678", "98765.4321", "1.23456789"),
            ("999999999999999.999999999999999999", "0.000000000000000001", "9999.999999999999999999"),
            ("0.00000001", "0.00000001", "0.000000000000000001"),
        ):
            with self.subTest(btc=btc, usdt=usdt, fee=fee):
                quote = quote_table(Decimal(btc), Decimal(usdt), Decimal(fee))
                self.assertEqual(json.loads(json.dumps(quote, allow_nan=False)), quote)
                adjusted_btc = Fraction(btc) * Fraction(1005, 1000)
                adjusted_usdt = Fraction(usdt) * Fraction(1005, 1000)
                sat_price = adjusted_btc / 100000000
                network = ceiling(Fraction(fee) * 141)
                printing = ceiling(Fraction(15, 100) * adjusted_usdt / sat_price)
                self.assertEqual(quote["costs"], {"network_sats": network, "print_sats": printing})
                self.assertEqual(Fraction(quote["rates"]["btc_toman"]), adjusted_btc)
                self.assertEqual(Fraction(quote["rates"]["usdt_toman"]), adjusted_usdt)
                for row in quote["rows"]:
                    principal = row["principal_sats"]
                    self.assertEqual(btc_to_sats(row["btc"]), principal)
                    subtotal = principal + network + printing
                    operator = ceiling(Fraction(15, 100) * subtotal)
                    self.assertEqual(row["operator_sats"], operator)
                    self.assertEqual(row["total_sats"], subtotal + operator)
                    self.assertEqual(row["total_toman"], ceiling((subtotal + operator) * sat_price))
                    self.assertEqual(row["total_rial"], row["total_toman"] * 10)


if __name__ == "__main__":
    unittest.main()
