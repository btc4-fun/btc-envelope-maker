"use strict";

(() => {
  if (!document.getElementById("payment-details")) return;
  const status = document.getElementById("payment-status");
  const qr = document.getElementById("payment-qr");
  const caption = document.getElementById("payment-qr-caption");
  const kinds = ["card", "sheba"];
  const labels = {
    card: "کد تصویری شمارهٔ کارت",
    sheba: "کد تصویری بخش عددی شبا"
  };
  let selected = "card";
  let copyVersion = 0;

  function showQr(kind) {
    selected = kind;
    qr.hidden = true;
    caption.textContent = labels[kind];
    qr.alt = labels[kind];
    qr.src = document.getElementById("payment-show-" + kind).getAttribute("href");
    for (const key of kinds) {
      document.getElementById("payment-show-" + key).setAttribute("aria-pressed", String(key === kind));
    }
    if (qr.complete && qr.naturalWidth > 0) qr.hidden = false;
  }

  qr.addEventListener("load", () => {
    qr.hidden = false;
    caption.textContent = labels[selected];
  });
  qr.addEventListener("error", () => {
    qr.hidden = true;
    caption.textContent = "کد تصویری در دسترس نیست؛ شمارهٔ نوشته‌شده را دستی کپی کنید.";
  });

  for (const kind of kinds) {
    const copy = document.getElementById("payment-copy-" + kind);
    copy.addEventListener("click", async () => {
      const version = ++copyVersion;
      status.textContent = "در حال کپی…";
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(copy.dataset.copy);
        if (version !== copyVersion) return;
        status.textContent = "شماره کپی شد؛ پس از چسباندن، شمارهٔ مقصد و نام صائب ملایی را بررسی کنید.";
        status.dataset.state = "success";
      } catch {
        if (version !== copyVersion) return;
        status.textContent = "کپی خودکار ممکن نشد؛ شماره را انتخاب و دستی کپی کنید.";
        status.dataset.state = "error";
      }
    });
    const control = document.getElementById("payment-show-" + kind);
    control.addEventListener("click", event => {
      event.preventDefault();
      showQr(kind);
    });
    control.addEventListener("keydown", event => {
      if (event.key !== " ") return;
      event.preventDefault();
      showQr(kind);
    });
  }
})();

(() => {
  const form = document.getElementById("lookup-form");
  if (!form) return;
  const field = document.getElementById("serial");
  const status = document.getElementById("lookup-status");
  const result = document.getElementById("lookup-result");
  const submit = document.getElementById("lookup-submit");
  const balanceSubmit = document.getElementById("balance-submit");
  let currentWallet = null;
  let balancePanel = null;
  // The native form and JS use the server's generator-derived grammar.
  // (?![\s\S]) is an absolute end assertion; $ alone permits a final newline.
  const validSerial = new RegExp("^(?:" + (field.getAttribute("pattern") || "(?!)") + ")(?![\\s\\S])");
  let requestVersion = 0;
  let controller = null;

  function invalidateLookup() {
    ++requestVersion;
    controller?.abort();
    controller = null;
    currentWallet = null;
    result.hidden = true;
    result.replaceChildren();
    result.setAttribute("aria-busy", "false");
    submit.disabled = balanceSubmit.disabled = false;
    announce("", "");
  }
  field.addEventListener("input", invalidateLookup);
  window.addEventListener("pagehide", invalidateLookup);

  function announce(message, state) {
    status.textContent = message;
    status.dataset.state = state;
  }

  function limitedMessage(retryAfter) {
    const seconds = typeof retryAfter === 'string' && /^(?:[1-9]|[1-5][0-9]|60)$/.test(retryAfter)
      ? retryAfter.replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]) : null;
    return "برای هر اتصال اینترنتی، پنج استعلام در شصت ثانیه مجاز است؛ " +
      (seconds ? "پس از " + seconds + " ثانیه دوباره تلاش کنید." : "کمی صبر کنید و دوباره بزنید.");
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

  const PUBLIC_HOSTS = ["btc4.fun", "btc.saeb.id.ir", "b.tc4fun.ir"];
  const UNSAFE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/;

  function publicText(value, max) {
    if (typeof value !== "string") return null;
    const text = value.trim();
    if (!text || text.length > max || UNSAFE.test(text)) return null;
    return text;
  }

  function publicUrl(value) {
    const text = publicText(value, 512);
    if (text === null || !text.startsWith("https://")) return null;
    let url;
    try { url = new URL(text); } catch { return null; }
    if (url.protocol !== "https:" || !PUBLIC_HOSTS.includes(url.hostname) ||
        url.host !== url.hostname || url.username || url.password ||
        !["", "/"].includes(url.port)) {
      return null;
    }
    return text;
  }

  function publicBlock(wallet) {
    const source = wallet.public;
    if (!source || typeof source !== "object") return null;
    const notes = publicText(source.notes, 500);
    let site = null;
    if (source.site && typeof source.site === "object") {
      const key = publicText(source.site.key, 64);
      const href = publicUrl(source.site.url);
      if (key && href && /^[A-Za-z0-9._-]{1,64}$/.test(key)) site = { key, href };
    }
    const image = publicUrl(source.image_url);
    if (notes === null && site === null && image === null) return null;
    const section = element("section");
    section.setAttribute("aria-label", "اطلاعات اختیاری پاکت");
    if (notes !== null) {
      section.append(element("p", "result-label", "یادداشت عمومی"), element("p", "public-notes", notes));
    }
    if (site !== null) {
      const link = element("a", "ltr-block", site.key);
      link.dir = "ltr";
      link.href = site.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      const wrap = element("p");
      wrap.append(link);
      section.append(element("p", "result-label", "سایت"), wrap);
    }
    if (image !== null) {
      const img = element("img");
      img.src = image;
      img.alt = "";
      img.width = 320;
      img.height = 180;
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", () => { img.hidden = true; });
      section.append(element("p", "result-label", "تصویر"), img);
    }
    section.append(element("p", "", "این اطلاعات اختیاری را فروشنده نوشته است؛ تأیید موجودی یا اصالت پاکت نیست."));
    return section;
  }

  const balanceUnavailable = "موجودی فعلاً در دسترس نیست؛ این خطا به معنی صفر نیست. آدرس و کد تصویری همچنان قابل استفاده‌اند.";

  function showBalance(wallet) {
    const balance = wallet.balance;
    if (balancePanel) {
      balancePanel.replaceChildren();
      balancePanel.hidden = true;
    }
    if (!balance && !wallet.balance_error) return;
    const panel = balancePanel || element("section");
    if (!balancePanel) result.append(panel);
    balancePanel = panel;
    panel.hidden = false;
    panel.setAttribute("aria-label", "موجودی آدرس عمومی");
    const valid = balance && balance.address === wallet.address &&
      Number.isSafeInteger(balance.confirmed_sats) && balance.confirmed_sats >= 0 &&
      balance.confirmed_sats <= 2100000000000000 &&
      Number.isSafeInteger(balance.pending_delta_sats) && Math.abs(balance.pending_delta_sats) <= 2100000000000000 &&
      balance.source === 'https://blockstream.info/api' &&
      typeof balance.fetched_at === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00$/.test(balance.fetched_at) &&
      Number.isFinite(Date.parse(balance.fetched_at));
    if (!valid || wallet.balance_error) {
      wallet.balance_error = 'unavailable';
      panel.append(element("p", "lookup-status", balanceUnavailable));
    } else {
      panel.append(element("h2", "", "موجودی آدرس عمومی"));
      for (const [label, amount, signed] of [
        ["موجودی تأییدشده", balance.confirmed_sats, false],
        ["تغییر خالص در انتظار", balance.pending_delta_sats, true]
      ]) {
        const magnitude = BigInt(Math.abs(amount));
        const sign = amount < 0 ? '-' : signed && amount > 0 ? '+' : '';
        const sats = element("p", "ltr-block", sign + magnitude);
        const btc = element("p", "ltr-block", sign + magnitude / 100000000n + '.' +
          (magnitude % 100000000n).toString().padStart(8, '0'));
        sats.dir = btc.dir = "ltr";
        panel.append(element("h3", "", label), element("p", "", "ساتوشی"), sats,
          element("p", "", "بیت‌کوین"), btc);
      }
      const source = element("p", "ltr-block", balance.source);
      const fetched = element("p", "ltr-block", balance.fetched_at);
      source.dir = fetched.dir = "ltr";
      panel.append(element("p", "", "منبع"), source,
        element("p", "", "زمان شروع دریافت به وقت جهانی؛ زمان ثبت در شبکه نیست."), fetched,
        element("p", "", "تغییر در انتظار قطعی نیست؛ می‌تواند منفی، حذف یا جایگزین شود. این اعداد تضمین موجودی قابل خرج یا اصالت پاکت نیستند. تاریخچه دریافت نمی‌شود."));
    }
  }

  function showWallet(wallet) {
    if (currentWallet?.serial === wallet.serial && currentWallet.address === wallet.address && !result.hidden) {
      currentWallet = wallet;
      showBalance(wallet);
      return;
    }
    balancePanel = null;
    currentWallet = wallet;
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
    const nodes = [heading, serialLabel, serial, addressLabel, address, copy, figure];
    const optional = publicBlock(wallet);
    if (optional !== null) nodes.push(optional);
    nodes.push(explorers, warning);
    result.replaceChildren(...nodes);
    result.hidden = false;
    showBalance(wallet);
  }

  async function lookup(serial, withBalance = false) {
    const version = ++requestVersion;
    controller?.abort();
    controller = new AbortController();
    balanceSubmit.disabled = false;
    result.setAttribute("aria-busy", "false");
    submit.disabled = false;
    const retained = withBalance && currentWallet?.serial === serial ? {
      serial, address: currentWallet.address, explorer_url: currentWallet.explorer_url
    } : null;
    if (retained) showWallet(retained);
    else {
      currentWallet = null;
      result.hidden = true;
      result.replaceChildren();
    }
    if (!validSerial.test(serial)) {
      field.setAttribute("aria-invalid", "true");
      announce("شمارهٔ سریال معتبر نیست. فقط حروف و ارقام انگلیسی، خط تیره یا زیرخط وارد کنید؛ آغاز آن باید حرف یا رقم باشد.", "error");
      field.focus();
      return;
    }
    field.removeAttribute("aria-invalid");
    result.setAttribute("aria-busy", "true");
    submit.disabled = true;
    balanceSubmit.disabled = true;
    announce(withBalance ? "در حال دریافت موجودی…" : "در حال پیدا کردن آدرس عمومی…", "loading");
    try {
      const response = await fetch("/api/wallets/" + encodeURIComponent(serial) + (withBalance ? "?balance=1" : ""), {
        method: "GET",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal
      });
      if (version !== requestVersion) return;
      if (response.status === 429) {
        announce(limitedMessage(response.headers?.get("Retry-After")), "error");
        return;
      }
      if (response.status === 404) {
        currentWallet = null;
        balancePanel = null;
        result.replaceChildren();
        result.hidden = true;
        announce("پاکتی با این شمارهٔ سریال پیدا نشد. حروف و ارقام را دوباره با روی پاکت تطبیق دهید.", "error");
        return;
      }
      if (response.status === 400) {
        field.setAttribute("aria-invalid", "true");
        announce("شمارهٔ سریال معتبر نیست. آن را دقیقاً مطابق روی پاکت وارد کنید.", "error");
        return;
      }
      if (!response.ok && !(withBalance && response.status === 503)) throw new Error("Lookup unavailable");
      const wallet = await response.json();
      if (version !== requestVersion) return;
      if (!validWallet(wallet, serial)) {
        throw new Error("Unexpected public wallet response");
      }
      if (withBalance && !wallet.balance) wallet.balance_error = 'unavailable';
      showWallet(wallet);
      announce(withBalance ? (wallet.balance_error ? balanceUnavailable : "نتیجهٔ موجودی دریافت شد؛ زمان و محدودیت‌های زیر را بخوانید.") :
        "آدرس عمومی پیدا شد. پیش از واریز، آدرس کامل و شبکه را بررسی کنید.", wallet.balance_error ? "error" : "success");
    } catch {
      if (version !== requestVersion) return;
      if (retained) showWallet({...retained, balance_error: 'unavailable'});
      announce(withBalance ? balanceUnavailable : "سرویس استعلام فعلاً در دسترس نیست. کمی بعد دوباره تلاش کنید؛ کلمات بازیابی را ارسال نکنید.", "error");
    } finally {
      if (version === requestVersion) {
        result.setAttribute("aria-busy", "false");
        submit.disabled = false;
        balanceSubmit.disabled = false;
      }
    }
  }

  field.addEventListener("invalid", (event) => {
    event.preventDefault();
    return lookup(field.value);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    return lookup(field.value, event.submitter === balanceSubmit);
  });

  if (form.dataset.initialSerial) {
    const serial = form.dataset.initialSerial;
    const state = form.dataset.initialState;
    const wallet = { serial, address: form.dataset.initialAddress, explorer_url: form.dataset.initialExplorer };
    if (state === 'found' && validSerial.test(serial) && validWallet(wallet, serial)) {
      try { wallet.balance = JSON.parse(form.dataset.initialBalance || 'null'); }
      catch { wallet.balance_error = 'unavailable'; }
      if (form.dataset.balanceError) wallet.balance_error = 'unavailable';
      showWallet(wallet);
      announce(wallet.balance_error ? balanceUnavailable : "آدرس عمومی پیدا شد. پیش از واریز، آدرس کامل و شبکه را بررسی کنید.", wallet.balance_error ? "error" : "success");
    } else if (state === 'rate_limited') {
      announce(limitedMessage(form.dataset.retryAfter), "error");
    } else if (state === 'not_found') {
      announce("پاکتی با این شمارهٔ سریال پیدا نشد. حروف و ارقام را دوباره با روی پاکت تطبیق دهید.", "error");
    } else if (state) {
      announce("سرویس استعلام فعلاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید.", "error");
    } else {
      lookup(serial);
    }
  }
})();
