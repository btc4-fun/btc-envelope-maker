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


class CustomQuoteTests(unittest.TestCase):
    def test_seeded_budget_quotes_match_closed_form_fraction_inverse(self):
        from fractions import Fraction
        import random
        from pricing import MAX_SATOSHIS, quote_for_budget

        rng = random.Random(48023)
        ceiling = lambda x: -(-x.numerator // x.denominator)
        for case in range(160):
            def decimal_rate(maximum, places):
                scale = 10**places
                numerator = rng.randint(1, maximum * scale)
                whole, remainder = divmod(numerator, scale)
                return f"{whole}.{remainder:0{places}d}" if places else str(whole)

            btc = decimal_rate(10**15, rng.choice((0, 8, 18)))
            usdt = decimal_rate(10**8, rng.choice((0, 8, 18)))
            fee = decimal_rate(10000, rng.choice((0, 8, 18)))
            sat_price = Fraction(btc) * Fraction(201, 200) / 100000000
            network = ceiling(Fraction(fee) * 141)
            printing = ceiling(Fraction(3, 20) * Fraction(usdt) * Fraction(201, 200) / sat_price)
            principal = rng.choice((500, rng.randint(500, MAX_SATOSHIS), MAX_SATOSHIS))
            subtotal = principal + network + printing
            budget = ceiling(ceiling(Fraction(23, 20) * subtotal) * sat_price) + rng.choice((-1, 0, 1))
            # Algebraically invert the two integer ceilings, independently of
            # production's binary search: total_sats <= floor(budget/sat_price).
            total_sats_limit = Fraction(budget) // sat_price
            subtotal_limit = 20 * total_sats_limit // 23
            expected_principal = min(MAX_SATOSHIS, subtotal_limit - network - printing)
            with self.subTest(case=case, budget=budget):
                if expected_principal < 500:
                    with self.assertRaisesRegex(ValueError, "insufficient"):
                        quote_for_budget(btc, usdt, fee, budget)
                    continue
                row = quote_for_budget(btc, usdt, fee, budget)
                self.assertEqual(row["principal_sats"], expected_principal)
                actual_subtotal = expected_principal + network + printing
                expected_total = ceiling(ceiling(Fraction(23, 20) * actual_subtotal) * sat_price)
                self.assertEqual(row["total_toman"], expected_total)
                self.assertEqual(row["remainder_toman"], budget - expected_total)

    def test_custom_rows_preserve_the_entire_existing_table_row_contract(self):
        from pricing import quote_for_budget, quote_for_principal, quote_table

        for inputs in (("10000000000", "100000", "1.1"),
                       ("12345678901.12345678", "98765.4321", "1.23456789"),
                       ("0.00000001", "0.00000001", "0.000000000000000001")):
            table = quote_table(*inputs)
            for row in table["rows"]:
                custom = (quote_for_principal(*inputs, row["principal_sats"])
                          if row["budget_toman"] is None
                          else quote_for_budget(*inputs, row["budget_toman"]))
                self.assertEqual({key: custom[key] for key in row}, row)
                for key in ("rates", "assumptions", "costs"):
                    self.assertEqual(custom[key], table[key])

    def test_all_conversion_text_is_bounded_before_decimal_parsing(self):
        from pricing import btc_to_sats, sats_to_btc

        self.assertEqual(btc_to_sats("0" * 63 + "1"), 100000000)
        self.assertEqual(sats_to_btc("0" * 63 + "1"), "0.00000001")
        for convert in (btc_to_sats, sats_to_btc):
            for invalid in ("0" * 64 + "1", "0" * 10000):
                with self.subTest(convert=convert.__name__, length=len(invalid)):
                    with self.assertRaisesRegex(ValueError, "64"):
                        convert(invalid)

    def test_raw_asset_value_uses_unadjusted_btc_without_any_package_fee(self):
        from decimal import Decimal, localcontext
        import pricing

        value = getattr(pricing, "raw_asset_toman", None)
        self.assertTrue(callable(value), "raw_asset_toman must be implemented")
        for raw_btc, principal, expected in (
            ("10000000000", 3000, "300000"),
            ("12345678901.12345678", "3000", "370370.3670337037034"),
            ("10000000000", 0, "0"),
            ("0.000000000000000001", 1, "0.00000000000000000000000001"),
            ("1000000000000000", pricing.MAX_SATOSHIS, "21000000000000000000000"),
        ):
            with self.subTest(raw_btc=raw_btc, principal=principal):
                with localcontext() as context:
                    context.prec = 1
                    context.Emax, context.Emin = 1, -1
                    for signal in context.traps:
                        context.traps[signal] = True
                    self.assertEqual(value(Decimal(raw_btc), principal), expected)
        for principal in (-1, True, False, 1.0, Decimal("1"), "1e3", "0" * 65, pricing.MAX_SATOSHIS + 1):
            with self.subTest(invalid=principal):
                with self.assertRaises(ValueError):
                    value("10000000000", principal)

    def test_budget_rejects_noninteger_or_overlong_input(self):
        from decimal import Decimal
        from pricing import quote_for_budget

        for invalid in (
            -1, True, False, 100000.0, Decimal("100000"), None, "", " 100000",
            "100000 ", "100000\n", "+100000", "-0", "100000.0", "1e5",
            "١٠٠٠٠٠", "１00000", "1_00000", "0" * 59 + "100000", "9" * 10000,
            10**64,
        ):
            with self.subTest(invalid=repr(invalid)[:80]):
                with self.assertRaises(ValueError):
                    quote_for_budget("10000000000", "100000", "1.1", invalid)
        self.assertEqual(
            quote_for_budget("10000000000", "100000", "1.1", "0" * 58 + "100000"),
            quote_for_budget("10000000000", "100000", "1.1", 100000),
        )

    def test_decimal_rates_do_not_normalize_positive_exponents_or_signed_zero(self):
        from decimal import Decimal, localcontext
        from pricing import quote_for_principal

        for index in range(3):
            for invalid in (Decimal("1E+3"), Decimal("-0"), Decimal("sNaN"),
                            "0" * 64 + "1", "1E+3", "1e3", 1.0, True):
                values = ["10000000000", "100000", "1.1"]
                values[index] = invalid
                with self.subTest(index=index, invalid=invalid):
                    with localcontext() as context:
                        for signal in context.traps:
                            context.traps[signal] = True
                        with self.assertRaises(ValueError):
                            quote_for_principal(*values, 3000)

    def test_custom_quotes_ignore_every_caller_decimal_trap_and_exponent_range(self):
        from decimal import Decimal, ROUND_FLOOR, localcontext
        from pricing import quote_for_budget, quote_for_principal

        inputs = ("12345678901.12345678", "98765.4321", "1.23456789")
        principal = quote_for_principal(*inputs, 3000)
        budget = quote_for_budget(*inputs, 50000001)
        with localcontext() as context:
            context.prec = 1
            context.rounding = ROUND_FLOOR
            context.Emax, context.Emin = 1, -1
            context.clamp = 1
            for signal in context.traps:
                context.traps[signal] = True
            self.assertEqual(quote_for_principal(*(Decimal(value) for value in inputs), "3000"), principal)
            self.assertEqual(quote_for_budget(*(Decimal(value) for value in inputs), "50000001"), budget)

    def test_public_synthetic_golden_vectors_match_exact_core(self):
        import json
        import pricing

        fixture_path = Path(__file__).parent / "fixtures" / "quote_calculator.json"
        fixture = json.loads(fixture_path.read_text())
        self.assertEqual(fixture["schema_version"], 1)

        def stringify_integers(value):
            if type(value) is int:
                return str(value)
            if isinstance(value, dict):
                return {key: stringify_integers(item) for key, item in value.items()}
            return value

        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                inputs = case["inputs"]
                function = pricing.quote_for_principal if case["mode"] == "principal" else pricing.quote_for_budget
                if "expected_error" in case:
                    with self.assertRaisesRegex(ValueError, "insufficient.*500"):
                        function(**inputs)
                else:
                    actual = function(**inputs)
                    self.assertEqual(stringify_integers(actual), case["expected"])
                    self.assertEqual(pricing.raw_asset_toman(inputs["btc_toman"], actual["principal_sats"]),
                                     case["raw_asset_toman"])
                    if "next_principal_total_toman" in case:
                        self.assertGreater(int(case["next_principal_total_toman"]), int(inputs["budget_toman"]))

    def test_insufficient_budget_raises_without_a_fictitious_principal(self):
        from pricing import quote_for_budget, quote_for_principal

        for rates in (
            ("10000000000", "100000", "1.1"),
            ("12345678901.12345678", "98765.4321", "1.23456789"),
            ("1000000000000000", "1000000000000000", "10000"),
        ):
            minimum = quote_for_principal(*rates, 500)["total_toman"]
            for budget in (0, minimum - 1):
                with self.subTest(rates=rates, budget=budget):
                    with self.assertRaisesRegex(ValueError, "insufficient.*500"):
                        quote_for_budget(*rates, budget)
            boundary = quote_for_budget(*rates, minimum)
            self.assertEqual(boundary["total_toman"], minimum)
            self.assertEqual(boundary["remainder_toman"], 0)

    def test_budget_inverse_has_no_table_cap_and_proves_maximality(self):
        from fractions import Fraction
        import pricing

        inverse = getattr(pricing, "quote_for_budget", None)
        self.assertTrue(callable(inverse), "quote_for_budget must be implemented")
        for btc, usdt, fee, budget in (
            ("10000000000", "100000", "1.1", 93164),
            ("10000000000", "100000", "1.1", 100000),
            ("10000000000", "100000", "1.1", 50000000),
            ("12345678901.12345678", "98765.4321", "1.23456789", 50000001),
            ("0.000000000000000001", "0.000000000000000001", "0.000000000000000001", 1),
            ("1000000000000000", "1000000000000000", "10000", 10**63),
        ):
            with self.subTest(btc=btc, budget=budget):
                row = inverse(btc, usdt, fee, budget)
                ceiling = lambda x: -(-x.numerator // x.denominator)
                sat_price = Fraction(btc) * Fraction(201, 200) / 100000000
                network = ceiling(Fraction(fee) * 141)
                printing = ceiling(Fraction(3, 20) * Fraction(usdt) * Fraction(201, 200) / sat_price)

                def cost(principal):
                    subtotal = principal + network + printing
                    return ceiling((subtotal + ceiling(Fraction(3, 20) * subtotal)) * sat_price)

                self.assertGreaterEqual(row["principal_sats"], 500)
                self.assertLessEqual(row["principal_sats"], pricing.MAX_SATOSHIS)
                self.assertEqual(row["total_toman"], cost(row["principal_sats"]))
                self.assertLessEqual(row["total_toman"], budget)
                self.assertEqual(row["budget_toman"], budget)
                self.assertEqual(row["remainder_toman"], budget - row["total_toman"])
                if row["principal_sats"] < pricing.MAX_SATOSHIS:
                    self.assertGreater(cost(row["principal_sats"] + 1), budget)
                principal_row = pricing.quote_for_principal(btc, usdt, fee, row["principal_sats"])
                self.assertEqual({**principal_row, "budget_toman": budget,
                                  "remainder_toman": budget - row["total_toman"]}, row)
        self.assertEqual(inverse("10000000000", "100000", "1.1", 93164)["principal_sats"], 500)
        self.assertEqual(inverse("10000000000", "100000", "1.1", 93164)["remainder_toman"], 0)
        self.assertGreater(inverse("10000000000", "100000", "1.1", 100000)["remainder_toman"], 0)

    def test_custom_principal_requires_bounded_unsigned_integer(self):
        from decimal import Decimal
        from pricing import MAX_SATOSHIS, quote_for_principal

        for invalid in (
            0, 499, -1, MAX_SATOSHIS + 1, True, False, 3000.0,
            Decimal("3000"), None, "", " 3000", "3000 ", "3000\n", "+3000",
            "-3000", "3000.0", "3e3", "٣٠٠٠", "３０００", "3_000",
            "0" * 61 + "3000", "9" * 10000,
        ):
            with self.subTest(invalid=repr(invalid)[:80]):
                with self.assertRaises(ValueError):
                    quote_for_principal("10000000000", "100000", "1.1", invalid)
        expected = quote_for_principal("10000000000", "100000", "1.1", 3000)
        self.assertEqual(
            quote_for_principal("10000000000", "100000", "1.1", "0" * 60 + "3000"),
            expected,
        )

    def test_custom_principal_matches_independent_fraction_oracle(self):
        from fractions import Fraction
        import json
        import pricing

        quote_for_principal = getattr(pricing, "quote_for_principal", None)
        self.assertTrue(callable(quote_for_principal), "quote_for_principal must be implemented")
        for btc, usdt, fee, principal in (
            ("10000000000", "100000", "1.1", 3000),
            ("12345678901.12345678", "98765.4321", "1.23456789", 3000),
            ("999999999999999.999999999999999999", "0.000000000000000001", "9999.999999999999999999", 500),
            ("0.000000000000000001", "1000000000000000", "0.000000000000000001", pricing.MAX_SATOSHIS),
        ):
            with self.subTest(btc=btc, principal=principal):
                row = quote_for_principal(btc, usdt, fee, principal)
                ceiling = lambda x: -(-x.numerator // x.denominator)
                sat_price = Fraction(btc) * Fraction(201, 200) / 100000000
                network = ceiling(Fraction(fee) * 141)
                printing = ceiling(Fraction(3, 20) * Fraction(usdt) * Fraction(201, 200) / sat_price)
                operator = ceiling(Fraction(3, 20) * (principal + network + printing))
                total = principal + network + printing + operator
                self.assertEqual({key: row[key] for key in (
                    "principal_sats", "network_sats", "print_sats", "operator_sats", "total_sats",
                    "total_toman", "total_rial", "budget_toman", "remainder_toman",
                )}, {
                    "principal_sats": principal, "network_sats": network,
                    "print_sats": printing, "operator_sats": operator, "total_sats": total,
                    "total_toman": ceiling(total * sat_price),
                    "total_rial": ceiling(total * sat_price) * 10,
                    "budget_toman": None, "remainder_toman": 0,
                })
                self.assertEqual(pricing.btc_to_sats(row["btc"]), principal)
                table = pricing.quote_table(btc, usdt, fee)
                for key in ("rates", "assumptions", "costs"):
                    self.assertEqual(row[key], table[key])
                self.assertEqual(json.loads(json.dumps(row, allow_nan=False)), row)


if __name__ == "__main__":
    unittest.main()
