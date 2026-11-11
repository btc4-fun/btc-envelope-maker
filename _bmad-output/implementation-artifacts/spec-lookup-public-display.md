---
title: 'نمایش کامل و خلوت اطلاعات عمومی استعلام'
type: 'bugfix'
created: '2026-11-11'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

صفحهٔ استعلام باید با جاوااسکریپت روشن و خاموش توضیحات عمومی، نام و نشانی سایت، تصویر و لینک‌های تماس معتبر را نشان دهد. علت حذف اطلاعات پس از اجرای جاوااسکریپت ابتدا با آزمون شکست‌خورده و دادهٔ مصنوعی بازتولید شود. انتقال امن دادهٔ پالایش‌شدهٔ اولیه به نمایشگر موجود، بدون درخواست اضافه، انجام شود. ارسال عادی فرم باید همین اطلاعات را نشان دهد؛ قرارداد سه‌عضوی رابط عادی تغییر نکند و هیچ درخواست خودکار موجودی اضافه نشود. استفاده از ارسال بومی فرم برای استعلام عادی مجاز است.

توضیحات طولانی و تصاویر آموزشی کاغذ داخل و بیرون از استعلام حذف و با دکمهٔ واضح به بخش موجود راهنما جایگزین شوند. هشدار کوتاه کلمات بازیابی و هشدارهای ضروری نتیجه باقی بمانند. تصاویر پذیرفته‌شده فقط روی سه میزبان فعلی پروژه مجاز شوند، نه همهٔ اینترنت؛ سایر محدودیت‌های سیاست محتوا حفظ شوند.

دادهٔ واقعی، دیتابیس، مولد، اپ‌ها، اسرار و چاپ واقعی خوانده یا تغییر نکنند. سه سند محلی ثبت‌نشده دست‌نخورده بمانند. کامیت، پوش، انتشار آینه، استقرار و پراکسی خارج از مجوز هستند. آزمون مرورگر واقعی شامل جاوااسکریپت روشن و خاموش، تصویر بارگذاری‌شده، مقصد و رفتار لینک‌ها، عرض موبایل و نبود دریافت خودکار موجودی باشد. خروجی آموزشی فهرست‌مجاز محلی بازسازی شود؛ ساخت محلی با انتشار یکسان نیست.

</frozen-after-approval>

## Implementation Notes

بررسی اولیه: قالب فقط در noscript متادیتا دارد؛ شیء اولیه در site.js فاقد public است. سیاست img-src هم‌مبدأ با میزبان‌های پذیرفته‌شده سازگار نیست. مسیر کوتاه سریال نیز الحاق اطلاعات عمومی ندارد. این‌ها یافتهٔ منبع‌اند و هنوز آزمون شکست‌خورده اجرا نشده است.

شکاف تصمیم محصول یا عملیات برگشت‌ناپذیر وجود ندارد. دامنهٔ کوچک: قالب استعلام، اسکریپت نمایش، الحاق متادیتای صفحه و سیاست تصویر، آزمون‌ها و مستند کوتاه. مسیر oneshot انتخاب شد. مجوز ادامه با حفظ سه فایل محلی در پاسخ «bd» دریافت شد.

### Implementation verification — awaiting independent parent review

- Added JSON-escaped initial public data and defensive hydration through the existing safe DOM renderer. Ordinary lookup remains a native GET; only explicit balance is enhanced. No API response contract was widened.
- Used the Flask endpoint identity for public metadata attachment so both serial aliases behave identically. Limited CSP image sources to self plus the existing three HTTPS project hosts; removed the blocked inline error handler.
- Removed the repeated tutorial include from lookup only, replacing it with a guide anchor button and concise purchase/seed warnings. Guide content and educational image files are unchanged.
- Test-first RED: three initial regression tests failed before implementation. A later CSP/tutorial RED also failed as expected. The unchanged HEAD runtime was then independently run against the same real-browser display acceptance; JS-on metadata was absent, no-JS image loading was CSP-blocked, and the old tutorial was present.
- GREEN: 372 tests ran, 5 skipped, no failures. Local educational snapshot rebuilt; all 10 snapshot tests passed. Publication guard, JavaScript syntax and diff whitespace checks passed.
- Real Chromium acceptance passed at desktop 1280 and mobile 390 widths, JS on/off: metadata and controlled allowlisted PNG loaded, no horizontal overflow, no automatic balance requests. Alias/form flow acceptance passed 10 recorded checks, including native form submission, exact HTTPS/mailto/tel attributes, one explicit balance request without QR refetch, and malformed/unsafe hydration retaining the address.
- Evidence and reproduction scripts are in the scratch directory linked from the verification report. This is local fixture evidence, not production or the user's Firefox. No real DB, external chain service, generator, app, secret or physical printing was accessed.
- Status remains in-progress for independent review. No commit, push, mirror publication or deployment was performed by the implementation worker. Subsequent release actions belong to the parent after review.

[Verification report](verification-lookup-public-display.md)

### Review follow-up — 2026-11-11 (parent closure pending)

- **Fixed: HTML metadata lost on balance failure.** New regression failed on all three HTML routes before code changes: initial-public decoded to null after the balance exception. HTML endpoint metadata is now projected before the optional upstream read, retaining notes/site/image/links with the address and explicit unavailable state on 503. Focused GREEN: 28 tests passed.
- **Fixed: UTF-16 length rejects valid supplementary Unicode.** New Node-renderer regression failed for 251/500-emoji notes and 17/32-emoji labels before the one-line fix. `publicText` now counts code points using `Array.from(text).length`, matching Python. Tests also reject 501-codepoint notes and 33-codepoint labels; server boundary controls independently pass.
- **API disposition: compatibility preserved.** Ordinary serial and reverse APIs keep their exact three-key bodies. Balance-failure serial API retains mapping plus balance_error, without public; reverse API retains its existing error envelope. These preexisting failure shapes are pinned by exact-body assertions rather than widened by an HTML bugfix. Successful explicit balance responses continue to include optional public metadata.
- **Verification:** final full suite ran 375 tests, OK with 5 explicitly disabled opt-in PostgreSQL/Docker skips; real database credentials flag unset and NFC_TEST_POSTGRES=0. Publication guard, both JavaScript syntax checks and diff whitespace check passed. Local allowlisted educational snapshot rebuilt without publication. Real Chromium passed six mobile cases (three HTML routes × JS on/off) with forced balance failure, visible 500-codepoint notes and 32-codepoint contact labels, and no horizontal overflow. Owned fixture server stopped.
- Review evidence, commands and limitations are appended to the verification report. Frozen intent unchanged; status remains in-progress. No commit, push, deploy, production/DB/apps/generator/secrets access, or edits to the three unrelated untracked documents.
