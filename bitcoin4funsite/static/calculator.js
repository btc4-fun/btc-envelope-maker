"use strict";

(() => {
  const unit = 100000000n;
  const maximum = 2100000000000000n;
  const positiveDecimal = value => typeof value === "string" && value.length <= 48 &&
    /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value) && /[1-9]/.test(value);
  const grouped = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimal = value => {
    const parts = value.split(".");
    return grouped(parts[0]) + (parts[1] ? "." + parts[1] : "");
  };
  const rational = value => {
    const [whole, fraction = ""] = value.split(".");
    return { numerator: BigInt(whole + fraction), denominator: 10n ** BigInt(fraction.length) };
  };
  const ceilDivide = (numerator, denominator) => (numerator + denominator - 1n) / denominator;
  const bitcoin = amount => {
    const fraction = (amount % unit).toString().padStart(8, "0").replace(/0+$/, "");
    return (amount / unit).toString() + (fraction ? "." + fraction : "");
  };

  let marketRequest;
  function fetchMarket() {
    if (!marketRequest) {
      marketRequest = fetch("/api/market", {
        method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
        headers: { Accept: "application/json" }
      }).then(response => {
        if (!response.ok) throw new Error("Market unavailable");
        return response.json();
      });
    }
    return marketRequest;
  }
  function validSnapshot(market) {
    return market && ["fresh", "stale"].includes(market.status) &&
      typeof market.fetched_at === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(market.fetched_at) &&
      Number.isFinite(Date.parse(market.fetched_at)) &&
      market.source?.prices === "https://swapwallet.app/api/v1/market/prices" &&
      market.source?.fees === "https://mempool.space/api/v1/fees/recommended";
  }
  // Decimal rates have power-of-ten denominators: retain every fractional digit.
  function rawValue(sats, price) {
    const rate = rational(price);
    const denominator = rate.denominator * unit;
    const numerator = sats * rate.numerator;
    const fraction = (numerator % denominator).toString()
      .padStart(denominator.toString().length - 1, "0").replace(/0+$/, "");
    return (numerator / denominator).toString() + (fraction ? "." + fraction : "");
  }

(() => {
  if (!document.getElementById("satoshi-converter")) return;
  const btc = document.getElementById("btc-amount");
  const sats = document.getElementById("satoshi-amount");
  const status = document.getElementById("converter-status");
  const grossPanel = document.getElementById("gross-valuation");
  const grossStatus = document.getElementById("gross-status");
  const grossResult = document.getElementById("gross-result");
  const grossToman = document.getElementById("gross-toman");
  let converted = null;
  let rawSnapshot = null;

  function updateGross() {
    grossResult.hidden = true;
    grossToman.textContent = "";
    if (!rawSnapshot || converted === null) return;
    grossToman.textContent = decimal(rawValue(converted, rawSnapshot.raw_rates.btc_toman));
    grossResult.hidden = false;
  }

  function convert(source, destination, fromBitcoin) {
    converted = null;
    updateGross();
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
    destination.value = fromBitcoin ? amount.toString() : bitcoin(amount);
    converted = amount;
    updateGross();
    status.textContent = "تبدیل دقیق انجام شد؛ بدون گرد کردن و بدون ارسال اطلاعات.";
    status.dataset.state = "success";
  }

  btc.addEventListener("input", () => convert(btc, sats, true));
  sats.addEventListener("input", () => convert(sats, btc, false));

  async function loadRawRate() {
    grossPanel.setAttribute("aria-busy", "true");
    grossStatus.dataset.state = "loading";
    grossStatus.textContent = "ارزش خام تومانی نیاز به نرخ آنلاین دارد؛ تبدیل بیت‌کوین و ساتوشی آفلاین می‌ماند.";
    try {
      const market = await fetchMarket();
      if (!validSnapshot(market) || !positiveDecimal(market.raw_rates?.btc_toman)) {
        throw new Error("Unexpected raw price");
      }
      rawSnapshot = market;
      document.getElementById("gross-raw-price").textContent = decimal(market.raw_rates.btc_toman);
      document.getElementById("gross-fetched-at").textContent = market.fetched_at;
      document.getElementById("gross-stale").hidden = market.status !== "stale";
      grossStatus.dataset.state = market.status === "stale" ? "stale" : "success";
      grossStatus.textContent = market.status === "stale"
        ? "ارزش خام با نرخ قدیمی ذخیره‌شده؛ این نرخ آنلاینِ تازه نیست."
        : "نرخ آنلاین خام دریافت شد؛ زمان دریافت را ببینید. این ارزش، جمع پرداختی پاکت نیست.";
      updateGross();
    } catch {
      rawSnapshot = null;
      updateGross();
      grossStatus.dataset.state = "error";
      grossStatus.textContent = "نرخ آنلاین در دسترس نیست؛ ارزش تومانی نمایش داده نمی‌شود. تبدیل بیت‌کوین و ساتوشی همچنان آفلاین کار می‌کند.";
    } finally {
      grossPanel.setAttribute("aria-busy", "false");
    }
  }
  loadRawRate();
})();

(() => {
  const panel = document.getElementById("market-panel");
  if (!panel) return;
  const status = document.getElementById("market-status");
  const data = document.getElementById("market-data");
  const stale = document.getElementById("market-stale");
  const rows = document.getElementById("quote-rows");
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const form = document.getElementById("quote-form");
  const amount = document.getElementById("quote-amount");
  const mode = document.getElementById("quote-mode");
  const calculate = document.getElementById("quote-calculate");
  const quoteStatus = document.getElementById("quote-status");
  const result = document.getElementById("quote-result");
  let snapshot = null;

  function quote(principal) {
    const network = BigInt(snapshot.costs.network_sats);
    const print = BigInt(snapshot.costs.print_sats);
    const operator = ceilDivide((principal + network + print) * 15n, 100n);
    const total = principal + network + print + operator;
    const rate = rational(snapshot.rates.satoshi_toman);
    const toman = ceilDivide(total * rate.numerator, rate.denominator);
    return { principal, network, print, operator, "total-sats": total,
      "total-toman": toman, "total-rial": toman * 10n };
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    clearResult();
    amount.removeAttribute("aria-invalid");
    if (!snapshot) return;
    if (!["principal_sats", "budget_toman"].includes(mode.value) ||
        amount.value.length > 32 || !/^[1-9][0-9]*$/.test(amount.value)) {
      reject("مقدار معتبر نیست؛ فقط عدد صحیح مثبت با ارقام انگلیسی، بدون فاصله، جداکننده یا صفر ابتدایی و حداکثر سی‌ودو رقم وارد کنید.");
      return;
    }
    let budget = null;
    let principal = BigInt(amount.value);
    if (mode.value === "principal_sats" && (principal < 500n || principal > maximum)) {
      reject("اصل مبلغ باید از پانصد ساتوشی تا سقف بیست‌ویک میلیون بیت‌کوین باشد.");
      return;
    }
    if (mode.value === "budget_toman") {
      budget = principal;
      if (quote(500n)["total-toman"] > budget) {
        reject("بودجه برای حداقل اصل مبلغ و همهٔ هزینه‌ها کافی نیست؛ بودجه را افزایش دهید.");
        return;
      }
      // Upper-bound search also handles flat price steps and the supply cap.
      let low = 500n;
      let high = maximum;
      while (low < high) {
        const middle = (low + high + 1n) / 2n;
        if (quote(middle)["total-toman"] <= budget) low = middle;
        else high = middle - 1n;
      }
      principal = low;
    }
    const values = quote(principal);
    for (const [name, value] of Object.entries(values)) {
      document.getElementById("quote-" + name).textContent = grouped(value);
    }
    document.getElementById("quote-btc").textContent = bitcoin(values.principal);
    document.getElementById("quote-budget-details").hidden = budget === null;
    document.getElementById("quote-budget").textContent = budget === null ? "" : grouped(budget);
    document.getElementById("quote-remainder").textContent = budget === null ? "" : grouped(budget - values["total-toman"]);
    result.hidden = false;
    const warning = snapshot.status === "stale"
      ? "برآورد با نرخ قدیمی ذخیره‌شده؛ پیش از پرداخت نرخ تازه را بررسی کنید."
      : "برآورد با دادهٔ دریافت‌شده؛ نرخ و پرداخت نهایی تضمین نمی‌شوند.";
    document.getElementById("quote-result-warning").textContent = warning;
    document.getElementById("quote-result-fetched-at").textContent = snapshot.fetched_at;
    quoteStatus.dataset.state = snapshot.status === "stale" ? "stale" : "success";
    quoteStatus.textContent = warning + " ورودی ارسال نشد.";
  });

  function clearResult() {
    result.hidden = true;
    for (const name of ["principal", "btc", "network", "print", "operator", "total-sats", "total-toman",
      "total-rial", "budget", "remainder", "result-warning", "result-fetched-at"]) {
      document.getElementById("quote-" + name).textContent = "";
    }
    document.getElementById("quote-budget-details").hidden = true;
  }
  function reject(message) {
    amount.setAttribute("aria-invalid", "true");
    quoteStatus.textContent = message;
    quoteStatus.dataset.state = "error";
  }
  const invalidate = () => {
    clearResult();
    amount.removeAttribute("aria-invalid");
    if (!snapshot) return;
    quoteStatus.textContent = snapshot.status === "stale"
      ? "نرخ قدیمی ذخیره‌شده است؛ محاسبه فقط برآورد قدیمی می‌دهد."
      : "برای مقدار و واحد انتخاب‌شده، محاسبه را بزنید.";
    quoteStatus.dataset.state = snapshot.status === "stale" ? "stale" : "ready";
  };
  amount.addEventListener("input", invalidate);
  mode.addEventListener("change", invalidate);

  function validMarket(market) {
    if (!validSnapshot(market) ||
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
        BigInt(row.budget_toman) % 100000n === 0n && row.total_toman <= row.budget_toman &&
        BigInt(row.remainder_toman) === BigInt(row.budget_toman) - BigInt(row.total_toman) &&
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
    calculate.disabled = true;
    quoteStatus.dataset.state = "loading";
    quoteStatus.textContent = "محاسبه پس از دریافت نرخ از سرور همین سایت آماده می‌شود…";
    status.textContent = "در حال دریافت نرخ و برآورد از سرور سایت…";
    status.dataset.state = "loading";
    try {
      const market = await fetchMarket();
      if (!validMarket(market)) throw new Error("Unexpected market data");
      snapshot = market;
      calculate.disabled = false;
      quoteStatus.dataset.state = market.status === "stale" ? "stale" : "ready";
      quoteStatus.textContent = market.status === "stale"
        ? "فقط نرخ قدیمی ذخیره‌شده آماده است؛ محاسبه برآورد قدیمی می‌دهد."
        : "داده آماده است؛ مقدار را وارد و محاسبه را انتخاب کنید.";
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
      snapshot = null;
      calculate.disabled = true;
      clearResult();
      quoteStatus.dataset.state = "error";
      quoteStatus.textContent = "نرخ در دسترس نیست؛ محاسبهٔ هزینه ممکن نیست. هیچ نرخ صفر یا جایگزین فرض نشده است.";
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
})();
