# Verified installation status

The site was built and activated on the explicitly requested RPi host. Both
public HTTPS hostnames returned the application, and browser inspection proved
same-origin font, CSS, JavaScript, API and QR requests with no automatic
third-party requests or CSP errors. Mobile viewport testing at 360px showed no
horizontal overflow.

- Public site: https://bitcoin4.fun
- Serial route: https://go.bitcoin4.fun/SERIAL
- Application root: /home/saeb/bitcoin4fun/bitcoin4funsite
- Existing database: d_bitcoin4fun, table public.wallets.
- Dedicated web role: bitcoin4fun_web_ro, SELECT(serial,address) only.
- Bind address: 127.0.0.1:18084; shared Caddy forwards the two named hosts.
- Caddy backup: /home/saeb/caddy/bitcoin4fun-preflight/Caddyfile.before.
- Existing certificate covers both names; not reissued by this task.
- Native architecture: linux/arm64. Nonroot, readonly rootfs and password mount,
  dropped capabilities, no-new-privileges and bounded logs verified at runtime.

A temporary record marked TEST-DO-NOT-FUND used the published BIP84 test address
to exercise successful public JSON, QR loading and both serial-page hostnames.
It was removed and the public API returned 404 afterward. No genuine wallet
records were imported. The database is ready for later public-ledger imports.
No private PDF, recovery words or existing local database was uploaded.

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
