# Repository ownership and current workspace

- Website/backend/offline wallet generator: btc4-fun/btc-envelope-maker,
  /home/saeb/PycharmProjects/btc_envelope_maker.
- Customer Android app (display name requested: btc4fun):
  btc4-fun/btc-tag-checker, /home/saeb/PycharmProjects/btc_tag_checker.
- Seller Android app: btc4-fun/btc-tag-mapper,
  /home/saeb/PycharmProjects/btc_nfc_seller, owned by the parallel seller task.

Do not include app signing keys, captured CSVs, generated wallets, runtime state,
local SDK configuration or build output in Git. The old android-customer copy
and its workflow were moved intact to the non-Git archive below; all 283 file
hashes were verified after the move. The independently built customer repository
is authoritative. This archive is retained, not deleted:

/home/saeb/PycharmProjects/btc-workspace-archive/customer-before-split/

The website local main and remote main have diverged: local payment commit
8dadc4f and remote source-link commit 06995ac both descend from the earlier
baseline. Preserve both; use a release worktree and a non-forced integration,
not reset/rebase/stash over ongoing work. User has now explicitly requested
commit/push/deploy of the completed task-file scope.

Seller working tree currently has ongoing workflow/build changes and scanner
regression documentation. Do not stage or overwrite those while its task owns
them. Customer rename/plain-language task owns its independent working tree.

Audience: ordinary inexperienced readers. Prefer short everyday Persian;
explain unavoidable technical terms immediately. Keep seed secrecy, stranger
purchase risks, pending-vs-confirmed balances, and legal rights intact. Security
questionnaire is a caution checklist, never a fabricated loss probability.
