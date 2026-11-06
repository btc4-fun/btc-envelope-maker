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

A successful response contains **only** `address`, `serial`, and `lookup_url` — no
query string, no other keys. The released Android app (1.1.5) rejects any other key
count, so this endpoint stays frozen at three keys. Illustrative offline fixture;
this does not claim the address is registered on the live site, and this public
test wallet must not be funded:

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
| 400 | `{"error":"invalid_address"}` | Invalid address |
| 400 | `{"error":"invalid_lookup_request"}` | Query string is not exactly the single `balance=1` |
| 404 | `{"error":"not_found"}` | Valid address, no registered mapping |
| 429 | `{"error":"rate_limited","retry_after":43}` | Shared quota exhausted; example delay |
| 503 | `{"error":"unavailable"}` | Admission/DB failure or invalid stored mapping |
| 503 | `{"error":"balance_unavailable", ...}` | Optional balance requested but upstream failed |

### Optional balance and public metadata

Without a query string the body is frozen at the three keys above. Exactly one
query, `?balance=1`, is admitted; repeats, other values, or any other key are
rejected with `400 {"error":"invalid_lookup_request"}` before quota or DB access.
The check runs in `before_request` against the raw query string, and a raw path
containing control bytes or percent-escapes is `400 invalid_address`.

`?balance=1` adds the same `balance` object `/api/wallets` returns (see
`docs/serial-balance.fa.md`) and, when the wallet has any, an optional `public`
object:

```json
{
  "address": "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
  "serial": "TEST-DO-NOT-FUND-0587k45300",
  "lookup_url": "https://btc4.fun/s/TEST-DO-NOT-FUND-0587k45300",
  "balance": {"address": "...", "confirmed_sats": 500, "pending_delta_sats": -50,
              "source": "https://blockstream.info/api", "fetched_at": "1970-01-01T00:16:40+00:00"},
  "public": {
    "notes": "یادداشت عمومی آزمایشی",
    "site": {"key": "btc4.fun", "url": "https://btc4.fun/"},
    "image_url": "https://btc4.fun/static/logo.png",
    "links": {"instagram": "https://instagram.com/btc4fun", "telegram": "https://t.me/btc4fun"}
  }
}
```

Shape rules: `notes` is always present in `public` and may be `null`; `site`,
`image_url`, and `links` appear only when set. `site_key` and `site_url` are
published together or not at all, and the `site.url` host must match `site_key`
(equal, or starting with `site_key + "."`). Values are seller-supplied text, not
proof of authenticity or a balance. They are never read from the private contact
columns, and a value that fails sanitization (control/format/bidi characters,
non-https, host outside the allowlist, userinfo or port) is dropped rather than
shown.

`links` is an optional flat map of short seller-chosen labels to absolute https
addresses — social accounts and contact routes. Rules: at most 20 entries; each
key is 1–32 characters of `a-z 0-9 . _ -`, lowercased, starting with a letter or
digit; each value is an absolute https URL with no control, bidi, or format
character. A single invalid entry is dropped on its own — one bad link never hides
the rest of the card. `links` is stored in the `public_links` TEXT column as JSON
and is never derived from `contact_type`, `contact_value`, or `notes`. A client
that reads this payload must treat `links` as optional so payloads written before
the column existed still parse.

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
SELECT serial, address, public_notes, site_key, site_url, image_url, public_links
FROM public.wallets WHERE address = %s LIMIT 1
```

The serial lookup uses the same seven columns; the tag (`nfc_uid`) lookup keeps its
original two-column read and never returns public metadata. Column selection is an
internal allowlist, not request text. Simultaneous `by_tag=True` and
`by_address=True` are rejected before credential access. Existing read-only
connection settings and timeouts are kept.

The five added columns are nullable and only ever carry values the seller chose to
publish; they are never populated from `contact_type`, `contact_value`, or `notes`.
`public_notes`, `site_key`, `site_url`, and `image_url` are TEXT; `public_links` is
TEXT holding a JSON object (`{"instagram":"https://…"}`) so the same schema works on
SQLite and PostgreSQL. The read role needs `SELECT` on the five public columns only
— never on the private contact columns — and this module never issues `GRANT`
itself. Creating the columns is a separate, explicit step:

```sh
python btc_db.py migrate-public --db "sqlite:///wallets.db"
```

It is idempotent and takes a bounded lock (SQLite `BEGIN IMMEDIATE`; PostgreSQL
`lock_timeout`/`statement_timeout` with an access-exclusive lock). Applying it in
production is the owner's deployment step, not this API's.

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

## Customer-only address details contract (design-only; not implemented here)

This section is the contract for a future private customer projection. It adds no
route, database field, grant, migration, or operational behavior to this release.
The public endpoint above remains public and must never be used as customer proof.

### Identity and ownership

- **Customer identity** is a server-authenticated, non-guessable customer principal
  (for example, a provider subject mapped to an internal immutable `customer_id`).
  An address, serial, NFC UID, contact value, request header, or caller-supplied
  customer identifier is not an identity proof.
- **Wallet ownership binding** is a durable server-side relation between that
  `customer_id` and the wallet record, established only by an authorized binding
  workflow with an auditable proof and explicit revocation state. Public lookup
  results and possession of an identifier never create or imply this relation.
- The private service must fail closed when identity, binding, revocation, or
  policy state is missing, ambiguous, expired, or unavailable. It must not fall
  back to the public address/serial/UID lookup.

### Private endpoint and projection

Proposed endpoint: `GET /api/customer/addresses/<address>/details` (private,
customer-authenticated). It is a contract placeholder, not an implementation
instruction for this change. The handler must authorize the authenticated
principal against the server-side ownership binding before reading private fields.
Its allowlisted response projection is only the approved customer-owned fields,
for example:

```json
{
  "address": "<canonical public address>",
  "customer_id": "<opaque internal id>",
  "details": {"label": "<customer-visible label>"},
  "binding": {"status": "active", "expires_at": "<UTC timestamp>"}
}
```

The exact private `details` fields require product approval; do not expose
`contact_type`, `contact_value`, notes, recovery material, credentials, raw
provider claims, or unrelated customers. The response must use an explicit
allowlist and `Cache-Control: no-store`; public `address`, `serial`, or `nfc_uid`
may be correlation inputs only after authentication and ownership authorization.

### Errors and lifecycle

| HTTP status | JSON body | Contract meaning |
| --- | --- | --- |
| 401 | `{"error":"unauthorized"}` | Missing, invalid, or expired customer authentication |
| 403 | `{"error":"forbidden"}` | Authenticated customer has no active binding to this wallet |
| 404 | `{"error":"not_found"}` | Authorized binding exists but the address/detail record is absent; do not use 404 to reveal an unbound wallet |
| 429 | `{"error":"rate_limited","retry_after":<seconds>}` | Private quota exhausted; include `Retry-After`; quota identity is the authenticated customer plus abuse controls |
| 503 | `{"error":"unavailable"}` | Identity/binding store, policy, audit, or dependency unavailable; fail closed without private data |

For anti-enumeration, deployments may intentionally normalize an unbound or
absent wallet to one externally documented response, but must not vary body,
private fields, or timing based on guessed address/serial/UID. Error bodies never
contain ownership, contact, notes, SQL, provider claims, or credentials.

Bindings require an explicit expiry policy, immediate revocation support, and
server-side checks on every request; expiry and revocation invalidate access
without deleting audit history. Audit records must capture the authenticated
principal, wallet/binding identifier, action, outcome, reason class, request
correlation id, and UTC timestamp, while excluding address-linked private values,
secrets, tokens, and raw request bodies. Audit failure is fail-closed for the
private operation. Retention and deletion must follow the applicable policy.

### Synthetic contract tests (future implementation gate)

Before enabling the endpoint, tests must use only disposable synthetic identities,
wallets, bindings, and private values and must cover: valid own binding and
allowlisted projection; missing/expired/revoked identity (401); another customer
or absent binding (403/normalized 404); missing detail (404); quota (429 plus
`Retry-After`); dependency/audit outage (503); expiry at the exact boundary;
revocation immediately before access; one audit event per admitted attempt; no
private values in responses/logs/errors; and no cache. A fail-closed regression
must prove that public address, serial, or NFC UID alone cannot authorize the
private projection, including after the public lookup succeeds.

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
