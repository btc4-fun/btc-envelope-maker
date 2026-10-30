# Reproducible generator dependencies

## Scope and files

The tested target is **CPython 3.13.5, Debian 13 Linux x86_64, glibc 2.41**.
These are target-specific wheel locks, not a claim of support for Windows,
macOS, ARM, musl, another Python ABI, or older glibc. A different target needs
its own artifact selection, lock and clean acceptance run. In particular the
selected PyNaCl wheel requires manylinux 2.34. The Python interpreter and OS
libraries are prerequisites, not Python packages covered by these locks.

| File | Contract |
| --- | --- |
| `requirements-runtime.in` | Five direct generator inputs, pinned to the already exercised versions |
| `requirements-runtime.txt` | Complete 26-distribution runtime closure, exact versions and selected-wheel SHA-256 |
| `requirements-test.in` / `.txt` | Optional test tools and independent `bech32` oracle; install alongside runtime |
| `requirements-db.in` / `.txt` | Optional PostgreSQL `psycopg` + binary implementation; install alongside runtime |
| `requirements-artifacts.json` | Exact wheel filenames, HTTPS URLs, digest matches, release metadata URLs/hashes and wheel `Requires-Dist` metadata for all 34 distinct artifacts |

`requirements.txt` is a legacy, operator-owned file. The new installation path
**does not include it** and preserves local additions. Direct runtime needs
were taken from its committed version at
`586c33fa5e36cd1d54786c377bdd5ba59c049692`, not the operator's edited copy.
Every selected version matches the existing generator development environment;
this work makes no package upgrades. Existing installed versions were only
selection constraints: acceptance used newly downloaded wheels and empty venvs,
not the development environment or its cache.

Runtime does not need `pytest`, external `bech32`, or `psycopg`. SQLite uses the
standard library. `ecdsa` and `six` occur in both runtime and test locks because
`bip-utils` itself requires them; the test oracle cannot remove that runtime
edge. Runtime plus tests installs 32 distributions; runtime plus PostgreSQL
installs 28. Do not add database/test tools to an offline generation machine
unless actually needed.

## Acquire approved wheels on an online preparation machine

Use a trusted toolchain separately from target execution. The recorded resolver
and installer was `uv 0.10.6`; Python was `/usr/bin/python3.13`. Resolve no source
builds: all artifacts in this manifest are wheels. Do not silently replace a
missing wheel with an sdist, a newer version, or an unchecked install.

The following stdlib-only acquisition example downloads the exact manifest
artifacts, checks their release-specific PyPI records and verifies both digests.
Run from this directory on the preparation machine, not the isolated generator.
The manifest includes optional artifacts; retain only the required lock's subset
when preparing a runtime-only bundle.

```sh
python3.13 - <<'PY'
import hashlib, json, pathlib, urllib.request
manifest = json.loads(pathlib.Path('requirements-artifacts.json').read_text())
wheelhouse = pathlib.Path('wheelhouse')
wheelhouse.mkdir(exist_ok=True)
for artifact in manifest['artifacts']:
    assert artifact['metadata_url'].startswith('https://pypi.org/pypi/')
    release = json.load(urllib.request.urlopen(artifact['metadata_url'], timeout=60))
    record = next(f for f in release['urls'] if f['filename'] == artifact['filename'])
    assert record['packagetype'] == 'bdist_wheel' and not record['yanked']
    assert record['url'] == artifact['url']
    assert artifact['url'].startswith('https://files.pythonhosted.org/')
    assert record['digests']['sha256'] == artifact['sha256']
    data = urllib.request.urlopen(artifact['url'], timeout=120).read()
    assert hashlib.sha256(data).hexdigest() == artifact['sha256']
    (wheelhouse / artifact['filename']).write_bytes(data)
PY
```

Retain release JSON and acquisition logs for review. Release JSON can change
(e.g. yanking/project metadata), so its recorded hash identifies the retrieved
record, not a promise that a future retrieval is byte-identical. Wheel hashes
must remain identical. Fetching PyPI metadata and wheels over HTTPS and matching
PyPI's digests provides source traceability and byte consistency. It does **not**
independently authenticate the publisher, audit package source/native binaries,
prove reproducible upstream builds, verify a signed provenance attestation, or
rule out a compromised publisher/index/toolchain. The manifest is reviewable
provenance evidence, not an authenticity certificate.

## Offline installation

Transfer the generator source, chosen lock files, verified wheelhouse and trusted
Python/installer through the offline machine's approved transfer process. Use a
fresh environment with no inherited site packages, no developer cache, and
**OS-disabled networking** (physically disconnected host or a properly restricted
network namespace/container). The flags below are defense in depth, not proof
that the OS network is disabled:

```sh
uv --offline --no-config venv --python /usr/bin/python3.13 --no-project .venv-offline
uv --offline --no-config --no-cache pip install \
  --python .venv-offline/bin/python --require-hashes --no-index \
  --find-links ./wheelhouse --only-binary :all: \
  -r requirements-runtime.txt
uv --offline --no-config pip check --python .venv-offline/bin/python
```

For an isolated **test** machine, add `-r requirements-test.txt` to the install
command. For PostgreSQL export add `-r requirements-db.txt` instead (or both only
when needed). Do not seed the venv with developer packages or pip/setuptools.
`uv` runs outside the target venv. Equivalent pip installs must retain hash,
no-index and binary-only enforcement and use a separately trusted installer.

Render/recovery tests additionally require OS `poppler-utils`, ZBar and fonts.
The tested packages were `poppler-utils 25.03.0-5+deb13u4`,
`libzbar0t64 0.23.93-8`, and `fonts-dejavu-core 2.37-8`.
These native dependencies and the interpreter are **not** covered by the wheel
hash lock. In a restricted filesystem, expose read-only native libraries,
`/etc/ld.so.cache`, fonts and `/sbin/ldconfig` (`/sbin -> usr/sbin` on Debian);
otherwise `ctypes.util.find_library('zbar')` can fail even with ZBar installed.
Use private scratch `TMPDIR` and a `pytest --basetemp` beneath it. Never run
acceptance against original configuration, wallet output or private images.

## Regenerating locks without upgrades

The wheelhouse contains exactly one reviewed wheel per selected version/target.
Compilation from this finite local set is deterministic and cannot select a
newer package from PyPI. Run on the tested target using the recorded uv version:

```sh
for group in runtime test db; do
  uv --offline --no-config pip compile "requirements-$group.in" \
    --python /usr/bin/python3.13 --no-index --find-links ./wheelhouse \
    --only-binary :all: --generate-hashes --no-header --no-annotate \
    --output-file "requirements-$group.txt"
done
```

Restore the descriptive comment headers if desired; they are not resolver
input. Test/DB inputs constrain shared versions with the runtime lock. To change
versions or platforms, explicitly review the new full closure/artifact manifest
and rerun fresh isolated installs and negative controls. An ordinary broad
PyPI compile can emit hashes for other platforms and sdists; the final locks
here were compiled against only the verified target wheelhouse.

## Complete runtime dependency graph

Versions are in the runtime lock; this lists every non-leaf edge after evaluating
wheel metadata markers for Python 3.13/Linux with no extras:

```text
bip-utils -> cbor2, coincurve, ecdsa, ed25519-blake2b-fork,
             py-sr25519-bindings, pycryptodome, pynacl,
             pytoniq-core-fork, typing-extensions
cffi -> pycparser
ecdsa -> six
pynacl -> cffi
pytoniq-core-fork -> bitarray, pycryptodomex, pynacl, requests,
                    typing-extensions, x25519
reportlab -> charset-normalizer, pillow
requests -> certifi, charset-normalizer, idna, urllib3
```

Leaves: `arabic-reshaper`, `bitarray`, `cbor2`, `certifi`,
`charset-normalizer`, `coincurve`, `ed25519-blake2b-fork`, `idna`, `pillow`,
`py-sr25519-bindings`, `pycparser`, `pycryptodome`, `pycryptodomex`,
`python-bidi`, `six`, `typing-extensions`, `tzdata`, `urllib3`, `x25519`.
The TON/network-library branch is an existing declared `bip-utils` dependency,
not a new application network feature; retaining the full declared closure is
necessary for a consistent installation. Network isolation remains required.

Release-specific `bip-utils 2.12.3` wheel metadata explicitly requires
`coincurve>=21.0.0` on Python >=3.13 (alongside its broader >=3.12 condition).
The selected `coincurve 21.0.0` CPython 3.13 manylinux x86_64 wheel declares no
Python distribution dependencies. That does not imply absence of native code
or bundled native dependencies. No bespoke replacement crypto was introduced.

## Executed acceptance and limits

Local evidence records empty venvs, exact commands, exit codes, installed
inventories, artifact hashes and source hashes. The installation harness used
`bubblewrap 0.12.0 --unshare-all --clearenv`, read-only OS toolchain and wheels,
only dedicated scratch writes, bounded process/time/memory/file resources, and
no user home, repository or developer venv mounts. A socket connection to a
numeric external address failed with `ENETUNREACH`; the namespace routing table
was empty. All installs used `--offline --no-cache --require-hashes --no-index
--find-links --only-binary :all:`.

* Runtime, runtime+tests and runtime+DB each installed from an empty environment
  and passed `uv pip check` (26, 32 and 28 distributions respectively).
* A disposable copy of the selected `coincurve` wheel had exactly one byte
  changed. Installation failed with **Hash mismatch**; the venv remained empty.
* Removing that wheel from another disposable wheelhouse failed dependency
  resolution, with networking unavailable and no cache fallback; the venv
  remained empty.
* The clean test environment passed the existing five public-vector crypto/
  PDF/recovery tests in an isolated generator-only snapshot: official BIP84
  address/self-test plus real rendering and pixel QR decoding for 12/24 words
  in paired/separate layouts. No random wallet was generated. This proves those
  cases for the recorded snapshot, not all wallet safety or later code changes.

Full application/security-suite closure is a separate gate. Hashes do not make
packages trustworthy, and these results are not a cross-platform guarantee,
upstream source audit, vulnerability scan, or deployment certification.
