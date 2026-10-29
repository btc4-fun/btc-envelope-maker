# Deployment

## Runtime contract

This service serves Persian educational pages and reads a single public wallet
record by serial. It never creates wallets, signs transactions, stores recovery
words or calls a blockchain API. A mempool link is an explicit external
navigation, not an automatically loaded resource. Self-contained assets do not
mean a live PostgreSQL-backed lookup works without reaching this server.

- Python 3.13; hash-locked dependencies in requirements.txt.
- Multi-architecture pinned official Python image index; native arm64 on RPi.
- Gunicorn: two workers, two threads, bounded timeout, no access log containing
  serials by default. Health endpoint /healthz checks HTTP process health only,
  not database readiness.
- Public JSON: /api/wallets/SERIAL, local QR: /api/wallets/SERIAL/qr.svg.
- Direct pages: /s/SERIAL and /SERIAL, including go.bitcoin4.fun/SERIAL.
- No authentication, serial listing or write endpoint. Serial-address mapping
  is deliberately public; serials are not passwords or proof of ownership.

## Database

Use a dedicated application database. The initial target is d_bitcoin4fun in
nextcloud-aio-database on the existing external nextcloud-aio Docker network.
Never change Nextcloud's databases, roles, container, image or volumes.

The owner/importer uses the existing btc_db.py contract:

```sql
CREATE TABLE IF NOT EXISTS public.wallets (
    serial TEXT PRIMARY KEY,
    address TEXT NOT NULL UNIQUE,
    jalali_datetime TEXT,
    created_utc TIMESTAMPTZ
);
```

The separate bitcoin4fun_web_ro login must be NOSUPERUSER, NOCREATEDB,
NOCREATEROLE, NOINHERIT. Grant CONNECT to the application database, USAGE on
public and SELECT (serial, address) on public.wallets only. Set its
 default_transaction_read_only to on as defense in depth. Do not reuse the
owner/importer's password in the web container. No automated migration runs at
web startup. Create/grant the table separately with the owner/admin.

Import only public ledger.csv records from a separate online computer using
the database owner's credentials through a private network/SSH tunnel. Never
expose PostgreSQL on a public host port or copy the private PDF to the server.
Pass credentials through a private environment or secret file, not arguments
or committed config. The original generator's URL masking has known gaps.

```sh
python btc_envelope_maker/btc_db.py import /private/path/ledger.csv
```

Set BTC_DB_URL privately for the importer; it is not part of the website's
configuration. Do not import preview addresses. The initial database may be
empty; not-found is an expected result until genuine public inventory is
imported. Do not seed fabricated live wallets or fund test fixtures.

## Docker Compose

Copy .env.example to ignored .env and fill nonsecret settings. Put the web
role's password alone in secrets/db_password, directory mode 0700 and file mode
0600. The file must be readable by container UID/GID 1000. Do not put the owner
credentials in this directory. The password is a readonly bind mount, never a
build argument or image layer. Keep .env mode 0600 as well.

```sh
cd bitcoin4funsite
docker compose config -q
docker compose build web
docker compose up -d --no-deps web
docker compose ps
curl --fail http://127.0.0.1:18084/healthz
```

The app binds host loopback only, runs unprivileged with a readonly rootfs,
dropped capabilities, no-new-privileges, bounded logs/resources and a small
non-executable tmpfs. The Docker context is an allowlist and cannot contain
.env, secrets, generator outputs or databases. Existing external network access
is needed for the database; it is not an Internet-wide isolation guarantee.

Rebuild when source changes: source copied into the image is not updated by
merely copying files or restarting. Use a unique image tag/revision and compare
app/template/static hashes inside the running container before claiming the
new revision is live. Compose restart policy is not automatic Git deployment.

## RPi installation and shared Caddy

Application root: /home/saeb/bitcoin4fun/bitcoin4funsite.
Application port: 127.0.0.1:18084. Database network: nextcloud-aio.
Shared Caddy uses host networking and the existing bind-mounted file:

/home/saeb/caddy/Caddyfile

Existing certificate lineage already covers bitcoin4.fun and go.bitcoin4.fun:

/etc/letsencrypt/live/bitcoin4.fun/

Before activation, recheck certificate SAN/validity and hostname DNS. Do not
issue a replacement just because this application is new. Preserve all shared
Caddy routes, mounts, global settings and unrelated certificates.

User approval is required for the exact domain blocks and reload. The approved
operation for this task is only adding the two requested hostnames, with a
backup and validated rollback; no Caddy restart or recreation. Prove the direct
application responds and matches this repository before editing the proxy.
Back up exact live Caddyfile bytes and preserve its bind-mounted inode during
write; validate inside the live container against its real certificate mounts,
then reload and read back the active host matchers/upstream from the admin API.
If validation or application/old-route smoke tests fail, restore backup bytes,
validate and reload the previous config. Never replace all shared routes with
the example below.

```caddyfile
https://bitcoin4.fun, https://go.bitcoin4.fun {
    tls /etc/letsencrypt/live/bitcoin4.fun/fullchain.pem /etc/letsencrypt/live/bitcoin4.fun/privkey.pem
    encode zstd gzip
    reverse_proxy 127.0.0.1:18084
}
```

See INSTALLATION.md for verified installation evidence and current host
limitations, including unsupported kernel memory limits and the offline wheel
build used on this RPi.

## Verification and rollback

Run the unit/UI suite, database privilege negative tests and live browser tests.
Inspect browser request URLs to prove all automatic assets/API/QR/font loads
are same-origin. Verify a synthetic public fixture only within a temporary
rolled-back/cleaned test; never publish fake funding or claim a real serial was
verified when the database is empty. Test unknown and malformed serials,
checksum-invalid database records, unavailable DB and correct HTTP headers.
Scan publication staging with a real secret scanner plus a filename/known-secret
and 12/24-word mnemonic guard before committing.

For an app-only rollback, select the previously verified immutable image tag
and recreate only web, preserving credentials and database. For first install,
stop/remove only the new application's web container and restore the Caddy
backup if reverting publication. Never run down -v, prune, reset the shared
proxy or delete existing database volumes. Do not delete the original wallet
artifacts or local operator files.
