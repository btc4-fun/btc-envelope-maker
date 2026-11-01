# Security policy and known limitations

Never submit recovery words, private keys, confidential PDFs, database passwords
or customer ledgers in public issues. Report vulnerabilities privately to:

09113458375@btc4.fun

## Website boundary

The web service has no wallet-generation or signing code. Its dedicated
PostgreSQL role is granted SELECT on serial and address only. Queries bind the
serial, output addresses must pass mainnet P2WPKH Bech32 checksum validation,
and all QR generation is local. No third-party scripts, analytics, fonts or
automatic external browser requests are used. Only the server retrieves market
prices and economy-fee suggestions with bounded responses/timeouts, no redirects
and a short cache. The exchange token stays in a private envfile outside Git
and the build context; only selected public numeric values reach the browser.
Stale cached quotes are marked and expire; unavailable data is not fabricated.
The serial is public and guessable; knowing
it is not authorization to spend and does not prove payment or ownership.

The public lookup intentionally reveals the associated public Bitcoin address.
Never put buyer names, notes, transaction secrets or recovery material in its
response. PostgreSQL and deployment credentials must remain outside Git and
outside the container image. The readonly database connection is defense in
depth; the database role must also have no write privileges.

Wallet contact_type/contact_value/notes are private nullable operator metadata.
The website account is deliberately denied SELECT on these columns; retain the
column-level grants even when adding schema fields. Public imports/listing and
ledger outputs do not carry contacts. Never infer contacts from a serial,
publish a contact export, or connect the public contact form to wallet records.

Serial inquiries are limited to five admissions in a rolling 60 seconds per client IP, shared by
HTML/API aliases and workers through private transactional SQLite admission.
QR requests for any serial admitted within that window are free and do not
refresh it; an unseen or expired QR consumes an ordinary admission. Repeated
non-QR inquiries count even for the same serial, including not-found results.
The state uses HMAC-derived identifiers, not raw client IPs or serials; keep its
directory private and persistent. Invalid configuration or state errors fail
closed. Shared-IP users share the limit; one can exhaust the group's quota,
and changing IPs can bypass this defense. This permits a burst of five and a
long-run rate of five/minute instead of the former one and four/minute; it is
not equivalent protection. Free QR work is not a total resource-consumption cap.
Legacy state is retained and conservatively holds each existing IP until its
last admission plus 60 seconds. Stop all old workers before a future upgrade;
mixed-version workers and downgrade state compatibility are not supported.
Trust forwarded client addresses only through the existing local/private peer
and last appended Caddy hop; keep the app port bound to loopback.

The inner guide image preserves the original design but replaces all twelve
recovery words and the entire recovery QR with opaque pixels. Partial word/QR
redaction is not sufficient. The explicitly authorized public outer example
retains its actual public address/QR/serial, with a conspicuous no-deposit
caption; it is not the visitor's wallet. Never claim that image is nonfunctional.
Original input filenames privatekey.png/publickey.png remain excluded from Git,
Docker contexts, uploads and static serving. Export metadata-free derivatives;
a text secret scanner cannot establish that a wallet image is safe.

The optional contact form never uploads files and submits only to this server.
Its publisher credential must have write-only permission to the private
notification topic, never administrator or read access. Signed expiring tokens,
durable replay prevention, request-size bounds and cross-worker rate limits
reduce abuse; they are not a guarantee against distributed spam. The server's
small SQLite state must not contain message text or raw client IPs. Submitted
contact content is held by the notification service under its retention policy.
Do not send recovery phrases, keys, passwords or confidential wallet images in
any contact channel. Missing notification configuration must fail closed without
revealing credentials or falsely claiming successful delivery.

## Historical generator security follow-up

Generator implementation, verification and current operating guidance now belong
to https://github.com/btc4-fun/btc-wallet-generator. The sections below preserve
pre-split findings; extraction does not resolve them. Website runtime and tests
no longer import that repository. The website owns a pinned pure validator copy;
see docs/address-validator-provenance.md.

The follow-up adds public-vector tests, including actual PDF text extraction,
pixel QR decoding and independent recovery of the printed address. Admission
tests mock key generation; they do not establish cryptographic correctness.
See SECURITY-FOLLOWUP.md for scope and executable checks.

- Serial suffix width now covers the entire run; duplicate serials fail before
  output. Historical one/two-character suffixes remain unchanged where sufficient.
- CLI output creation uses a restored restrictive umask; files begin at 0600,
  batch directories at 0700. After exclusive directory creation, output errors
  and catchable interruptions remove known partial artifacts, warning explicitly
  when cleanup is incomplete. Unexpected failures are re-raised after cleanup;
  existing output folders are never owned or removed by the failed run.
- Real generation requires --acknowledge-offline even with --allow-online.
  Failed probes are not proof of isolation; the latter skips only advisory probes.
- Preview writes no ledger and never connects to a database. Both project
  public preview addresses are rejected by production CSV import/direct save.
- Shared bounded mainnet P2WPKH checksum validation rejects invalid inventory
  before database access. Connection descriptions omit userinfo/query/fragment;
  driver errors are value-free. Never pass credentials on the command line.
- Generated serial shapes are checked before website admission/database access;
  browser and server use the same grammar, retaining the existing ASCII/64-char
  website envelope and optional prefix, compact time and extended suffixes.

## Remaining generator limitations (not fixed by this follow-up)

- A shared writable output parent still permits directory-replacement/symlink
  races and public/private aliasing. Umask does NOT fix this. Use an output root
  and filesystem controlled exclusively by the offline operator; path-based
  cleanup also assumes that trusted parent. Descriptor-relative exclusive,
  no-follow output handling remains separate work.
- Second-resolution serials are not globally unique: same-second runs across
  roots/machines, clock reuse and prefix reuse can collide. Exclusive directory
  creation prevents overwriting a batch in the same root, not global collisions.
- Filesystem output is not a crash-atomic transaction; power loss, SIGKILL,
  repeated interruptions during rollback or cleanup failures may leave partial
  files. Direct low-level rendering
  outside the CLI private-creation context does not inherit its mode guarantee.
  Process-wide umask assumes the single-threaded CLI.
- Physically disconnect networking and use a trusted offline live environment
  and offline printer. Neither acknowledgement nor probes enforce isolation.
- Generator runtime, optional test and PostgreSQL dependencies have complete
  target-specific version/hash locks; see btc_envelope_maker/DEPENDENCIES.md.
  The verified target is CPython 3.13/Linux x86_64, not every platform. Hashes
  establish byte consistency, not publisher authenticity, safe native code or
  entropy quality. OS libraries/interpreter remain outside the Python locks.
- Public-vector exclusions cover this project's two preview vectors, not every
  publicly known or compromised wallet. Synthetic website persistence fixtures
  remain separate from production inventory imports.

Use only dedicated offline printers and encrypted/ephemeral storage. Deleting
files is not guaranteed secure erasure on SSD/flash, backups or printer storage.
The person who generated a paper wallet could have retained its words: transfer
all funds to a new wallet whose recovery words only you created and control.
Never type recovery words into this website or any general web form.

The website does not certify that an address is funded. Verify network, address,
transaction and confirmations independently; pending transactions can be
replaced, dropped or delayed indefinitely. No audit guarantees absence of bugs
or safety for storing significant funds.
