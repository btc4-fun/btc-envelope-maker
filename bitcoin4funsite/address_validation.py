"""Shared, bounded lower-case mainnet P2WPKH address validation."""
from __future__ import annotations

import re

from bech32 import decode

# The generator's two public preview phrases (12/24 words); never inventory.
# m/84'/0'/0'/0/0, independently checked with bip_utils. Add new project
# preview vectors here whenever introducing them; website fixtures remain valid.
PUBLIC_TEST_ADDRESSES = frozenset({
    "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
    "bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6",
})


def valid_inventory_address(value: object) -> bool:
    """Production import/save excludes published project preview wallets."""
    return valid_address(value) and value not in PUBLIC_TEST_ADDRESSES


_ADDRESS = re.compile(r"bc1q[02-9ac-hj-np-z]{38}")


def valid_address(value: object) -> bool:
    """Keep the website/generator contract narrow; reject before decoding."""
    if not isinstance(value, str) or len(value) != 42 or _ADDRESS.fullmatch(value) is None:
        return False
    version, program = decode("bc", value)
    return version == 0 and program is not None and len(program) == 20
