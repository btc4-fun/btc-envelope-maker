# Deployment

## Runtime contract

This service serves Persian educational pages and reads a single public wallet
record by serial. It never creates wallets, signs transactions, stores recovery
words or fetches a user's blockchain activity. Server-side market prices and
economy fee suggestions use fixed sources; a mempool address link is an explicit external
navigation, not an automatically loaded resource. Self-contained assets do not
mean a live PostgreSQL-backed lookup works without reaching this server.

- Python 3.13; hash-locked dependencies in requirements.txt.
- Multi-architecture pinned official Python image index; native arm64 on RPi.
- Gunicorn: two workers, two threads, bounded timeout, no access log containing
  serials by default. Health endpoint /healthz checks HTTP process health only,
  not database readiness.
- Public JSON: /api/wallets/SERIAL, local QR: /api/wallets/SERIAL/qr.svg.
- Direct pages: /s/SERIAL and /SERIAL, including go.btc4.fun/SERIAL.
- No wallet authentication, serial listing or wallet write endpoint. Serial-address mapping
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
    created_utc TIMESTAMPTZ,
    contact_type TEXT,
    contact_value TEXT,
    notes TEXT
);
```

The separate bitcoin4fun_web_ro login must be NOSUPERUSER, NOCREATEDB,
NOCREATEROLE, NOINHERIT. Grant CONNECT to the application database, USAGE on
public and SELECT (serial, address) on public.wallets only. Set its
 default_transaction_read_only to on as defense in depth. Do not reuse the
owner/importer's password in the web container. No automated migration runs at
web startup. Create/grant the table separately with the owner/admin.

The three nullable metadata fields are private operator records, not public
wallet data. Examples of contact_type include email, phone, telegram and
whatsapp; no contact values are inferred or populated automatically. Newly added
fields are NULL in existing rows; any already-present compatible metadata and
all existing ledger values remain unchanged. The web role must
remain SELECT(serial,address) only: never grant table-level SELECT now that the
table can contain personal contact information. Public API, QR, CSV ledger and
ordinary list output must not include these fields. Export contact data only
through a separately authorized private process, never Git or public fixtures.

For existing installations run the explicit owner-side migrate-contact command
in btc_db.py after checking its help. The reusable PostgreSQL routine uses a
two-second lock timeout and ten-second statement timeout; SQLite uses its
existing ten-second busy timeout. Fresh tables include the fields; normal
web startup does not migrate tables. The completed one-time live PostgreSQL
operation added nullable text columns, with no table rebuild/default population, a
two-second lock timeout and five-second statement timeout. A repeated migration
and a separate connection's schema readback passed. Actual web-role reads of
each contact field were denied; a marked synthetic metadata record was cleaned
after checking that public JSON still exposes only serial/address/explorer_url.

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

Create secrets/market.env with SWAPWALLET_API_TOKEN, mode 0600, and
secrets/contact.env with CONTACT_SECRET (random signing key),
BTC_CONTACT_NTFY_TOKEN (dedicated topic-only publisher), and
CONTACT_STATE_FILE=/var/lib/btc4fun/contact.sqlite3. These are runtime envfiles,
not Docker build inputs. Never print docker compose config or docker inspect
environment values to logs; use config -q and key-presence checks.

Create state/ with mode 0700 owned by runtime UID/GID 1000 before starting. This
is the sole writable persistent application mount; it contains contact token
hashes, keyed client-IP hashes, state and timestamps for cross-worker rate limits
and replay prevention, not submitted names, phone numbers or messages. Preserve
it on app-only rollback. Contact text is sent to the private notification topic;
that service's retention policy applies. No files upload.

Provision a separate regular ntfy user, deny all topics, then allow write-only
for btc4fun; deny anonymous access to that topic. The public form submits only
to this app. JSON notifications POST to the ntfy root URL (not the topic URL),
with a fixed topic and the token held only server-side. Verify anonymous read
and publish denial, publisher read denial and unrelated-topic denial. Do not
copy an administrator token into this application.

On this RPi, public-IP hairpin routing reaches a self-signed endpoint. The
Compose host mapping resolves only ntfy.linxu.ir to Docker's host gateway so
the existing shared TLS proxy is reached; the client still uses the fixed
HTTPS hostname with certificate verification enabled. Gateway-local TLS health
was proven from the exact application container before adding the mapping.
No Caddy configuration, host DNS or system-wide routing change is required.

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

The bounded outbound helper must be copied with the application modules in both
the regular Dockerfile and any offline ARM build recipe. A previous image build
that predates a helper or transport fix is historical evidence, not verification
of the current source. Repeat import/route smoke checks and source-hash parity
after the final image is recreated.

## Serial lookup admission and guide images

Every valid serial inquiry is admitted once per client IP per 15 seconds,
across /lookup?serial=..., /s/SERIAL, /SERIAL and /api/wallets/SERIAL.
Invalid serials and an empty form do not query the wallet database. Admission
is enforced before database access, with HTTP 429 and Retry-After on denial;
state failure returns a sanitized 503 rather than bypassing the limiter.
The same admitted serial's local QR within that 15-second window is a companion
request and does not reset the timer. A different/direct QR uses the same gate.
The server-rendered page is hydrated without a duplicate API inquiry.

The limiter uses the existing CONTACT_SECRET and a separate SQLite file:

    LOOKUP_STATE_FILE=/var/lib/btc4fun/lookup.sqlite3

Keep the existing state directory mounted writable and UID/GID 1000, mode 0700.
Both Gunicorn workers share transactional state; restarting the application
must not remove it. Only HMAC-derived client/serial identifiers and timestamps
are retained, not raw IPs, serials, wallet addresses or contact data. Clients
behind a shared public IP share the interval. This is not a distributed-attack
defense or a replacement for upstream capacity controls. Caddy appends the
connecting client IP; never expose the upstream listener publicly or accept
arbitrary forwarded headers from an untrusted proxy.

Only guide-inner-example.png and guide-outer-example.png are public guide
illustrations. The inner card keeps its original design while all twelve words
and the entire recovery QR are covered. The owner-authorized outer card retains
public address/QR/serial pixels and has a no-deposit caption; do not describe
its public codes as nonfunctional. Both PNGs have no source metadata. User originals
privatekey.png/publickey.png must remain local: Git ignore, forced-index guard,
Docker exclusions, transfer allowlist and Flask static refusal protect them.
Never copy the full static directory without filtering operator originals.

## RPi installation and shared Caddy

Application root: /home/saeb/bitcoin4fun/bitcoin4funsite.
Application port: 127.0.0.1:18084. Database network: nextcloud-aio.
Shared Caddy uses host networking and the existing bind-mounted file:

/home/saeb/caddy/Caddyfile

Current certificate lineage covers btc4.fun and go.btc4.fun:

/etc/letsencrypt/live/btc4.fun/

Before activation, recheck certificate SAN/validity and hostname DNS. Do not
issue a replacement just because this application is new. Preserve all shared
Caddy routes, mounts, global settings and unrelated certificates.

User approval is required for the exact domain blocks and reload. The approved
operation is the two new requested hostnames plus path/query-preserving
permanent redirects from bitcoin4.fun and go.bitcoin4.fun, with backup and
validated rollback; no Caddy restart or recreation. The current routes were
already active when the parallel operator stopped; their bytes were preserved
by the app deployment. Prove the direct
application responds and matches this repository before editing the proxy.
Back up exact live Caddyfile bytes and preserve its bind-mounted inode during
write; validate inside the live container against its real certificate mounts,
then reload and read back the active host matchers/upstream from the admin API.
If validation or application/old-route smoke tests fail, restore backup bytes,
validate and reload the previous config. Never replace all shared routes with
the example below.

```caddyfile
https://btc4.fun, https://go.btc4.fun {
    tls /etc/letsencrypt/live/btc4.fun/fullchain.pem /etc/letsencrypt/live/btc4.fun/privkey.pem
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
