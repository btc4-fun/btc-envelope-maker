"""Official BIP173 vectors and independent-package differential oracle."""
import importlib.util
from pathlib import Path

from bech32 import CHARSET, decode, encode

SOURCE = Path(__file__).resolve().parents[1] / 'address_validation.py'
spec = importlib.util.spec_from_file_location('canonical_validator', SOURCE)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_official_vectors_and_narrow_contract():
    # https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki
    assert validator.valid_address('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4')
    rejected = [
        'BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4',  # valid BIP173; not canonical lower case
        'tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7',
        'bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k7grplx',
        'BC1SW50QA3JX3S', 'bc1zw508d6qejxtdg4y5r3zarvaryvg6kdaj',
        'tb1qqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvsesrxh6hy',
        'tc1qw508d6qejxtdg4y5r3zarvary0c5xw7kg3g4ty',
        'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5',
        'BC13W508D6QEJXTDG4Y5R3ZARVARY0C5XW7KN40WF2', 'bc1rw5uspcuh',
        'bc10w508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kw5rljs90',
        'BC1QR508D6QEJXTDG4Y5R3ZARVARYV98GJ9P',
        'tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sL5k7',
        'bc1zw508d6qejxtdg4y5r3zarvaryvqyzf3du',
        'tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3pjxtptv', 'bc1gmk9yu',
        None, [], {}, 42, '', 'bc1q' + 'q' * 1000000,
    ]
    assert all(not validator.valid_address(value) for value in rejected)


def test_differential_synthetic_programs_and_every_single_symbol_mutation():
    # Deterministic witness bytes, not keys or randomly generated wallets.
    addresses = [encode('bc', 0, [(offset + i) % 256 for i in range(20)]) for offset in range(256)]
    for address in addresses:
        version, program = decode('bc', address)
        assert version == 0 and len(program) == 20
        assert validator.valid_address(address)
    for address in (addresses[0], *validator.PUBLIC_TEST_ADDRESSES):
        assert not validator.valid_inventory_address(address) if address in validator.PUBLIC_TEST_ADDRESSES else validator.valid_inventory_address(address)
        for index in range(3, len(address)):
            for symbol in CHARSET:
                if symbol == address[index]:
                    continue
                candidate = address[:index] + symbol + address[index + 1:]
                assert decode('bc', candidate) == (None, None)
                assert not validator.valid_address(candidate)


def test_site_and_database_share_canonical_functions():
    import sys
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from btc_envelope_maker import address_validation as canonical
    from bitcoin4funsite import address_validation as site
    from btc_envelope_maker import btc_db
    assert site.valid_address is canonical.valid_address
    assert btc_db.valid_inventory_address is canonical.valid_inventory_address
