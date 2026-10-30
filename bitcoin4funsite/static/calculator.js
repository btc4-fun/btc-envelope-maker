"use strict";

(() => {
  if (!document.getElementById("satoshi-converter")) return;
  const btc = document.getElementById("btc-amount");
  const sats = document.getElementById("satoshi-amount");
  const status = document.getElementById("converter-status");
  const unit = 100000000n;
  const maximum = 21000000n * unit;

  function convert(source, destination, fromBitcoin) {
    source.removeAttribute("aria-invalid");
    destination.removeAttribute("aria-invalid");
    if (source.value === "") {
      destination.value = "";
      status.textContent = "برای تبدیل، یکی از دو مقدار را با ارقام انگلیسی وارد کنید. هیچ مقداری ارسال نمی‌شود.";
      status.dataset.state = "idle";
      return;
    }
    const pattern = fromBitcoin ? /^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,8})?$/ : /^(?:0|[1-9][0-9]{0,15})$/;
    if (!pattern.test(source.value)) {
      destination.value = "";
      source.setAttribute("aria-invalid", "true");
      status.textContent = "مقدار معتبر نیست؛ فقط ارقام انگلیسی، بدون فاصله یا جداکننده. بیت‌کوین حداکثر هشت رقم اعشار و ساتوشی عدد صحیح دارد.";
      status.dataset.state = "error";
      return;
    }
    const parts = source.value.split(".");
    const amount = fromBitcoin ? BigInt(parts[0]) * unit + BigInt((parts[1] || "").padEnd(8, "0")) : BigInt(source.value);
    if (amount > maximum) {
      destination.value = "";
      source.setAttribute("aria-invalid", "true");
      status.textContent = "مقدار از سقف ۲۱ میلیون بیت‌کوین بیشتر است.";
      status.dataset.state = "error";
      return;
    }
    const fraction = (amount % unit).toString().padStart(8, "0").replace(/0+$/, "");
    destination.value = fromBitcoin ? amount.toString() : (amount / unit).toString() + (fraction ? "." + fraction : "");
    status.textContent = "تبدیل دقیق انجام شد؛ بدون گرد کردن و بدون ارسال اطلاعات.";
    status.dataset.state = "success";
  }

  btc.addEventListener("input", () => convert(btc, sats, true));
  sats.addEventListener("input", () => convert(sats, btc, false));
})();

(() => {
  const panel = document.getElementById("market-panel");
  if (!panel) return;
  const status = document.getElementById("market-status");
  const data = document.getElementById("market-data");
  const stale = document.getElementById("market-stale");
  const rows = document.getElementById("quote-rows");
  const positiveDecimal = value => typeof value === "string" && value.length <= 48 &&
    /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value) && /[1-9]/.test(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const grouped = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimal = value => {
    const parts = value.split(".");
    return grouped(parts[0]) + (parts[1] ? "." + parts[1] : "");
  };

  function validMarket(market) {
    if (!market || !["fresh", "stale"].includes(market.status) ||
        typeof market.fetched_at !== "string" ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(market.fetched_at) ||
        !Number.isFinite(Date.parse(market.fetched_at)) ||
        market.source?.prices !== "https://swapwallet.app/api/v1/market/prices" ||
        market.source?.fees !== "https://mempool.space/api/v1/fees/recommended" ||
        !market.rates || ![market.rates.btc_toman, market.rates.usdt_toman, market.rates.satoshi_toman].every(positiveDecimal) ||
        market.assumptions?.exchange_fee_percent !== "0.5" ||
        market.assumptions?.operator_fee_percent !== "15" ||
        market.assumptions?.print_usd !== "0.15" || market.assumptions?.transaction_vbytes !== 141 ||
        !positiveDecimal(market.assumptions?.network_fee_rate) ||
        !integer(market.costs?.network_sats) || !integer(market.costs?.print_sats) ||
        !Array.isArray(market.rows) || market.rows.length < 1 || market.rows.length > 21) return false;
    return market.rows.every((row, index) => {
      if (!row || ![row.principal_sats, row.network_sats, row.print_sats, row.operator_sats,
          row.total_sats, row.total_toman, row.total_rial, row.remainder_toman].every(integer) ||
          row.principal_sats < 500 || row.principal_sats > 2100000000000000 || row.total_toman === 0 ||
          typeof row.btc !== "string" || !/^(?:0|[1-9][0-9]{0,7})\.[0-9]{8}$/.test(row.btc) ||
          row.network_sats !== market.costs.network_sats || row.print_sats !== market.costs.print_sats) return false;
      const [whole, fraction] = row.btc.split(".");
      if (BigInt(whole) * 100000000n + BigInt(fraction) !== BigInt(row.principal_sats) ||
          BigInt(row.principal_sats) + BigInt(row.network_sats) + BigInt(row.print_sats) + BigInt(row.operator_sats) !== BigInt(row.total_sats) ||
          BigInt(row.total_toman) * 10n !== BigInt(row.total_rial)) return false;
      if (index === 0) return row.principal_sats === 500 && row.budget_toman === null && row.remainder_toman === 0;
      return integer(row.budget_toman) && row.budget_toman >= 100000 && row.budget_toman <= 2000000 &&
        row.budget_toman % 100000 === 0 && row.total_toman <= row.budget_toman &&
        row.remainder_toman === row.budget_toman - row.total_toman &&
        (index === 1 || row.budget_toman > market.rows[index - 1].budget_toman);
    });
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function quoteRow(row, index) {
    const tr = element("tr");
    const principal = element("th");
    principal.setAttribute("scope", "row");
    principal.append(element("span", grouped(row.principal_sats), "numeric-block"));
    if (index === 0) principal.append(element("small", "حداقل بستهٔ پیشنهادی", "quote-note"));
    const btc = element("td", row.btc, "numeric-block");
    btc.dir = "ltr";
    const total = element("td");
    total.append(element("strong", grouped(row.total_toman), "numeric-block"));
    const details = element("details", undefined, "quote-details");
    const breakdown = element("dl");
    for (const [label, value] of [
      ["اصل مبلغ؛ ساتوشی", row.principal_sats], ["شبکه؛ ساتوشی", row.network_sats],
      ["چاپ؛ ساتوشی", row.print_sats], ["گرداننده؛ ساتوشی", row.operator_sats],
      ["جمع؛ ساتوشی", row.total_sats], ["معادل ریال", row.total_rial],
      ...(row.budget_toman === null ? [] : [["بودجه؛ تومان", row.budget_toman], ["باقی‌مانده؛ تومان", row.remainder_toman]])
    ]) {
      const group = element("div");
      const amount = element("dd", grouped(value), "numeric-block");
      amount.dir = "ltr";
      group.append(element("dt", label), amount);
      breakdown.append(group);
    }
    details.append(element("summary", "ریز هزینه و معادل ریال"), breakdown);
    total.append(details);
    tr.append(principal, btc, total);
    return tr;
  }

  async function loadMarket() {
    panel.setAttribute("aria-busy", "true");
    status.textContent = "در حال دریافت نرخ و برآورد از سرور سایت…";
    status.dataset.state = "loading";
    try {
      const response = await fetch("/api/market", {
        method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (!response.ok) throw new Error("Market unavailable");
      const market = await response.json();
      if (!validMarket(market)) throw new Error("Unexpected market data");
      document.getElementById("market-fetched-at").textContent = market.fetched_at;
      document.getElementById("btc-price").textContent = decimal(market.rates.btc_toman);
      document.getElementById("usdt-price").textContent = decimal(market.rates.usdt_toman);
      document.getElementById("sat-price").textContent = decimal(market.rates.satoshi_toman);
      document.getElementById("network-fee-rate").textContent = decimal(market.assumptions.network_fee_rate);
      rows.replaceChildren(...market.rows.map(quoteRow));
      stale.hidden = market.status !== "stale";
      data.hidden = false;
      status.textContent = market.status === "stale" ? "نرخ قدیمی ذخیره‌شده نمایش داده می‌شود؛ پیش از پرداخت قیمت تازه را بررسی کنید." : "برآورد با آخرین دادهٔ دریافت‌شده آماده است؛ نرخ نهایی و زمان تأیید تضمین نمی‌شود.";
      status.dataset.state = market.status === "stale" ? "stale" : "success";
    } catch {
      rows.replaceChildren();
      data.hidden = true;
      stale.hidden = true;
      status.textContent = "قیمت و برآورد فعلاً در دسترس نیست. هیچ نرخ صفر یا جایگزینی فرض نشده است؛ بعداً صفحه را بازخوانی کنید.";
      status.dataset.state = "error";
    } finally {
      panel.setAttribute("aria-busy", "false");
    }
  }

  loadMarket();
})();
