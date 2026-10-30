# Generator and lookup security follow-up

## Disposition and regression evidence

1. Generator coverage: the internal official BIP84 self-test already existed;
   no standalone generator CI job existed. Added real-library tests plus actual
   12/24-word PDF output in paired/separate layouts. Poppler extracts printed
   words/address, libzbar decodes rasterized QR, and independent PBKDF2/BIP32/
   secp256k1/Bech32 recovery matches the printed address. Characterization was
   green initially; scratch mutations of QR payload and derivation index failed.
   Code: btc_envelope_maker/tests/test_generator_crypto.py.
2. Serial wrap: reproduced at 1297/1300, corrected with full-run width and
   pre-output uniqueness. Boundaries 36/37/1296/1297/1300 pass. Duplicate and
   wallet-validation failures leave no print/ledger files. Same-second collisions
   across independent roots remain explicitly demonstrated/documented.
   Code: serial_width, to_b36, make_wallets and main in the generator.
3. URL privacy: reproduced credential/query and error-message leaks; corrected
   safe-component descriptions, malformed-URL rejection and value-free driver/
   cleanup/importer CLI errors. Credentials in process arguments are still unsafe.
   Code: btc_db.py; tests/test_database_security.py.
4. Address validation: reproduced checksum-invalid CSV/direct-save admission;
   shared bounded lowercase mainnet witness-v0 20-byte validation now runs before
   connection or writes. Tests cover type/length/alphabet/checksum/network/version/
   witness-length and zero database side effects for rejected batches.
   Code: bitcoin4funsite/address_validation.py; btc_db.py read_ledger/save_rows.
5. Creation permissions: reproduced permissive initial modes and ignored failures;
   CLI creates directories/files restrictively and restores umask on failure.
   Actual PDF descriptors observed as 0600 before writing. Handled chmod/write/
   layout failures remove known artifacts, warning on incomplete cleanup.
   Hostile-parent rename/symlink/alias races remain OPEN, not solved by umask.
6. Offline assurance: reproduced admission without explicit confirmation;
   --acknowledge-offline now required before non-preview work, including with
   --allow-online. All flag/probe combinations exercised before mocked keygen.
   Probes/acknowledgement do not prove or enforce isolation.
7. Preview: reproduced preview ledger output and import acceptance; no preview
   ledger or database access now. Production CSV/direct save reject both actual
   project preview addresses. Website fixtures use their own isolated test path.
8. Short lookup routes: reproduced /admin and /login reaching admission; generated
   serial grammar now gates every alias before limiter/database construction.
   Browser/native/server share that grammar. Legacy, compact and wider serials
   remain accepted within the pre-existing ASCII/64-character website envelope.
   Persistent 15-second admission and companion QR behavior remain tested.

## Executable gates

Install site dependencies using its hash-locked requirements. For generator tests:

    python -m pip install -r btc_envelope_maker/requirements-runtime.txt -r btc_envelope_maker/requirements-test.txt

Install native poppler-utils and libzbar0. Set TMPDIR to a private scratch
location, then run from repository root:

    python -B -m pytest -p no:cacheprovider --basetemp "$TMPDIR/generator-tests" btc_envelope_maker/tests -q
    python -B -m unittest discover -s bitcoin4funsite/tests -v
    python bitcoin4funsite/tests/check_publication_guard.py

The generator job is included in .github/workflows/verify.yml and fails rather
than skipping missing PDF/QR dependencies. The website image explicitly copies
and allowlists the shared address validator. No generator/signing code is added
to that image. requirements-runtime.txt adds bech32 without replacing an
operator's existing requirements.txt changes. Preserve the repository directory
structure for standalone btc_db.py imports.

Parent local verification before independent review: 60 generator/database
security tests passed; 183 website tests passed with two credential-gated skips.
The two PostgreSQL permission tests separately passed against a disposable local
PostgreSQL 18 container with synthetic credentials/rows. Both rows and container
were removed and absence verified. These are not production ACL/migration proofs.

Official source checks fetched the BIP84 document and Trezor BIP39 vectors;
confirmed the fixed BIP84 address and zero-entropy 128/256-bit phrase vectors.
Sources:

https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki
https://github.com/trezor/python-mnemonic/blob/master/vectors.json

## Remaining boundaries

Read SECURITY.md. Hostile writable parents, crash atomicity, globally unique
serial issuance, dependency authenticity and true network isolation are not
certified. No real wallet was generated, inspected or funded for these tests.
No real config/database/recovery output/original wallet images were opened or
uploaded. Historical live-migration notes remain historical, not new evidence.
The website's two accepted URL aliases are unchanged; no shared proxy reload
or database migration is required by this release. Publication/review/deployment
status must be verified against the exact final commit, not inferred from this
pre-release test summary.
