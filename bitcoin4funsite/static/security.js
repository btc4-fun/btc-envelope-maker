"use strict";

(() => {
  const questionnaire = document.getElementById("security-questionnaire");
  if (!questionnaire) return;
  const names = ["secrets", "public", "device", "apps", "password", "updates",
    "shared", "compromise", "links", "knowledge"];
  const radios = Array.from(document.querySelectorAll('#security-questionnaire input[type="radio"]'));
  const status = document.getElementById("security-status");
  const result = document.getElementById("security-result");

  function clearResult() {
    result.hidden = true;
    delete result.dataset.level;
    document.getElementById("security-score").textContent = "";
    document.getElementById("security-advice").textContent = "";
    status.textContent = "";
    for (const name of names) document.getElementById("security-" + name).removeAttribute("aria-invalid");
  }

  function resetAnswers() {
    for (const radio of radios) radio.checked = false;
    clearResult();
  }

  for (const radio of radios) radio.addEventListener("change", clearResult);
  document.getElementById("security-reset").addEventListener("click", () => {
    resetAnswers();
    radios[0].focus();
  });
  // Do not retain answers restored by browser history or form-state restoration.
  window.addEventListener("pageshow", resetAnswers);
  resetAnswers();

  document.getElementById("security-check").addEventListener("click", () => {
    clearResult();
    let firstMissing = null;
    for (const name of names) {
      const group = document.getElementById("security-" + name);
      const selected = radios.filter(radio => radio.name === name && radio.checked);
      if (selected.length !== 1 || !["safe", "risk", "unknown"].includes(selected[0].value)) {
        group.setAttribute("aria-invalid", "true");
        if (!firstMissing) firstMissing = radios.find(radio => radio.name === name);
      } else {
        group.removeAttribute("aria-invalid");
      }
    }
    if (firstMissing) {
      status.textContent = "لطفاً به همهٔ پرسش‌ها پاسخ دهید. اگر جواب را نمی‌دانید، «مطمئن نیستم» را بزنید.";
      firstMissing.focus();
      return;
    }
    status.textContent = "";
    const flagged = radios.filter(radio => radio.checked && radio.value !== "safe").map(radio => radio.name);
    const score = String(flagged.length).replace(/[0-9]/g, digit => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
    document.getElementById("security-score").textContent = "شاخص احتیاط آموزشی: " + score + " از ۱۰ مورد نیاز به بررسی دارد. این عدد احتمال از دست دادن پول نیست.";
    const stop = flagged.some(name => name !== "knowledge");
    result.dataset.level = stop ? "stop" : flagged.length ? "learn" : "review";
    let advice = stop
      ? "توقف: تا رفع مشکل یا روشن شدن چیزی که درباره‌اش شک دارید، پاکت را باز نکنید. کلمات را وارد نکنید و به این کیف پول واریز نکنید. اگر نمی‌دانید چطور مشکل را بررسی کنید، از فرد متخصص معتبر کمک بگیرید. راز کیف پول را به او هم ندهید. "
      : flagged.length
        ? "اول بدون پول واقعی یاد بگیرید و تمرین کنید. "
        : "در پاسخ‌های شما موردی برای توقف پیدا نشد. این به معنی بررسی گوشی شما نیست. عدد پایین تضمین امنیت نیست. پیش از باز کردن پاکت، راهنمای بالا را مرور کنید. اشتباه، کلاهبرداری و افت قیمت هنوز ممکن است. ";
    const steps = {
      secrets: "اگر راز لو رفته، پاک کردن عکس یا عوض کردن رمز گوشی کافی نیست. کیف پول تازه با کلمات تازه لازم است. اگر موجودی دارید، با دستگاه قابل اعتماد و کمک فرد متخصص معتبر آن را به کیف پول تازه منتقل کنید.",
      public: "به جای خصوصی بروید. مطمئن شوید کسی یا دوربینی کلمات را نمی‌بیند. تماس تصویری و نشان دادن صفحه به دیگران را قطع کنید.",
      device: "کلمات را فقط در دستگاه قابل اعتماد وارد کنید. اگر حفاظت گوشی دست‌کاری شده یا به ورود دیگران شک دارید، اول آن را به فرد متخصص معتبر نشان دهید.",
      apps: "برنامه‌های ناشناس و اجازه‌های آن‌ها را بررسی کنید. در اندروید، اجازهٔ نصب برنامه‌های ناشناس را خاموش کنید. به برنامهٔ ناشناس اجازهٔ دیدن صفحه یا کنترل گوشی ندهید. پاک کردن برنامه به‌تنهایی ثابت نمی‌کند گوشی امن شده است.",
      password: "قفل صفحه را روشن کنید. رمز تازه و غیرتکراری بگذارید. از تاریخ تولد، شمارهٔ موبایل یا بخشی از کد ملی خود و خانواده استفاده نکنید.",
      updates: "گوشی و برنامه‌ها را به‌روز کنید. اگر گوشی دیگر به‌روزرسانی امنیتی نمی‌گیرد، از دستگاه قابل اعتماد دیگری استفاده کنید.",
      shared: "کلمات را روی گوشی مشترک باز نکنید. برای دیگران حساب یا گوشی جدا در نظر بگیرید. نصب برنامه و دسترسی به کلمات را محدود کنید. این احتیاط برای همه است، نه فقط کودکان.",
      compromise: "ورود قبلی دیگران به حساب، به‌تنهایی ثابت نمی‌کند گوشی آلوده است. با دستگاه قابل اعتماد رمزهای لو رفته را عوض کنید. دستگاه‌های ناشناس را از حساب خارج کنید. علت مشکل را بررسی کنید. برای سوءاستفاده از حساب بانکی با بانک تماس بگیرید.",
      links: "زدن لینک مشکوک به‌تنهایی ثابت نمی‌کند گوشی آلوده است. بررسی کنید آیا رمز داده‌اید، برنامه نصب کرده‌اید یا اجازه‌ای داده‌اید. با دستگاه قابل اعتماد رمزهای لو رفته را عوض کنید. برنامه و اجازهٔ مشکوک را با کمک فرد متخصص معتبر بررسی کنید.",
      knowledge: "بدون پول واقعی تمرین کنید. فرق آدرس و کلمات کیف پول را یاد بگیرید. روش نگهداری نسخهٔ کاغذی امن را یاد بگیرید. قیمت ممکن است پایین بیاید. پولی که اشتباه می‌فرستید شاید برنگردد."
    };
    for (const name of flagged) advice += steps[name] + " ";
    advice += "این عدد احتمال از دست دادن پول نیست. نتیجه توصیه به خرید نیست و اجازه‌ای برای گذاشتن پول زیاد نیست.";
    document.getElementById("security-advice").textContent = advice;
    result.hidden = false;
    result.focus();
  });
  questionnaire.hidden = false;
})();
