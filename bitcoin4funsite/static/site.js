"use strict";

(() => {
  const form = document.getElementById("lookup-form");
  if (!form) return;
  const field = document.getElementById("serial");
  const status = document.getElementById("lookup-status");
  const result = document.getElementById("lookup-result");
  const submit = document.getElementById("lookup-submit");
  const validSerial = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
  let requestVersion = 0;

  function announce(message, state) {
    status.textContent = message;
    status.dataset.state = state;
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function validWallet(wallet, serial) {
    return wallet && wallet.serial === serial && typeof wallet.address === 'string' &&
      /^bc1q[a-z0-9]{10,86}$/.test(wallet.address) &&
      wallet.explorer_url === 'https://mempool.space/address/' + wallet.address;
  }

  function showWallet(wallet) {
    const heading = element("h2", "", "آدرس عمومی این پاکت");
    const serialLabel = element("p", "result-label", "شمارهٔ سریال");
    const serial = element("p", "public-serial ltr-block", wallet.serial);
    serial.dir = "ltr";
    const addressLabel = element("p", "result-label", "آدرس دریافت در شبکهٔ اصلی بیت‌کوین");
    const address = element("p", "public-address ltr-block", wallet.address);
    address.dir = "ltr";
    const copy = element("button", "secondary-button", "کپی آدرس عمومی");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(wallet.address);
        announce("آدرس عمومی کپی شد. پس از چسباندن، آدرس کامل مقصد را دوباره بررسی کنید.", "success");
      } catch {
        announce("کپی خودکار ممکن نشد. آدرس عمومی را از کادر بالا انتخاب و دستی کپی کنید.", "error");
      }
    });
    const figure = element("figure", "qr-block");
    const qr = element("img");
    qr.src = "/api/wallets/" + encodeURIComponent(wallet.serial) + "/qr.svg";
    qr.alt = "کد تصویری آدرس عمومی برای دریافت بیت‌کوین";
    qr.width = 192;
    qr.height = 192;
    const caption = element("figcaption", "", "فقط برای دریافت؛ کلمات بازیابی در این تصویر نیست.");
    qr.addEventListener("error", () => {
      qr.hidden = true;
      caption.textContent = "کد تصویری فعلاً در دسترس نیست؛ از آدرس عمومی نوشته‌شده استفاده کنید.";
    });
    figure.append(qr, caption);
    const explorers = element("div", "explorer-links");
    for (const [prefix, label] of [
      ["https://mempool.space/address/", "کاوشگر مم‌پول ↗"],
      ["https://blockstream.info/address/", "کاوشگر بلاک‌استریم ↗"],
      ["https://www.blockchain.com/explorer/addresses/btc/", "کاوشگر بلاک‌چین ↗"]
    ]) {
      const explorer = element("a", "explorer-link", label);
      explorer.href = prefix + wallet.address;
      explorer.target = "_blank";
      explorer.rel = "noopener noreferrer";
      explorers.append(explorer);
    }
    const warning = element("p", "result-warning", "هر پیوند، یک سایت خارجی را در زبانهٔ جدید باز می‌کند و آدرس عمومی را با آن سرویس به اشتراک می‌گذارد. مرورگر هیچ درخواست خودکاری به این سرویس‌ها نمی‌فرستد. نمایش آدرس، تضمین موجودی یا تأیید تراکنش نیست.");
    result.replaceChildren(heading, serialLabel, serial, addressLabel, address, copy, figure, explorers, warning);
    result.hidden = false;
  }

  async function lookup(serial) {
    const version = ++requestVersion;
    result.setAttribute("aria-busy", "false");
    submit.disabled = false;
    result.hidden = true;
    result.replaceChildren();
    if (!validSerial.test(serial)) {
      field.setAttribute("aria-invalid", "true");
      announce("شمارهٔ سریال معتبر نیست. فقط حروف و ارقام انگلیسی، خط تیره یا زیرخط وارد کنید؛ آغاز آن باید حرف یا رقم باشد.", "error");
      field.focus();
      return;
    }
    field.removeAttribute("aria-invalid");
    result.setAttribute("aria-busy", "true");
    submit.disabled = true;
    announce("در حال پیدا کردن آدرس عمومی…", "loading");
    try {
      const response = await fetch("/api/wallets/" + encodeURIComponent(serial), {
        method: "GET",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (version !== requestVersion) return;
      if (response.status === 429) {
        announce("هر پانزده ثانیه فقط یک استعلام مجاز است؛ کمی صبر کنید و دوباره بزنید.", "error");
        return;
      }
      if (response.status === 404) {
        announce("پاکتی با این شمارهٔ سریال پیدا نشد. حروف و ارقام را دوباره با روی پاکت تطبیق دهید.", "error");
        return;
      }
      if (response.status === 400) {
        field.setAttribute("aria-invalid", "true");
        announce("شمارهٔ سریال معتبر نیست. آن را دقیقاً مطابق روی پاکت وارد کنید.", "error");
        return;
      }
      if (!response.ok) throw new Error("Lookup unavailable");
      const wallet = await response.json();
      if (version !== requestVersion) return;
      if (!validWallet(wallet, serial)) {
        throw new Error("Unexpected public wallet response");
      }
      showWallet(wallet);
      announce("آدرس عمومی پیدا شد. پیش از واریز، آدرس کامل و شبکه را بررسی کنید.", "success");
    } catch {
      if (version !== requestVersion) return;
      announce("سرویس استعلام فعلاً در دسترس نیست. کمی بعد دوباره تلاش کنید؛ کلمات بازیابی را ارسال نکنید.", "error");
    } finally {
      if (version === requestVersion) {
        result.setAttribute("aria-busy", "false");
        submit.disabled = false;
      }
    }
  }

  field.addEventListener("invalid", (event) => {
    event.preventDefault();
    return lookup(field.value);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return lookup(field.value);
  });

  if (form.dataset.initialSerial) {
    const serial = form.dataset.initialSerial;
    const state = form.dataset.initialState;
    const wallet = { serial, address: form.dataset.initialAddress, explorer_url: form.dataset.initialExplorer };
    if (state === 'found' && validSerial.test(serial) && validWallet(wallet, serial)) {
      showWallet(wallet);
      announce("آدرس عمومی پیدا شد. پیش از واریز، آدرس کامل و شبکه را بررسی کنید.", "success");
    } else if (state === 'rate_limited') {
      announce("هر پانزده ثانیه فقط یک استعلام مجاز است؛ کمی صبر کنید و دوباره بزنید.", "error");
    } else if (state === 'not_found') {
      announce("پاکتی با این شمارهٔ سریال پیدا نشد. حروف و ارقام را دوباره با روی پاکت تطبیق دهید.", "error");
    } else if (state) {
      announce("سرویس استعلام فعلاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید.", "error");
    } else {
      lookup(serial);
    }
  }
})();
