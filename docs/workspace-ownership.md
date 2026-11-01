# Repository ownership and current workspace

- Website/backend/offline wallet generator: btc4-fun/btc-envelope-maker,
  /home/saeb/PycharmProjects/btc_envelope_maker.
- Customer Android app (display name: btc4fun):
  btc4-fun/btc-tag-checker, /home/saeb/PycharmProjects/btc_tag_checker.
- Seller Android app: btc4-fun/btc-tag-mapper,
  /home/saeb/PycharmProjects/btc_nfc_seller.

Do not include app signing keys, captured CSVs, generated wallets, runtime state,
local SDK configuration or build output in Git. The old android-customer copy
and its workflow were moved intact to the non-Git archive below; all 283 file
hashes were verified after the move. The independently built customer repository
is authoritative. This archive is retained, not deleted:

/home/saeb/PycharmProjects/btc-workspace-archive/customer-before-split/

The earlier website divergence was resolved without rewriting history. Fresh
remote reads found local and remote main equal at 6de0399 before the Android
version-one release work. The running website remains the plain-language image
recorded in plain-language-release.md; Android publication does not deploy it.

The user explicitly transferred the seller's existing workflow/build/scanner
changes into the version-one release scope. Review and test them before staging;
operator handoffs and unrelated generator requirements remain outside that scope.
Both Android repositories are authorized for documentation, release workflows,
commits, version-one tags and pushes. Shared proxy, production database and
website deployment are not part of this release request.

The user explicitly authorized a new shared Android signing identity, replacing
the earlier request to reuse the SMS project's key. Signing material and its
private backup are outside all repositories; four repository signing secrets
were provisioned in each Android repository. Public certificate SHA-256:

7c4ccefc998b2407b22c2a7a3bc97e9b5f9baca3089886a5e71dcfef85b0fa3b

Metadata presence is not proof of signing; verify the published APK certificate.
Never uninstall an installed app to bypass a signing mismatch without permission.

Audience: ordinary inexperienced readers. Prefer short everyday Persian;
explain unavoidable technical terms immediately. Keep seed secrecy, stranger
purchase risks, pending-vs-confirmed balances, and legal rights intact. Security
questionnaire is a caution checklist, never a fabricated loss probability.
