# NFC mobile work: approved scope and implementation checkpoints

## Requested scope

- Separate Android customer and seller apps.
- Customer scans a tag; backend returns Bitcoin balance and transaction history.
- New backend inquiry limit: one request per twenty seconds per client IP on
  tag-serial inquiries only; preserve existing website serial lookup quota.
- Seller records tag identifier and public address offline, exports dated CSV,
  and later imports mappings without replacing already assigned mappings.
- Assess hashing wallet serials and tag identifiers.
- Request diagnostics include IP and headers with configurable rotating
  retention; omit cookie, token and security-bearing header values.

## Findings from current code

`btc_envelope_maker/btc_db.py:165` creates `serial TEXT PRIMARY KEY` and a unique
public address. Existing imports require a serial, and conflict handling refuses
changing a serial's address. This is the printed/generated wallet serial, not an
unused tag field. Replacing it with a tag UID would break printed lookup URLs.
No NFC mapping field/table or Android Gradle project currently exists.

`bitcoin4funsite/app.py:234` returns serial, public address and an explorer URL;
it does not fetch balance/history. `lookup_limit.py` implements five admissions
per client IP in a rolling sixty-second window with persistent cross-worker
state. The new mobile gate must be scoped deliberately rather than reusing that
policy and claiming a twenty-second interval.

## Security assessment

Unkeyed SHA-256 can hide plaintext from casual database viewing, but does not
make a predictable serial or readable tag secret. It prevents neither cloning
nor replay. If clients send a hash accepted as the identifier, that hash itself
can be replayed. Hashing cannot prove a physical tag was read. Existing printed
serials should stay compatible; do not migrate them solely for cosmetic secrecy.

A server-keyed HMAC of canonical raw UID bytes is an optional database-only
pseudonymization measure; the key must stay off the mobile apps and outside the
database. It needs an explicit key rotation/backfill policy. Offline seller CSV
may retain the raw UID for later trusted import; this is not end-to-end secrecy.
No scheme here proves the recovery phrase has never been copied.

## Approved first implementation slice

Preserve the existing wallet serial. Add a separate nullable unique NFC field,
populated by an explicit owner-side
import. Match an existing wallet by its validated public address, fill only an
unassigned binding, accept identical replay idempotently and reject conflicting
reassignments atomically. Do not insert invented wallets or modify production
schema automatically. Test with disposable SQLite/PostgreSQL fixtures first.

Customer API: independently persistent per-IP twenty-second admission on tag
lookup only, bounded upstream calls and pagination, confirmed and unconfirmed
amounts kept distinct, time/source reported, unavailable is never zero balance.
Provider and history pagination are still to be chosen.

Seller: NFC read only, public address entry/scan, explicit confirmation, private
local persistence and dated export. No recovery phrase/private key handling,
no tag write/lock, no online seller token required for the requested offline flow.

Approved diagnostics: bounded rotating JSON-lines files with timestamp, method,
path, response status, latency and IP; header names can be retained, but redact
Authorization, Cookie, tokens and other secret-bearing values. Escape controls,
bound header lengths, and configure retention. Literal complete-header logging
would retain credentials and contradict existing privacy statements.

## Active implementation checkpoint

The user confirmed the additional field, tag-inquiry-only limit and configurable
rotating deletion with security/cookie redaction. Local TDD work has started on
explicit migration/CSV import and independent admission/audit components. No NFC
production migration or release is authorized by the earlier payment deployment.

Working wire format: NFC UID is uppercase contiguous hexadecimal, representing
4, 7 or 10 bytes in Android Tag.getId() order. CSV fields are uid, address,
captured_at. Preserve leading zero bytes; reject malformed text rather than
silently repairing it. These engineering choices will be shared by both apps.
Raw UID storage is the initial implementation choice; hashing was discussed,
not requested as a migration. Neither raw nor hashed UID authenticates a tag.

Implemented locally: explicit SQLite/PostgreSQL NFC migration/import, persistent
per-IP gate, rotating audit, and GET `/api/tags/<uid>` with optional lowercase
64-hex `after_txid`. Existing printed serial lookup remains unchanged. Audit
failure is fail-closed before wallet access; 102 audit records mark admission
start and a second record reports final status. Invalid arguments return 400,
unknown tags 404, quota 429 with Retry-After, unavailable dependencies 503.

The route uses the Blockstream Esplora adapter: confirmed balance, signed pending
balance delta, and up to 25 confirmed transactions per page. Pending transactions
are not individually listed. Full pages provide a continuation candidate, not
proof of more history. Reads are explicitly non-atomic, request-start timestamped,
and two sequential provider calls each have a four-second/256-KiB limit. No
upstream errors become fabricated zero balances. Public address is disclosed to
this provider when a customer requests activity; no recovery data is involved.

Route/provider integration has been exercised with explicit fixture transport,
not live funded wallets. Migration/import tests ran against disposable SQLite
and PostgreSQL. Existing deployment role still needs a separately approved
column-level SELECT(nfc_uid) grant and explicit owner migration before activation;
never grant whole-table SELECT or run migration at website startup. Runtime
packaging now includes both tag_access.py and chain_activity.py.

Audit configuration: TAG_AUDIT_DIR, TAG_AUDIT_MAX_BYTES (8192..104857600),
TAG_AUDIT_BACKUP_COUNT (0..100). Defaults are a private tag-audit directory in
the existing state mount, 1 MiB per file and five backups. Rotation is size-based,
not idle time expiry; reducing retention takes effect on the next record. Client
IP is retained, header values are allowlisted/redacted, raw query/body/UID are
not logged by the route. State uses TAG_LOOKUP_STATE_FILE and CONTACT_SECRET.

Android implementations, physical NFC evidence, production privacy wording,
full image-build verification and independent review remain pending. Do not
describe this local backend candidate as a working mobile system. Payment
deployment is a separate completed release; NFC changes remain uncommitted and
undeployed.

## Review closure and additional requested work

The independent backend review identified an activation/privacy gap and a
missing restricted-role integration gate. The route now requires explicit
TAG_LOOKUP_ENABLED=1 before any audit/quota/database/provider action. Default-off
side-effect refusal is regression-tested. Real disposable PostgreSQL tests now
exercise the actual route/SQL under SELECT(serial,address,nfc_uid), show denial
without the added column grant, preserve private-column/write/schema denial
with readonly transactions disabled, and retain printed-serial/QR behavior.
The parent reran all three integration tests successfully and verified cleanup.

The new /security page and local-only questionnaire are implemented and visually
checked at a mobile width. Scores count caution topics, not invented loss
probabilities or permission to invest. Terms now disclose conditional tag
provider access and plaintext-IP rotating audit retention. These local changes
have not been published. The previous paragraph's pending privacy/review gates
are closed at source level; packaging/release and physical-device gates remain.

The user clarified “Google flow” means GitHub workflow: use GitHub Actions for
Android build artifacts. Seller app is owned by a separate task/repository.
Customer app work is active in android-customer, with offline public content,
manual online updates and release signing requiring private credentials. No
release key has been created or supplied by this task, and no hosted run is yet
claimed. Re-read the private todo file after completing the current gates.
