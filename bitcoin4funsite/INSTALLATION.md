# Verified installation status

## Current payment release — 2026-10-31

This section supersedes the image/version statements in the historical sections
below. The app-only payment release is active and healthy on the RPi:

    sha256:109a3fd29b1a61939f5f692b2ec892a211cefc35f12e57eb8468b61e8977a644

The previous running immutable image was used as the native ARM base after all
unchanged runtime modules and locked requirements matched local source. Only
eleven changed public template/static files were copied in a network-disabled
build. All 32 runtime source/assets in the release manifest matched the running
container after activation. The manifest SHA-256 is:

    f32d0d0ab25740a01a554ed2d812ab2b676af37b9c0197b70dfa00b23803a995

Private operational evidence and the exact prior Compose override are retained:

    /home/saeb/bitcoin4fun/releases/payment-20261031T144135Z/

The existing override now pins the new immutable image; the adjacent source
tree was not overwritten and is not the authoritative running source. Rollback:
restore `compose.override.before.yaml` from that directory to the application
root's `compose.override.yaml`, then run `docker compose up -d --no-deps
--no-build web` and verify health/public routes. The prior image is retained:

    sha256:9fb9ec9cb46ed5a8e7dd42c0f608a5914f0ab075a7ce0bdc5d5fb2dd674d21c8

Verification: 194 local tests, no failures, two credential-gated database tests
skipped. The publication guard's positive/negative controls passed. Real HTTPS
browser checks passed on home, guide, terms and costs on both public hostnames:
one merged warning per page, no full payment panel on home, no horizontal
overflow at 390px, and no automatic cross-origin resources. Card/Sheba clipboard
contents and image switching passed on the public main hostname. Direct health,
page and SVG routes passed; name/account ownership is not bank-verified.

Shared Caddy and base Compose bytes were unchanged; mounts and both persistent
SQLite file identities were preserved. No production SQL, migration, wallet
import, contact submission or credential modification was performed. Current
database ACLs were not re-audited. The host still cannot enforce the declared
Docker memory limit. No automatic Git deployment or Git push was performed.

## Historical installation evidence

The site was built and activated on the explicitly requested RPi host. Both
public HTTPS hostnames returned the application, and browser inspection proved
same-origin font, CSS, JavaScript, API and QR requests with no automatic
third-party requests or CSP errors. Mobile viewport testing at 360px showed no
horizontal overflow.

- Public site: https://btc4.fun
- Serial route: https://go.btc4.fun/SERIAL
- Application root: /home/saeb/bitcoin4fun/bitcoin4funsite
- Existing database: d_bitcoin4fun, table public.wallets.
- Dedicated web role: bitcoin4fun_web_ro, SELECT(serial,address) only.
- Bind address: 127.0.0.1:18084; shared Caddy forwards the two named hosts.
- Caddy backup: /home/saeb/caddy/bitcoin4fun-preflight/Caddyfile.before.
- Current certificate and active host matchers cover both new names. Old-domain
  redirects preserve serial paths and query strings. These routes were already
  active when the parallel operator stopped; the app deployment preserved them.
- Native architecture: linux/arm64. Nonroot, readonly rootfs and password mount,
  dropped capabilities, no-new-privileges and bounded logs verified at runtime.

A temporary record marked TEST-DO-NOT-FUND used the published BIP84 test address
to exercise successful public JSON, QR loading and both serial-page hostnames.
It was removed and the public API returned 404 afterward. No genuine wallet
records were imported. The database is ready for later public-ledger imports.
No private PDF, recovery words or existing local database was uploaded.

## Subsequent calculator baseline and new guide release

The previous accepted custom-calculator commit was
cf3151bab9bc2704433bc9eda72891050605e538, deployed as the ARM64 image below.
Its 151 default tests plus two separately credentialed database checks passed;
the two independent math/privacy reviews passed and main CI succeeded.
Earlier images and test totals later in this file are historical checkpoints,
not the current guide/rate-limit release.

sha256:20a898614d9d724a141017af1d682021be205bc682d4e71d134900e8a7811803

The guide release adds shared plain-language inner/outer examples on home,
lookup and guide, a camera/stranger/forged-address warning, and clarified
initial-deposit terms. The original inner design is retained with all recovery
words and its QR covered; the explicitly authorized outer design retains public
deposit/lookup information and warns not to fund the example. Source input
filenames remain excluded from Git, builds, transfer and static serving.
The pre-existing /s/SERIAL and /SERIAL handlers are exercised as equivalent
public-only routes; no shared-Caddy change is required.

Serial admission is enforced per client IP every 15 seconds using shared
persisted SQLite state. Same-result QR requests within the interval do not
extend the timer. Error responses expose Retry-After, not state or credentials.
The default factory and real route integration are covered separately from
tests that inject a limiter. See DEPLOYMENT.md for paths and boundaries.

The guide candidate was built natively with offline locked wheels, activated
app-only, and read back healthy. Its image is:

sha256:e759b6ff1c382397c220a97ad92f2226d2b5459c893abea19e33c63f8277cf56

The parent default and TMPDIR-unset runs each discovered 175 tests: 173 passed
and two credential-gated tests skipped. Those two real database permission
tests passed separately. Both actual serial URLs displayed the public-vector
fixture and local QR, without a duplicate initial API request. A second lookup
was rejected, and a lookup after 15 seconds succeeded. The exact synthetic row
was removed; public API 404 was read back. No genuine wallet rows were examined.
Home, guide, lookup and terms were inspected at 360px: safe images loaded on
all three requested pages, no page overflow, no automatic third-party request
and no captured script error. The normal Dockerfile build also confirmed both
original wallet images are absent. The shared Caddy configuration was unchanged.

## Market and converter preview verification (historical)

The native preview was activated before extended tests at the user's request.
Public /api/market returned a fresh quote; /costs rendered nineteen actual quote
rows in a real browser, beginning with 500 principal satoshis. /satoshi converted
one satoshi exactly in both directions. Six public pages on each new hostname
were checked at 360px: twelve page results, zero horizontal overflow and zero
automatic third-party resource requests. The only public-serial fixture used a
published BIP84 test address, was deleted afterward, and API 404 was read back.

The running preview's seventeen Python/template/CSS/JS/font file hashes matched
its transferred manifest. The preview image is:

sha256:95acf5c59989718a1e92255378861d883cd294645115cd6ab6f627222770e0ba

The current operator rollback snapshot is private on the RPi:

/home/saeb/bitcoin4fun/btc4fun-v2-resume-backup

A fresh database privilege test found broader table-level SELECT than the
documented two-column boundary. That dedicated web role alone was reduced to
SELECT(serial,address); denied UPDATE and denied created_utc reads were then
verified with the real role. No real wallet rows were inspected or changed.

## Contact follow-up verification

The native-form contact image was activated and reported healthy (subsequently
superseded by the transport-hardened image below):

sha256:ff5e807538a54b477ece9c9fa105cd37e7d807f49ed05b6d28e98db2aa40eefd

The native browser form was submitted with scripting disabled, without a
referrer override, and redirected to the success view. The exact harmless
synthetic message was read back once from the private topic; notification ID:

HSNf57smf5PM

The temporary read-only verification identity and its token file were removed
after the readback. The application publisher can write only to btc4fun; its
topic reads, other-topic writes and anonymous topic reads were denied. The
contact page keeps same-origin referrer metadata so native Chromium form POSTs
retain an Origin header; external navigation still receives no referrer. Other
pages retain no-referrer. The shared Caddy file was unchanged by these releases.

That revision's suite ran 100 tests successfully with one credential-gated
database test skipped in the default run; that database test passed separately
against the real column-limited role and cleaned its public fixture. These are
execution results, not a guarantee of no vulnerabilities.

## Transport-hardened final revision

Two reproduced review findings were corrected: a socket idle timeout did not
bound a continuously trickling response, and a failed refresh could cross the
cached quote's maximum lifetime. A fixed local subprocess now enforces the
whole-request deadline and is killed/reaped on timeout. Request credentials
travel through stdin, not argv or inherited environment. Cache eligibility is
checked after the refresh completes; contact's identical transport path shares
the fix while retaining at-most-once admission for uncertain delivery.

The current native ARM64 image is:

sha256:5171fcdbf2533cf3b75fdbff131294a5024cafb32f6e047d75a98308e9cf81c7

The parent reran 108 tests: no failures/errors, one credential-gated test skipped;
the actual database privilege test passed separately. Real loopback tests cover
trickling content-length/chunked responses and headers, response-size caps,
redirect refusal, closed sockets and reaped child processes. Public market
rendering remained successful after deployment.

The browser's final contact attempt correctly hit the persistent client rate
limit after prior E2E submissions. No rate-limit records were cleared. A labelled
in-container request with a synthetic client address then exercised the final
production factory and real notification transport; its exact synthetic message
was read back once, and the temporary reader was removed. Notification ID:

UhwENeinZ20g

The earlier browser no-JavaScript proof and this final-container transport proof
are separate evidence, not a claim that the rate-limited browser attempt sent.

## Environmental limitations

The first online image build could reach PyPI but could not resolve
files.pythonhosted.org. Rather than modifying host DNS/routing or restarting
Docker, the exact arm64 wheels whose SHA-256 hashes are in requirements.txt were
downloaded on the controller and transferred. The native image was built with
network disabled, with the same pinned Python base and locked dependencies.
The normal Dockerfile remains portable for hosts with working package access.
Application/template/static hashes were compared inside the running container.

The RPi kernel reported that Docker memory-limit support is unavailable; the
Compose memory limit is declared but is NOT enforced on this host. No kernel or
host-wide setting was changed. The application still has bounded worker count,
request/database timeouts, PID limit and log rotation. Check cgroup support
before relying on the memory cap for hostile traffic.

Several unrelated Caddy certificates were already expired before this task.
They were not renewed or changed. All previous host matchers were preserved,
and the previously working Matrix route was checked after reload. This task is
not an audit or repair of the other hosted applications.

A first activation attempt was rolled back because an on-host request to the
public IP encountered a self-signed hairpin endpoint. The unchanged candidate
then passed hostname-verified local-SNI tests and activation; independent
external HTTPS and browser checks succeeded afterward. No TLS verification was
disabled for successful acceptance tests, and Caddy was never restarted or
recreated.

## Publication boundary

Only allowlisted source, tests, public assets, licenses and sanitized examples
are committed. Local todo/config.toml, databases, generated PDFs/ledgers,
virtual environments and runtime credentials are ignored. Gitleaks and a staged
path/known-credential guard are used before publication. The separate original
offline generator has unresolved security review findings recorded in
../SECURITY.md; deployment of this read-only website does not fix them.

The repository includes a verification workflow. Restart persistence is
configured; automatic deployment of future Git commits is not configured.
