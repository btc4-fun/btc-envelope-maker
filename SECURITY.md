# Security policy and known limitations

Never submit recovery words, private keys, confidential PDFs, database passwords
or customer ledgers in public issues. Report vulnerabilities privately to:

09113458375@btc4.fun

## Website boundary

The web service has no wallet-generation or signing code. Its dedicated
PostgreSQL role is granted SELECT on serial and address only. Queries bind the
serial, output addresses must pass mainnet P2WPKH Bech32 checksum validation,
and all QR generation is local. No third-party scripts, analytics, fonts or
automatic mempool requests are used. The serial is public and guessable; knowing
it is not authorization to spend and does not prove payment or ownership.

The public lookup intentionally reveals the associated public Bitcoin address.
Never put buyer names, notes, transaction secrets or recovery material in its
response. PostgreSQL and deployment credentials must remain outside Git and
outside the container image. The readonly database connection is defense in
depth; the database role must also have no write privileges.

## Existing offline generator: unresolved review findings

Website publication does NOT fix or certify the offline generator. Its initial
review identified these issues, still pending unless a later change explicitly
closes them with tests:

- A shared writable output parent permits directory-replacement/symlink races,
  redirecting secret PDFs or aliasing private output onto public filenames.
- Permission-hardening failures are ignored; file permissions are restricted
  only after PDF and ledger output. Use a private trusted filesystem and parent.
- Failed TCP probes to three destinations do not prove a machine is offline.
  Physically disconnect and use a clean offline environment; do not rely on the
  check as network isolation. Do not use --allow-online with real keys.
- Batch serial suffixes wrap above 1,296 wallets. Keep batches below that
  capacity until dynamic suffix sizing and uniqueness checks are implemented.
- Preview ledgers have no intrinsic preview marker. Never fund a preview/test
  address or import sample records as real inventory.
- Database URL query-password redaction and imported-address checksum
  validation need hardening. Never put credentials on the command line or
  share raw configuration/logs. Validate public addresses independently.
- The generator's original requirements are lower bounds without artifact
  hashes. Its self-test checks derivation correctness, not package authenticity.

Use only dedicated offline printers and encrypted/ephemeral storage. Deleting
files is not guaranteed secure erasure on SSD/flash, backups or printer storage.
The person who generated a paper wallet could have retained its words: transfer
all funds to a new wallet whose recovery words only you created and control.
Never type recovery words into this website or any general web form.

The website does not certify that an address is funded. Verify network, address,
transaction and confirmations independently; pending transactions can be
replaced, dropped or delayed indefinitely. No audit guarantees absence of bugs
or safety for storing significant funds.
