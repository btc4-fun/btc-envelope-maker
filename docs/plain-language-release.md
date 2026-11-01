# Plain-language customer release

This is the historical plain-language release checkpoint. Later Android
version-one signing/publication work is separate; current ownership and signing
authorization are recorded in workspace-ownership.md. Statements below about
missing signing secrets and the parallel seller task describe this checkpoint,
not the current release preparation.

Website source: 89b954ee0682081770e40724fb686d23bd0c81f3; remote main readback
and GitHub verification successful:
https://github.com/btc4-fun/btc-envelope-maker/actions/runs/41230996869

RPi running image:
sha256:f61daaefb82882da91991517535ec0600a492b4cc91c5b7638b8e5f445f80bc7

All 37 runtime manifest files matched; health and /download,/security passed.
Public HTTPS readback verified simplified questions and real GitHub build link.
Only web was recreated; database, credentials, tag activation settings, state and
shared Caddy were unchanged. Rollback override and old image retained under:
/home/saeb/bitcoin4fun/releases/plain-89b954e/

Customer source: 6d7f631fd810e2d0354e9348f2ce079d3e424fbd; name btc4fun,
version 0.1.2/code 3, package unchanged. Workflow and downloaded APK verified:
https://github.com/btc4-fun/btc-tag-checker/actions/runs/41231230751

Downloaded debug APK SHA-256:
9d53ffdb4f1a070b9d794a0320409c30121a39442c31f395cb90b4f8ee985f13

Local tests: website 243 run, five integration tests skipped; customer Python16,
JUnit20, lint clean. UI emulator evidence is separate from physical NFC testing.
The app bundles reviewed simplified public content snapshot46f0083fb527; no
live prices frozen into offline content. Debug-only signing remains explicit;
user has not supplied stable release secrets. Workflow artifacts require GitHub
login and expire; the website does not advertise a nonexistent public release.

Main repository merge preserved both the prior local payment commit and the
remote organization-link commit, with no force push. Unrelated generator
requirements edit and local operator handoff remain outside release. Original
customer directory/workflow archived intact outside Git, not deleted.

Seller repository remains owned by parallel task: its workflow/build and scanner
changes are still dirty. Its last published workflow passed at8528d9a; those
unpublished changes were not staged, modified or represented as released here.
