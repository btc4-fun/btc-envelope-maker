# Public address → printed serial API

## Purpose and scope

`GET /api/addresses/<address>` resolves an existing public Bitcoin address to its
registered printed serial. This is an ordinary public reverse lookup, enabled
alongside serial lookup; it does not depend on the optional tag-activity feature.
It does not register a wallet, infer a serial from an address, update NFC metadata,
write any wallet records, or contact a blockchain/market provider. It adds no HTML
address route. The existing serial page remains the destination for an NFC URL.

The address/serial association is public information. Requests disclose the public
address to the website (and may appear in its normal infrastructure access logs),
not to an external blockchain provider. Never send private keys, seeds, mnemonics,
contact details, or private QR payloads to this endpoint.

## Request

```text
GET https://btc4.fun/api/addresses/<address>
```

- Supply exactly the canonical lowercase mainnet P2WPKH address accepted by the
  existing `valid_address`: 42 characters, witness version zero, 20-byte program,
  valid BIP173 checksum.
- No trimming, case conversion, checksum repair, network conversion, or URL/BIP21
  extraction is performed. Invalid input is rejected before admission or DB access.
- No query parameters are supported, including URL overrides, QR flags, or cursors.
  Any nonempty query string is rejected.
- There is no authentication or private-data capability added by this API.

## Responses

A successful response contains **only** `address`, `serial`, and `lookup_url`.
Illustrative offline fixture; this does not claim the address is registered on the
live site, and this public test wallet must not be funded:

```json
{
  "address": "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
  "serial": "TEST-DO-NOT-FUND-0587k45300",
  "lookup_url": "https://btc4.fun/s/TEST-DO-NOT-FUND-0587k45300"
}
```

The returned address must exactly match the requested address, and the stored
serial must match the website's existing serial grammar. Otherwise the response
is `503`, not a guessed or repaired mapping. The URL always uses the literal
`https://btc4.fun/s/` origin and the registered serial; request `Host`, forwarded
headers, and query parameters cannot replace it.

| HTTP status | JSON body | Meaning |
| --- | --- | --- |
| 200 | Object above | Registered public mapping found |
| 400 | `{"error":"invalid_address"}` | Invalid address or unsupported query string |
| 404 | `{"error":"not_found"}` | Valid address, no registered mapping |
| 429 | `{"error":"rate_limited","retry_after":43}` | Shared quota exhausted; example delay |
| 503 | `{"error":"unavailable"}` | Admission/DB failure or invalid stored mapping |

A `429` also has `Retry-After` with the same number of seconds as `retry_after`.
Errors contain no serial, URL, private fields, connection details, or guessed data.
Success and API error responses inherit `Cache-Control: no-store` and
`X-Robots-Tag: noindex, nofollow, noarchive`.

## Shared quota and database boundary

The API uses the existing `app.extensions['lookup_limiter']` instance, including
`LOOKUP_LIMITER` injection, and the same client-IP derivation as serial lookup.
The limit remains **five admissions per IP in the preceding sixty seconds**,
shared with serial API and HTML lookups. Address admission uses
`address_` + the validated address and `qr=False`; repeated reverse lookups are
never free QR companions. Existing serial QR behavior is unchanged. Valid misses
and DB failures consume an admission; malformed input does not. Unavailable quota
state fails closed before any wallet DB credential read or connection.

The production DB path extends `database_lookup(..., by_address=True)`, selecting
only existing public columns with a bound address:

```sql
SELECT serial, address FROM public.wallets WHERE address = %s LIMIT 1
```

Column selection is an internal allowlist (`serial`, `nfc_uid`, `address`), not
request text. Simultaneous `by_tag=True` and `by_address=True` are rejected before
credential access. Existing read-only connection settings and timeouts are kept.
There are no new private-column reads, schema changes, grants, or wallet writes.
The existing public `serial,address` read permissions suffice for this query.

## Android seller flow: offline capture first

1. Keep scanning, validating, and storing the public address locally as the offline
   capture operation. Offline capture must not silently trigger a network request.
2. Offer online serial resolution only as a **separate explicit optional action**.
   Explain that this sends the public address to the website. Never upload a private
   QR or derive/reconstruct wallet secrets.
3. Request this endpoint using the exact validated public address. On success,
   require an exact address match, valid serial, and the canonical URL above.
4. Show the registered serial for comparison with the printed wallet. Require an
   explicit seller confirmation before writing the returned serial website URL as
   an NFC URI record. This API itself performs no NFC write or tag registration.
5. On an offline error, `400`, `404`, `429`, or `503`, retain local capture without
   inventing a serial or substituting an address-based website URL. Respect
   `Retry-After`; do not automatically loop through retries or bulk provisioning.

This change implements only the server lookup contract. Android UI, NFC writing,
and optional online provisioning remain separate client work.

## Offline verification

```sh
.venv/bin/python -m unittest discover -s bitcoin4funsite/tests -p test_address_serial_lookup.py -v
env -u BTC_TEST_OWNER_PASSWORD_FILE -u NFC_TEST_POSTGRES \
  .venv/bin/python -m unittest discover -s bitcoin4funsite/tests -v
```

`ADDRESS_LOOKUP` accepts an injected callable taking the exact public address and
returning `{'address': ..., 'serial': ...}` or `None`. The tests use synthetic
records, a mock PostgreSQL connection/cursor contract harness, and real disposable
SQLite limiter state. They cover validation order, SQL parameterization, public
field projection, fixed-origin URLs, sanitized failures, shared quota in both
request orders, expiry, and unchanged serial QR exemption. They do not access live
DB credentials, query live blockchain services, verify deployed-site behavior,
or establish a real PostgreSQL ACL proof.
