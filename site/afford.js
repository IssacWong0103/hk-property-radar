/* HK Property Radar — affordability engine.

   Everything here runs in the browser and stays in the browser: age, income and
   savings are never sent anywhere and never leave localStorage. That is
   deliberate — this is the one screen holding personal financial data.

   Rules encoded below are dated. Check them against the source before trusting
   a number to a real purchase; see RULES.asOf and the links in the UI. */
'use strict';

/* ---------- statutory / regulatory constants ----------
   AVD Scale 2, residential property, instruments executed on or after
   26 Feb 2026. Source: GovHK stamp duty rate table.
   Bands are "exceeds prev, does not exceed upTo" — upTo is inclusive.
   Rows with `marginalRate` are the marginal-relief steps that bridge each
   flat-rate band (they cap the duty jump at the band edge). */
const AVD_BANDS = [
  {upTo:      4000000, flat:100},
  {upTo:      4323780, base:     100, over:      4000000, marginalRate:0.20},
  {upTo:      4500000, rate:0.0150},
  {upTo:      4935480, base:   67500, over:      4500000, marginalRate:0.10},
  {upTo:      6000000, rate:0.0225},
  {upTo:      6642860, base:  135000, over:      6000000, marginalRate:0.10},
  {upTo:      9000000, rate:0.0300},
  {upTo:     10080000, base:  270000, over:      9000000, marginalRate:0.10},
  {upTo:     20000000, rate:0.0375},
  {upTo:     21739120, base:  750000, over:     20000000, marginalRate:0.10},
  {upTo:    100000000, rate:0.0425},
  {upTo:    109574468, base: 4250000, over:    100000000, marginalRate:0.30},
  {upTo:     Infinity, rate:0.0650},
];

const RULES = {
  asOf: 'July 2026',
  ltvCap: 0.70,          // HKMA flat cap, all residential, since 16 Oct 2024
  dsrLocal: 0.50,        // debt servicing ratio cap, income sourced in HK
  dsrOverseas: 0.40,     // banks routinely tighten where income is earned abroad
  tenorMaxYears: 30,     // HKMA maximum
  ageRule: 75,           // banks size tenor as (ageRule − age), capped at tenorMaxYears
  agencyPct: 0.01,       // standard HK agency commission
  legalFee: 15000,       // solicitor, typical range 10k–20k
  hiborSpread: 0.013,    // typical H+ mortgage spread
  fallbackRate: 0.0375,  // used if HIBOR unavailable
  mgmtPerSqftMonth: 3.5, // management fee, varies widely by estate
  ratesPct: 0.05,        // Government rates: 5% of rateable value per year
  // Pre-28-Feb-2024, a non-permanent resident also paid BSD 15% + AVD Scale 1
  // flat 15%. Both were abolished; kept here only to show the delta.
  legacyNonPrSurcharge: 0.30,
};

/* ---------- money maths ---------- */

/** Ad valorem stamp duty on a residential purchase, Scale 2. */
function avd(price){
  if (!(price > 0)) return 0;
  for (const b of AVD_BANDS){
    if (price <= b.upTo){
      if (b.flat != null) return b.flat;
      if (b.marginalRate != null) return Math.ceil(b.base + (price - b.over) * b.marginalRate);
      return Math.ceil(price * b.rate);
    }
  }
  return 0;
}

/** Level monthly repayment on an annuity mortgage. */
function pmt(principal, annualRate, months){
  if (months <= 0) return 0;
  const r = annualRate / 12;
  if (r === 0) return principal / months;
  return principal * r / (1 - Math.pow(1 + r, -months));
}

/** Largest loan whose monthly repayment does not exceed `payment`. */
function loanFromPayment(payment, annualRate, months){
  if (payment <= 0 || months <= 0) return 0;
  const r = annualRate / 12;
  if (r === 0) return payment * months;
  return payment * (1 - Math.pow(1 + r, -months)) / r;
}

/** Bank tenor: (75 − age), capped at the 30-year regulatory maximum. */
function tenorYears(age){
  return Math.max(0, Math.min(RULES.tenorMaxYears, RULES.ageRule - age));
}

/** Total cash needed at completion for a given purchase price. */
function cashToClose(price, ltv){
  const deposit = price * (1 - ltv);
  const duty    = avd(price);
  const agency  = price * RULES.agencyPct;
  return {
    deposit, duty, agency, legal: RULES.legalFee,
    total: deposit + duty + agency + RULES.legalFee,
  };
}

/** Highest price whose cash-to-close fits the savings available. Binary search
    because stamp duty is piecewise, so there is no clean closed form. */
function priceFromCash(cash, ltv){
  if (cash <= 0) return 0;
  let lo = 0, hi = 500e6;
  for (let i = 0; i < 60; i++){
    const mid = (lo + hi) / 2;
    if (cashToClose(mid, ltv).total <= cash) lo = mid; else hi = mid;
  }
  return lo;
}

/**
 * Core calculation. Returns both binding constraints so the UI can say *why*
 * the ceiling is where it is — that is the part buyers actually act on.
 */
function calc(input){
  const {age, income, otherDebt, cash, overseasIncome, rate, sizeSqft} = input;

  const years  = tenorYears(age);
  const months = years * 12;
  const dsr    = overseasIncome ? RULES.dsrOverseas : RULES.dsrLocal;
  const ltv    = RULES.ltvCap;

  // Income route
  const maxPayment    = Math.max(0, income * dsr - otherDebt);
  const maxLoan       = loanFromPayment(maxPayment, rate, months);
  const priceByIncome = ltv > 0 ? maxLoan / ltv : 0;

  // Cash route
  const priceByCash = priceFromCash(cash, ltv);

  const maxPrice = Math.min(priceByIncome, priceByCash);
  const bindingConstraint = priceByIncome <= priceByCash ? 'income' : 'cash';

  const loan    = maxPrice * ltv;
  const payment = pmt(loan, rate, months);
  const costs   = cashToClose(maxPrice, ltv);

  // Recurring monthly outgoings beyond the mortgage
  const mgmt        = (sizeSqft || 0) * RULES.mgmtPerSqftMonth;
  const rateableEst = maxPrice * 0.032;                      // ≈ annual rental value
  const govRates    = rateableEst * RULES.ratesPct / 12;
  const monthlyTotal = payment + mgmt + govRates;

  // What the age rule costs. It bites in one of two ways depending on which
  // constraint binds: if income binds, a short tenor shrinks the ceiling; if
  // cash binds, the ceiling is unchanged but every month costs more. Report
  // both so the cost never silently disappears.
  const fullMonths     = RULES.tenorMaxYears * 12;
  const loanIfYoung    = loanFromPayment(maxPayment, rate, fullMonths);
  const priceIfYoung   = Math.min(ltv > 0 ? loanIfYoung / ltv : 0, priceByCash);
  const agePenalty     = Math.max(0, priceIfYoung - maxPrice);
  const paymentIfYoung = pmt(loan, rate, fullMonths);
  const paymentPenalty = Math.max(0, payment - paymentIfYoung);
  const shortTenor     = years < RULES.tenorMaxYears;

  // What abolition of BSD/NRSD saved a non-permanent resident
  const legacyExtra = maxPrice * RULES.legacyNonPrSurcharge;

  return {
    years, months, dsr, ltv, rate,
    maxPayment, maxLoan, priceByIncome, priceByCash,
    maxPrice, bindingConstraint, loan, payment, costs,
    mgmt, govRates, monthlyTotal,
    priceIfYoung, agePenalty, paymentIfYoung, paymentPenalty, shortTenor, legacyExtra,
    sizeSqft,
  };
}

/* ---------- formatting ---------- */
const hkd = n => {
  if (n == null || Number.isNaN(n)) return '—';
  if (Math.abs(n) >= 1e6) return 'HK$' + (n / 1e6).toLocaleString('en-US', {maximumFractionDigits: 2}) + 'M';
  return 'HK$' + Math.round(n).toLocaleString('en-US');
};
const hkd0 = n => (n == null || Number.isNaN(n)) ? '—'
  : 'HK$' + Math.round(n).toLocaleString('en-US');
const pct = n => (n * 100).toLocaleString('en-US', {maximumFractionDigits: 2}) + '%';

/* ---------- inputs ---------- */
const FIELDS = ['afAge','afIncome','afDebt','afCash','afSize','afRate','afOverseas'];

function readInputs(){
  const num = id => {
    const v = parseFloat(String(document.getElementById(id).value).replace(/,/g, ''));
    return Number.isFinite(v) ? v : 0;
  };
  return {
    age:            num('afAge'),
    income:         num('afIncome'),
    otherDebt:      num('afDebt'),
    cash:           num('afCash'),
    sizeSqft:       num('afSize'),
    rate:           num('afRate') / 100,
    overseasIncome: document.getElementById('afOverseas').checked,
  };
}

function saveInputs(){
  const store = {};
  FIELDS.forEach(id => {
    const el = document.getElementById(id);
    store[id] = el.type === 'checkbox' ? el.checked : el.value;
  });
  localStorage.setItem('hkpr-afford', JSON.stringify(store));
}

function restoreInputs(){
  let store = {};
  try { store = JSON.parse(localStorage.getItem('hkpr-afford') || '{}'); } catch (_) {}
  FIELDS.forEach(id => {
    if (store[id] === undefined) return;
    const el = document.getElementById(id);
    if (el.type === 'checkbox') el.checked = store[id]; else el.value = store[id];
  });
  return Object.keys(store).length > 0;
}

/** Pre-fill the mortgage rate from the live HIBOR series already on the page. */
function seedRate(){
  const el = document.getElementById('afRate');
  if (el.value) return;
  const h = window.state && window.state.macro && window.state.macro.hibor;
  const latest = h && h.values && h.values.filter(v => v != null).at(-1);
  const r = latest != null ? (latest / 100 + RULES.hiborSpread) : RULES.fallbackRate;
  el.value = (r * 100).toFixed(2);
}

/* ---------- render ---------- */

function renderHeadline(r){
  const el = document.getElementById('afHeadline');
  if (!(r.maxPrice > 0)){
    el.innerHTML = '<div class="empty">Enter your age, income and savings above to see your ceiling.</div>';
    return;
  }
  const why = r.bindingConstraint === 'income'
    ? `Your <strong>income</strong> is the limit — the bank caps repayments at ${pct(r.dsr)} of monthly income.`
    : `Your <strong>cash</strong> is the limit — you need ${pct(1 - r.ltv)} deposit plus stamp duty and fees up front.`;
  el.innerHTML = `
    <div class="af-big">
      <div class="af-big-label">You can buy up to</div>
      <div class="af-big-value">${hkd(r.maxPrice)}</div>
      <div class="af-big-sub">${why}</div>
    </div>
    <div class="af-facts">
      <div class="af-fact"><span>Mortgage</span><strong>${hkd(r.loan)}</strong><small>${pct(r.ltv)} loan-to-value</small></div>
      <div class="af-fact"><span>Monthly repayment</span><strong>${hkd0(r.payment)}</strong><small>over ${r.years} years at ${pct(r.rate)}</small></div>
      <div class="af-fact"><span>Cash needed to complete</span><strong>${hkd(r.costs.total)}</strong><small>deposit + duty + fees</small></div>
      <div class="af-fact"><span>Total monthly cost</span><strong>${hkd0(r.monthlyTotal)}</strong><small>incl. management &amp; rates</small></div>
    </div>`;
}

function renderCash(r){
  const rows = [
    ['Deposit', r.costs.deposit, `${pct(1 - r.ltv)} of price — the regulatory maximum loan is ${pct(r.ltv)}`],
    ['Stamp duty (AVD Scale 2)', r.costs.duty, 'Same rate a local buyer pays'],
    ['Agency commission', r.costs.agency, 'Typically 1%, negotiable'],
    ['Solicitor', r.costs.legal, 'Typical range HK$10,000–20,000'],
  ];
  document.getElementById('afCashTable').innerHTML =
    `<thead><tr><th>Item</th><th>Amount</th></tr></thead><tbody>` +
    rows.map(([k, v, note]) =>
      `<tr><td>${k}<div class="af-note">${note}</div></td><td>${hkd0(v)}</td></tr>`).join('') +
    `<tr class="af-total"><td>Cash to complete</td><td>${hkd0(r.costs.total)}</td></tr></tbody>`;
}

function renderMonthly(r){
  const rows = [
    ['Mortgage repayment', r.payment, `${r.years}-year tenor at ${pct(r.rate)}`],
    ['Management fee', r.mgmt, `Estimated at HK$${RULES.mgmtPerSqftMonth}/sq.ft on ${r.sizeSqft || 0} sq.ft`],
    ['Government rates', r.govRates, '5% of rateable value — estimated'],
  ];
  document.getElementById('afMonthlyTable').innerHTML =
    `<thead><tr><th>Item</th><th>Per month</th></tr></thead><tbody>` +
    rows.map(([k, v, note]) =>
      `<tr><td>${k}<div class="af-note">${note}</div></td><td>${hkd0(v)}</td></tr>`).join('') +
    `<tr class="af-total"><td>Total per month</td><td>${hkd0(r.monthlyTotal)}</td></tr></tbody>`;
}

function renderInsights(r){
  const el = document.getElementById('afInsights');
  if (!(r.maxPrice > 0)) { el.innerHTML = ''; return; }
  const cards = [];

  if (r.shortTenor){
    // The penalty surfaces as lost buying power (income-bound) or a higher
    // monthly bill (cash-bound). Lead with whichever actually applies.
    const detail = r.agePenalty > 0
      ? `<p class="af-delta">A 30-year tenor on the same income would reach
         <strong>${hkd(r.priceIfYoung)}</strong> — about <strong>${hkd(r.agePenalty)}</strong> more
         buying power. This is the single biggest constraint on your budget, and no generic
         mortgage calculator shows it.</p>`
      : `<p class="af-delta">Your ceiling here is set by cash, not tenor — but the shorter term
         still raises the repayment. On this ${hkd(r.loan)} mortgage you pay about
         <strong>${hkd0(r.paymentPenalty)}/month more</strong> than a 30-year borrower
         (${hkd0(r.payment)} vs ${hkd0(r.paymentIfYoung)}).</p>`;
    cards.push(`
      <div class="af-insight warn">
        <h3>Your age shortens the mortgage</h3>
        <p>Banks size the tenor as <strong>75 minus your age</strong>, capped at 30 years. At
        ${r.age || 'your age'} that is <strong>${r.years} years</strong>, not 30.</p>
        ${detail}
      </div>`);
  }

  cards.push(`
    <div class="af-insight good">
      <h3>You no longer pay the foreign-buyer surcharge</h3>
      <p>Buyer's Stamp Duty and New Residential Stamp Duty were abolished on
      <strong>28 February 2024</strong>. A non-permanent resident now pays the same
      Scale 2 rate as a local buyer.</p>
      <p class="af-delta">On a ${hkd(r.maxPrice)} flat you would previously have paid roughly
      <strong>${hkd(r.legacyExtra)}</strong> in additional duty on top. That surcharge is gone.
      <span class="af-caveat">Both duties are suspended rather than repealed — the Government
      can reinstate them.</span></p>
    </div>`);

  if (r.dsr === RULES.dsrOverseas){
    cards.push(`
      <div class="af-insight warn">
        <h3>Income earned outside Hong Kong is treated more strictly</h3>
        <p>Banks generally cut the debt-servicing allowance to about ${pct(RULES.dsrOverseas)} of income
        (from ${pct(RULES.dsrLocal)}) and may ask for more documentation. Your ceiling above already
        reflects this. Confirm the exact treatment with your bank — policies differ.</p>
      </div>`);
  }

  el.innerHTML = cards.join('');
}

/** Bridges affordability into the district data already loaded. */
function renderReach(r){
  const el = document.getElementById('afReach');
  const d  = window.state && window.state.districts;
  const size = r.sizeSqft;
  if (!d || !d.by_district || !(r.maxPrice > 0) || !(size > 0)){
    el.innerHTML = '<div class="empty">Set a target flat size to see which districts are within reach.</div>';
    return;
  }
  const rows = d.by_district
    .filter(x => x.avg_psf != null)
    .map(x => ({...x, typical: x.avg_psf * size}))
    .sort((a, b) => a.typical - b.typical);

  const within = rows.filter(x => x.typical <= r.maxPrice);
  const pillCls = {'HK Island':'r1','Kowloon':'r2','New Territories':'r3'};

  document.getElementById('afReachSub').textContent =
    `${within.length} of ${rows.length} districts · ${size} sq.ft`;

  el.innerHTML =
    `<thead><tr><th>District</th><th>Region</th><th>Typical ${size} sq.ft flat</th><th>Deals</th><th></th></tr></thead><tbody>` +
    rows.map(x => `
      <tr class="${x.typical <= r.maxPrice ? '' : 'af-out'}">
        <td>${x.district}</td>
        <td><span class="pill ${pillCls[x.region] || ''}">${x.region || '—'}</span></td>
        <td>${hkd(x.typical)}</td>
        <td>${x.units == null ? '—' : Math.round(x.units).toLocaleString('en-US')}</td>
        <td>${x.typical <= r.maxPrice
              ? '<span class="af-tag in">within budget</span>'
              : '<span class="af-tag out">over</span>'}</td>
      </tr>`).join('') + '</tbody>';
}

function drawAfford(){
  seedRate();
  const input = readInputs();
  const r = calc(input);
  r.age = input.age;
  renderHeadline(r);
  renderCash(r);
  renderMonthly(r);
  renderInsights(r);
  renderReach(r);
  saveInputs();
}

function initAfford(){
  restoreInputs();
  FIELDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input',  drawAfford);
    el.addEventListener('change', drawAfford);
  });
  const reset = document.getElementById('afReset');
  if (reset) reset.onclick = () => {
    localStorage.removeItem('hkpr-afford');
    FIELDS.forEach(id => {
      const el = document.getElementById(id);
      if (el.type === 'checkbox') el.checked = false; else el.value = '';
    });
    drawAfford();
  };
}

/** Current affordability picture for other tabs (e.g. the estate drill-down) to
    tint by budget. Returns null until enough has been entered to compute a ceiling. */
function snapshot(){
  const input = readInputs();
  if (!(input.income > 0) && !(input.cash > 0)) return null;
  const r = calc(input);
  return r.maxPrice > 0 ? {maxPrice: r.maxPrice, sizeSqft: input.sizeSqft} : null;
}

window.HKAfford = {drawAfford, initAfford, calc, avd, pmt, tenorYears, snapshot, RULES};
