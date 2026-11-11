# Lookup public display — local implementation verification

Date: 2026-11-11. State: **implementation verified locally; awaiting independent parent review**. No commit/push/deploy/mirror publication by implementation worker.

## Scope and result

The page now transfers sanitized public metadata as JSON-escaped initial data, parses it defensively and reuses the existing safe DOM renderer. Ordinary form submission is native so it does not depend on the intentionally metadata-free ordinary API. Explicit balance enhancement remains unchanged in contract. Endpoint-based attachment fixes the root serial alias. CSP images remain restricted to self and the existing three HTTPS project hosts. The repeated lookup tutorial was replaced with a guide button and concise warnings; the guide itself is unchanged.

Modified tracked paths:

- README.md
- bitcoin4funsite/app.py
- bitcoin4funsite/static/site.js
- bitcoin4funsite/templates/lookup.html
- bitcoin4funsite/tests/test_public_metadata_api.py
- bitcoin4funsite/tests/test_serial_validation.py
- bitcoin4funsite/tests/test_ui_contract.py

The implementation notes were appended to the specification; its frozen approval block and in-progress status are unchanged. The three preexisting untracked documents remain untouched.

## RED → GREEN

1. Before implementation, three new regressions failed: missing initial-public transfer on the root alias, absent safe JSON handoff, and ordinary submit still intercepting to metadata-free JSON. Raw observed output retained in `red-initial-tests.log`.
2. CSP/tutorial regression assertions failed before their corresponding edits. Raw output retained in `red-csp-ui.log` (includes transient failures in older transport scenarios after the deliberate native-submit contract change).
3. The unchanged tracked HEAD runtime was later copied to scratch and exercised with the same real Chromium display acceptance. JS-on metadata disappeared; the no-JS allowlisted image was blocked by the old CSP; the repeated tutorial remained. This is baseline confirmation, not a claim that browser tests ran before all code edits.
4. Final full suite: **372 tests run; OK, 5 skipped**, exit 0. Final verbose log identifies the optional real-Postgres/Docker skips; none were enabled. Synthetic negative-test warning logs are expected and retained.
5. Local educational snapshot built by the existing allowlisted builder; **10 snapshot tests passed**, exit 0. No mirror repository was modified or published.
6. Publication guard positive/negative controls passed. Node syntax checks passed for site.js and calculator.js. `git diff --check` passed.

## Real browser evidence

Browser: Chromium 156.0.8078.4, headless automation through existing local Node Playwright 1.64.0; not the user's Firefox.

Four display cases passed: desktop 1280×900 and mobile 390×844, each with JavaScript on/off. Each showed the public notes/site/contact data and decoded the controlled PNG from the allowlisted image URL (`naturalWidth=1`). There were zero console/page errors, no attempted external traffic outside the locally fulfilled image, zero automatic balance requests and no horizontal overflow (1280/1280 and 390/390). The image test proves CSP/browser loading under controlled interception, not availability of a production image.

An additional 10 recorded flow checks passed: both aliases and lookup query with JS on/off; ordinary native GET submission in both modes; exact HTTPS `_blank`/noopener/noreferrer and in-place mailto/tel attributes; a single explicitly requested balance call with unchanged QR resource count and metadata retained; four malformed/unsafe initial-public variants preserving the address and rejecting unsafe URLs. These are local synthetic checks, not live chain evidence.

Mobile screenshot inspected: no visible collisions or clipping; long address wraps and guide button fits. The screenshot also exposes existing small low-contrast explanatory text and the guide button remains below the result; these are not newly introduced layout defects or separately redesigned here.

## Reproduction artifacts

All paths below are relative to:

```text
/home/saeb/.hermes/cache/scratch/lookup-public-display/
```

- `server.py`: synthetic app factory, stub lookup/limiter, balance spy, server outgoing socket refusal except loopback.
- `browser-check.js`: display matrix, controlled HTTPS PNG interception, reject other external traffic.
- `flow-check.js`: native/alias/contact/balance/defensive-hydration acceptance.
- `browser-evidence.json`: four GREEN cases and screenshot paths.
- `flow-evidence.json`: 10 GREEN flow records.
- `red-browser/browser-evidence.json`, `red-browser.log`: unchanged HEAD browser failure evidence.
- `desktop-js-on.png`, `desktop-js-off.png`, `mobile-js-on.png`, `mobile-js-off.png`.
- `red-initial-tests.log`, `red-csp-ui.log`.
- `green-ui-final.log`, `green-full-final-verbose.log`.
- `snapshot.log`, `educational-snapshot/`: locally rebuilt mirror, not publication.

Run the fixture with the site venv and an explicit public source directory, then run both Node harnesses against its loopback URL. Both owned preview servers were stopped; ports 18765/18766 no longer listen. The flow harness expects a fresh synthetic balance spy.

## Issues and boundaries

A scratch-only pip Playwright install failed on network timeouts; a bounded command-scoped proxy retry also failed. No proxy configuration was changed. Existing local Node Playwright/browser cache provided the real browser path without changing project dependencies. No generator/apps/default database/secret/local configuration/real print/production/external balance services were accessed.

Parent must independently review the final diff, decide release readiness and perform any separately authorized commit/push/deployment/publication. This report does not mark the task done or claim the changes are live.

## Review follow-up — 2026-11-11

Both verified defects are fixed; **status remains in-progress pending parent closure**. This section supersedes the earlier test count, not its historical evidence. Frozen intent is unchanged.

### Dispositions and actual RED/GREEN evidence

1. **Metadata missing after native balance failure — fixed.** Added an HTML regression covering `/s/<serial>?balance=1`, `/<serial>?balance=1`, and `/lookup?serial=<serial>&balance=1`. Actual RED: 28 tests ran with three failing subtests, each showing null initial-public instead of the complete sanitized object. The fix projects HTML metadata before the balance read can return 503. Focused GREEN: 28 tests passed, preserving address, explicit balance error, initial hydration data and no-JS notes/image/contact links.
2. **Supplementary Unicode rejected by UTF-16 length — fixed.** Added real site.js execution tests with 251/500/501 emoji notes and 17/32/33 emoji contact labels. Actual RED: 42 tests ran with four failing accepted-value subtests (251/500 notes, 17/32 labels); over-limit controls already rejected correctly. Changed the common text limit to `Array.from(text).length`. Independent server boundary tests pin the same Python codepoint limits. These server controls are additional coverage, not claimed as preexisting failures. Final full-suite GREEN includes all six Node boundary cases.
3. **Balance-failure API optional metadata — deliberately not widened.** This review fix is scoped to HTML rendering. Ordinary serial/reverse APIs remain exactly three-key; serial balance failure remains mapping + balance_error without public, and reverse balance failure retains its established error envelope. Exact-body assertions now pin both failure contracts even with populated public fields. Successful explicit balance responses still carry optional public. Changing API error metadata would be a separate consumer-contract decision, not an implicit side effect of fixing HTML.

### Final execution

```sh
env -u BTC_TEST_OWNER_PASSWORD_FILE NFC_TEST_POSTGRES=0 .venv/bin/python -m unittest discover -s bitcoin4funsite/tests -v
```

**375 tests ran in 50.776 seconds; OK, 5 skipped; exit 0.** Two existing real-database credential tests and three disposable-Docker PostgreSQL tests were explicitly disabled. No real DB was used. Expected synthetic failure warnings remain in raw logs.

Publication guard positive/negative controls passed; `node --check` for site.js and calculator.js and `git diff --check` all exited 0. Existing snapshot suite is included in the full run; local allowlisted snapshot was rebuilt into `review-educational-snapshot/`, builder exit 0. Nothing was published.

Real Chromium additionally passed **six mobile 390×844 cases**: all three native balance-failure HTML routes, JavaScript on/off, forced synthetic upstream exception, 503 status, complete visible 500-codepoint note and accepted 32-codepoint contact label, and no horizontal overflow. Server lookup/limiter/balance were injected; outbound server connections refused except loopback; allowlisted image was answered with controlled PNG bytes and other external browser traffic refused. This is local synthetic browser evidence, not live upstream or deployment evidence. The owned preview subprocess was terminated and waited for in a finally block.

### Review evidence files

Relative to the scratch evidence directory above:

- `review-red-balance.log`: actual three HTML regression failures before fix.
- `review-green-balance.log`: focused 28-test GREEN.
- `review-red-unicode.log`: actual four Unicode acceptance failures before fix.
- `review-green-full.log`: final verbose full-suite GREEN including Unicode boundaries/server controls and all skip reasons.
- `review-browser-run.py`, `review-server.py`, `review-browser.js`, `review-browser-server.log`, `review-browser-evidence.json`: synthetic browser reproduction and six passed records.
- `review-snapshot.log`, `review-educational-snapshot/`: final local rebuild, not publication.

Follow-up changes are limited to app.py, site.js, test_public_metadata_api.py, test_ui_contract.py, and these two BMad artifacts. No new repository file was created in this follow-up. Existing unrelated tracked work and the three untracked local documents were not edited. No commit/push/deploy, app/generator changes, secret reads, real database or production access occurred. Parent review/publication/closure remains outstanding.
