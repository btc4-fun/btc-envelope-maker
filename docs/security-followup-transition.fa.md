# گذار سهمیه و پراکسی

## گذار فرم تماس

توکن نسخهٔ یک پس از ارتقا پذیرفته نمی‌شود. فرم بازمانده از نسخهٔ قبلی باید دوباره بارگیری شود تا توکن نسخهٔ دو و پرسش جمع تازه بگیرد؛ پیام قبلی خودکار ارسال یا تکرار نمی‌شود. حفظ پیش‌نویس در این تغییر اضافه نشده است.

```text
token v1 → rejected
token v2 → signed question
```

استقرار باید هماهنگ باشد: همهٔ پردازش‌های قدیمی صادرکننده و پذیرندهٔ فرم با نسخهٔ تازه جایگزین شوند و از ترکیب هم‌زمان دو نسخه جلوگیری شود. پس از جایگزینی، فرم تازه و ارسال مصنوعی کنترل شود. سهمیه‌های سراسری تماس تغییر نکرده‌اند و برای این گذار نباید پایگاه پذیرش حذف یا سهمیه‌ها بازنشانی شوند.

نشانی‌های نسخهٔ شش با پیشوند شصت‌وچهاربیتی یکسان، سهمیهٔ تماس، استعلام و تگ مشترک دارند. نشانی نگاشت‌شدهٔ نسخهٔ چهار با شکل معمول نسخهٔ چهار یکسان است. قالب چکیدهٔ نشانی معمول نسخهٔ چهار تغییر نکرده است.

چکیده‌های قبلی حذف یا بازنویسی نمی‌شوند و طبق عمر قبلی منقضی می‌شوند. چون نشانی خام ذخیره نشده است، تبدیل چکیدهٔ قدیمی نسخهٔ شش به پیشوند ممکن نیست؛ سهمیهٔ آن هنگام ارتقا یک بار بازنشانی می‌شود. سهمیهٔ نگاشت‌شدهٔ نسخهٔ چهار در استعلام نیز اکنون به سهمیهٔ نسخهٔ چهار متصل است. برای جلوگیری از اجرای هم‌زمان دو سیاست، همهٔ پردازش‌های قدیمی باید هنگام استقرار با نسخهٔ جدید جایگزین شوند.

فهرست پراکسی معتبر به‌صورت پیش‌فرض خالی است. پیش از استقرار، مالک باید نشانی یا شبکهٔ دقیق همتای متصل را صریحاً تنظیم کند. نشانی دروازه از روی خصوصی‌بودن یا محلی‌بودن حدس زده نمی‌شود. بدون این تنظیم، همهٔ کاربران پشت پراکسی سهمیهٔ همان همتا را خواهند داشت.

```text
TRUSTED_PROXIES
```

نمونهٔ محیط عمومی این مقدار را خالی دارد و ترکیب کانتینر همان مقدار را صریحاً به برنامه می‌رساند. مقدار باید در محیط اجرای ترکیب یا فایل محیط کنار آن توسط مالک تنظیم شود؛ گذاشتن آن فقط در فایل محیط تماس یا قیمت کافی نیست، چون مقدار صریح ترکیب اولویت دارد. هیچ دروازه‌ای به‌صورت خودکار انتخاب نمی‌شود.

مقدار، فهرستی جداشده با ویرگول از نشانی یا شبکهٔ معتبر است. فقط پراکسی‌ای را مجاز کنید که زنجیرهٔ مبدأ را به‌درستی تکمیل یا پاک‌سازی می‌کند؛ فقط آخرین عضو زنجیره بررسی می‌شود. اگر آن عضو نامعتبر باشد، نشانی همتا استفاده می‌شود و عضوهای قبلی جایگزین آن نمی‌شوند. ورودی نامعتبر تنظیم باعث توقف راه‌اندازی می‌شود.

## Security/contact release gate

The security/contact release retains the existing feature flags, credentials,
mounts and quota state. It does not enable a new NFC feature, run database
queries/migrations, read real wallets, or change the shared reverse proxy.

Before activation, observe the connecting peer with a uniquely marked health
request through the existing proxy; also prove a client-supplied forwarded
address is not accepted as the last hop. Configure only that observed address
explicitly in the web service override. Do not publish private host inventory
or runtime configuration in this repository.

A source-only native image may retain the approved immutable application's
installed dependencies only after its complete recorded runtime manifest,
unchanged dependency lock and interpreter/startup compatibility are verified.
Build from committed allowlisted public files, never a dirty workspace. Verify
all runtime bytes in a network-disabled synthetic candidate and again in the
actual serving container. Synthetic contact delivery uses an injected recorder
and disposable state, never the real notification provider or quota database.

Preserve the exact existing override and old immutable image before activation.
Compare concurrent configuration immediately before writing. Change only the
web image pin and explicit proxy setting, stop every old worker, then recreate
only web. Preserve all existing state and secret identities. Public acceptance
requires health, a visible signed arithmetic question, same-origin referrer
policy, and rejection of missing/null/foreign Origin; no real contact message
is needed. Rollback must stop the new workers first, restore the exact saved
override, and verify old-image health. Neither rollback nor upgrade may clear
quota state. Live activation and exact commit/image evidence belong in the
operator's deployment report; this runbook alone does not claim activation.
