"""Bounded lower-case mainnet P2WPKH validation, shared with the website.

Checksum functions below are from Pieter Wuille's reference implementation:
https://github.com/sipa/bech32/blob/master/ref/python/segwit_addr.py
Retrieved reference SHA256:
2884ce04a36c8374c4249177cd90e91e545ac73b5c9260307bbeb74ae2e9de0f
BIP173: https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki
Only the checksum is needed: the preflight fixes HRP=bc, version=0 and exactly
32 five-bit program symbols (=20 bytes, no padding). No encoding, signing or
key-generation implementation is included. Bech32m is intentionally rejected.
"""
# Copyright (c) 2017, 2020 Pieter Wuille
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
import re

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_ADDRESS = re.compile(r"bc1q[02-9ac-hj-np-z]{38}")
PUBLIC_TEST_ADDRESSES = frozenset({
    "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
    "bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6",
})


def bech32_polymod(values):
    """Internal function that computes the Bech32 checksum (reference)."""
    generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def bech32_hrp_expand(hrp):
    """Expand the HRP into values for checksum computation (reference)."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def valid_address(value: object) -> bool:
    """Reject noncanonical shape before bounded BIP173 checksum work."""
    if not isinstance(value, str) or len(value) != 42 or _ADDRESS.fullmatch(value) is None:
        return False
    data = [CHARSET.find(x) for x in value[3:]]
    return bech32_polymod(bech32_hrp_expand("bc") + data) == 1


def valid_inventory_address(value: object) -> bool:
    """Exclude the project's two public preview wallets from production."""
    return valid_address(value) and value not in PUBLIC_TEST_ADDRESSES
