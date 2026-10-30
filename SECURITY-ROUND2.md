# Security round 2: acceptance and release contract

This record closes the four local remediation reports against the final source
reviewed before publication. It does not claim production deployment by itself.
Operational image/commit/CI and rollback evidence is recorded separately by the
release operator after activation.

## Changes

- Restore generator-directory independence: resolve optional database URL before
  importing its module. Share one bounded, dependency-free MIT-attributed BIP173
  validator; retain lowercase mainnet witness-v0/20-byte acceptance and both
  project preview exclusions. The website image receives this helper only.
- Clean known partial output on unexpected errors and catchable interruption
  only after exclusive folder creation. Preserve original exceptions through
  cleanup and broken diagnostic streams; restore umask and never remove a
  previous run's folder. Correct missing-dependency recovery guidance to refer
  to offline hash locks instead of unpinned installation.
- Admit five inquiries per rolling60 seconds per canonical IP, atomically across
  workers and restarts. Preserve HMAC-only state and fail-closed behavior.
  QR companions for all admitted serials are free until their own admission
  expires, without renewal. Other QR requests consume ordinary admission.
- Lock the full generator runtime and separate optional tests/PostgreSQL inputs
  to exact versions and hashes without upgrading packages or including the
  operator-owned legacy requirements.txt. See DEPENDENCIES.md in the generator.

## Executed local acceptance

- Full generator suite:113 passed in a fresh, offline-wheelhouse-installed test
  environment; independently rerun113 passed. Real public-vector derivation,
  PDF text and pixel-QR recovery are separate from guarded random-generation
  admission and synthetic error injection.
- Full website suite:190 discovered,188 passed and2 explicit database-credential
  skips. Those2 tests separately passed against disposable local PostgreSQL18;
  fixture rows and containers were removed and absence verified.
- Actual synchronized SIGINT processes, both layouts, prior-folder preservation,
  permission/ledger/rollback failures and umask covered. Additional independent
  actual-closed-stderr matrix:16 passed, and16 failures against old product bytes.
- Standalone generator-only copy from a different working directory reached the
  pre-entropy guard. Standalone SQLite import required no website/third-party
  packages. No random spendable wallets were created.
- Validator official vectors, deterministic differential checks and corrupted
  controls passed. Independent bip_utils comparison accepted4096 deterministic
  programs and rejected19344 one-symbol mutations; this is not entropy testing.
- Quota independent review:78 tests plus900 dense oracle comparisons, actual
 10000-IP capacity, worker/restart sharing and failure-before-wallet-access.
- Verified34 selected wheels against exact PyPI release metadata and SHA256.
  Fresh offline installs contained26 runtime,32 runtime+test and28 runtime+DB
  distributions. Tampered/missing coincurve controls rejected installation with
  zero installed packages. Verified platform only: CPython3.13.5, Debian13,
  Linux x86_64, glibc2.41. Other platforms require separate acceptance.
- Real Chromium JS/no-JS:five successful inquiries, sixth429/Retry-After60,
  Persian wait display, prior QR at capacity, native form, both SSR aliases
  without duplicate JSON fetches, same-origin resources, expiry without deleting
  state. Browser/server ran with external routing disabled.
- Actual local amd64 website image:28 runtime files matched source;11 layers
  inspected with no forbidden originals, generator/DB module, bip_utils or
  coincurve. Real Gunicorn health and synthetic route checks passed. This build
  reused a cached locked dependency layer, not a fresh offline site installation.
- Final public-source Gitleaks scan:zero findings. Publication guard:85 allowlisted
  snapshot files,zero violations, plus positive/negative controls. The snapshot
  included the preserved local legacy requirement edit for review; that edit is
  excluded from the release commit. Text scans do not certify image privacy.
- Independent source review initially found two low-severity defects in recovery
  guidance and exception reporting; both were reproduced, minimally corrected,
  and independently closed on final hashes. No unresolved blocking finding.

## Activation and rollback

Build from the repository root, retaining the Dockerfile-specific allowlist:

    docker build -f bitcoin4funsite/Dockerfile -t bitcoin4fun:release .

An ARM deployment needs a native image, not the tested amd64 image. If package
access is unavailable, use target-compatible verified wheels and hash-required
network-disabled installation in a separate public-only staging context. Copy
only the canonical validator from the generator directory; never transfer real
config, original wallet images, output, recovery material or wallet databases.

Preserve existing state, credentials, network/port bindings and shared proxy.
Before activation, record the immutable previous image and exact nonsecret
Compose override. Recheck them immediately before changing the web service.
Stop all old web workers before starting the new image; no rolling/mixed-version
operation. The legacy state table remains intact; new admission creates an
additive bounded table. Existing legacy clients conservatively wait until their
last admission plus60 seconds. Do not delete state or rotate the key to upgrade.

For failure rollback, stop new workers, retain their quota state and wait a full
60-second horizon with no web workers admitting requests before starting the
recorded old image/override. This avoids treating a downgrade as if the old
version understood new history. Do not reset or delete state, touch wallet data,
restart the shared proxy, or prune images/volumes. Verify health, immutable image,
runtime file hashes and public educational/invalid-serial routes after activation.
Use synthetic success/QR fixtures only in isolated verification, not live inventory.

## Remaining limits

The new quota is intentionally more permissive:burst5 instead of1 and sustained
5/minute instead of4/minute. Shared-IP peers can exhaust the same quota, and free
QR work is not a total resource cap. See site DEPLOYMENT.md for exact semantics.

Trusted output parents remain required. Power loss/SIGKILL, hostile rename/symlink
races, secure erasure and globally unique same-second serials are not solved.
Unavailable stderr cannot guarantee warning delivery after incomplete cleanup.
Hash locking proves byte consistency, not publisher authenticity or harmless
native code. Interpreter/OS libraries are outside Python locks. The site retains
an already locked bech32 package used by tests; removing that nonblocking extra
is deferred rather than expanding this remediation into a dependency refactor.

No production ACL or wallet migration assurance is inferred from local tests.
The personal Hermes skill and private detailed evidence stay outside this public
repository; no operational secrets or machine-specific notification routes are
part of the release.
