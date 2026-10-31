# NFC website activation evidence

Activated on ssh rpi, app-only. No Caddy changes, database imports, wallet writes,
secret rotation or source-tree overwrite. The existing nullable unique nfc_uid
column was already present; no schema migration was run. Only SELECT(nfc_uid)
was added to bitcoin4fun_web_ro. Readback verified serial/address/nfc_uid SELECT,
private metadata denial and no INSERT/UPDATE/DELETE/TRUNCATE privilege.

Running image:

sha256:a3fef0942eaa9ddd55d2af4c9f87141a7f24cb2a9a78313c60f7dad6eef79358

Native ARM image built without network from previous immutable application base.
All 36 manifest files matched the actual running container. Health passed.
TAG_LOOKUP_ENABLED=1; audit 1048576 bytes/file, five backups; existing mounts
preserved. Host still does not enforce declared memory cgroup limit.

External browser: /security and questionnaire present; unassigned test UID
00000000 returned 404, immediate repeat returned 429 with Retry-After 20.
No test mapping was inserted. Provider transport/schema passed from the actual
container against the published public BIP84 test-vector address, not a user's
wallet. This does not prove a particular physical tag is mapped or scanned.

Local website suite before activation: 241 tests, OK, five credential-gated
checks skipped. Separate disposable PostgreSQL integration had passed earlier.
Branding tests now expect the user-approved organization repository URL.

Rollback/evidence directory on rpi:

/home/saeb/bitcoin4fun/releases/nfc-20261031/

Restore compose.override.before.yaml to the app's compose.override.yaml and
recreate only web with --no-deps --no-build. The old image is retained. If
reverting the newly added permission, revoke SELECT(nfc_uid) only; keep schema,
wallet records and all persistent state. Do not restart/reload shared Caddy.

Source is a tested uncommitted working-tree candidate; no main-repository push
or commit is implied. Customer visual redesign is an independent active task.
