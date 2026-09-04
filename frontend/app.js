const API_BASE = window.location.hostname === "" || window.location.protocol === "file:"
  ? "http://127.0.0.1:8000/api"
  : `${window.location.protocol}//${window.location.hostname}:8000/api`;

const TOKEN_KEY = "smartwatch-token";
const USERNAME_KEY = "smartwatch-username";
const MARKET_KEY = "smartwatch-market";
const THEME_KEY = "smartwatch-theme";

// ---- Theme toggle (data-theme applied pre-paint by an inline script in <head>) ----

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  const lightBtn = document.getElementById("theme-light-btn");
  const darkBtn = document.getElementById("theme-dark-btn");
  if (lightBtn) lightBtn.classList.toggle("active", theme === "light");
  if (darkBtn) darkBtn.classList.toggle("active", theme === "dark");
}

applyTheme(document.documentElement.getAttribute("data-theme") || "light");

function selectTheme(theme) {
  applyTheme(theme);
  // Canvas charts bake theme colors into their pixels at draw time, so they
  // don't update on their own when CSS variables change - force a redraw.
  if (lastHoldings.length > 0) {
    renderAllocation(lastHoldings);
    renderPnlChart(lastHoldings);
  }
}

document.getElementById("theme-light-btn").addEventListener("click", () => selectTheme("light"));
document.getElementById("theme-dark-btn").addEventListener("click", () => selectTheme("dark"));

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
function setSession(token, username) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USERNAME_KEY, username);
}
function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USERNAME_KEY);
}

const els = {
  authView: document.getElementById("auth-view"),
  authForm: document.getElementById("auth-form"),
  authUsername: document.getElementById("auth-username"),
  authPassword: document.getElementById("auth-password"),
  authSubmit: document.getElementById("auth-submit"),
  authError: document.getElementById("auth-error"),
  authTabs: document.querySelectorAll(".auth-tab"),

  appView: document.getElementById("app-view"),
  exchangeTabs: document.querySelectorAll(".exchange-tab"),
  navTabs: document.querySelectorAll(".nav-tab"),
  usernameDisplay: document.getElementById("username-display"),
  logoutBtn: document.getElementById("logout-btn"),

  portfolioView: document.getElementById("portfolio-view"),
  portfolioStatsBar: document.getElementById("portfolio-stats-bar"),
  holdingForm: document.getElementById("holding-form"),
  holdingSymbol: document.getElementById("holding-symbol"),
  holdingQty: document.getElementById("holding-qty"),
  holdingPrice: document.getElementById("holding-price"),
  portfolioError: document.getElementById("portfolio-error"),
  portfolioEmptyState: document.getElementById("portfolio-empty-state"),
  portfolioHoldings: document.getElementById("portfolio-holdings"),
  exportCsvBtn: document.getElementById("export-csv-btn"),
  allocationSection: document.getElementById("allocation-section"),
  allocationChart: document.getElementById("allocation-chart"),
  allocationLegend: document.getElementById("allocation-legend"),
  pnlSection: document.getElementById("pnl-section"),
  pnlChart: document.getElementById("pnl-chart"),
  pnlSummary: document.getElementById("pnl-summary"),

  watchlistView: document.getElementById("watchlist-view"),
  form: document.getElementById("add-form"),
  input: document.getElementById("symbol-input"),
  error: document.getElementById("error-banner"),
  sensitivitySelect: document.getElementById("sensitivity-select"),
  recommendations: document.getElementById("recommendations"),
  recommendationsGrid: document.getElementById("recommendations-grid"),
  emptyState: document.getElementById("empty-state"),
  emptyStateText: document.getElementById("empty-state-text"),
  groups: document.getElementById("groups"),
  statsBar: document.getElementById("stats-bar"),
  status: document.getElementById("status-line"),
  clock: document.getElementById("clock"),
  marketStatus: document.getElementById("market-status"),

  modal: document.getElementById("detail-modal"),
  modalBackdrop: document.getElementById("modal-backdrop"),
  modalClose: document.getElementById("modal-close"),
  modalSymbol: document.getElementById("modal-symbol"),
  modalLevelBadge: document.getElementById("modal-level-badge"),
  modalPriceRow: document.getElementById("modal-price-row"),
  modalChart: document.getElementById("modal-chart"),
  breakdownSection: document.getElementById("breakdown-section"),
  breakdownBars: document.getElementById("breakdown-bars"),
  modalStats: document.getElementById("modal-stats"),
};

let lastEntries = [];
let lastHoldings = [];
let currentView = "portfolio";
let currentMarket = localStorage.getItem(MARKET_KEY) || "US";
let pollTimer = null;

function marketQuery() {
  return `market=${encodeURIComponent(currentMarket)}`;
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    clearSession();
    showAuthView();
    throw new Error("Session expired - please log in again");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function fmtPct(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}
function currencySymbol(currency) {
  return currency === "INR" ? "\u20B9" : "$";
}
function fmtMoney(value, currency = "USD") {
  const sign = value < 0 ? "-" : "";
  return `${sign}${currencySymbol(currency)}${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ---- Auth ----

let authMode = "login";

els.authTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    authMode = tab.dataset.mode;
    els.authTabs.forEach((t) => t.classList.toggle("active", t === tab));
    els.authSubmit.textContent = authMode === "login" ? "Log in" : "Sign up";
    els.authPassword.autocomplete = authMode === "login" ? "current-password" : "new-password";
    els.authError.hidden = true;
  });
});

els.authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = els.authUsername.value.trim();
  const password = els.authPassword.value;
  els.authError.hidden = true;
  try {
    const path = authMode === "login" ? "/auth/login" : "/auth/register";
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || "Something went wrong");
    setSession(body.token, body.username);
    showAppView();
  } catch (err) {
    els.authError.textContent = err.message;
    els.authError.hidden = false;
  }
});

els.logoutBtn.addEventListener("click", async () => {
  try {
    await fetch(`${API_BASE}/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${getToken()}` } });
  } catch (_) {
    // best-effort - log out locally regardless of network state
  }
  clearSession();
  showAuthView();
});

function showAuthView() {
  if (pollTimer) clearInterval(pollTimer);
  els.appView.hidden = true;
  els.authView.hidden = false;
  els.authPassword.value = "";
}

function showAppView() {
  els.authView.hidden = true;
  els.appView.hidden = false;
  els.usernameDisplay.textContent = localStorage.getItem(USERNAME_KEY) || "";
  els.exchangeTabs.forEach((t) => t.classList.toggle("active", t.dataset.market === currentMarket));
  switchView(currentView);
  startClock();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => switchView(currentView, true), 20000);
}

// ---- Exchange toggle (US / India) - each market has its own watchlist,
// portfolio, and recommendations, kept separate at the database level ----

els.exchangeTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.dataset.market === currentMarket) return;
    currentMarket = tab.dataset.market;
    localStorage.setItem(MARKET_KEY, currentMarket);
    els.exchangeTabs.forEach((t) => t.classList.toggle("active", t === tab));
    // Clear market-scoped content immediately so a still-in-flight request
    // for the previous market can never flash its data under the new one.
    els.groups.innerHTML = "";
    els.recommendations.hidden = true;
    els.recommendationsGrid.innerHTML = "";
    els.portfolioHoldings.innerHTML = "";
    els.allocationSection.hidden = true;
    els.pnlSection.hidden = true;
    switchView(currentView);
  });
});

// ---- Nav tabs (Portfolio / Watchlist) ----

els.navTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

function switchView(view, silent = false) {
  currentView = view;
  els.navTabs.forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  els.portfolioView.hidden = view !== "portfolio";
  els.watchlistView.hidden = view !== "watchlist";
  if (view === "portfolio") loadPortfolio(silent);
  else {
    if (!silent) loadPreferences();
    loadWatchlist(silent);
  }
}

// ---- Preferences: what counts as "meaningful" is user-tunable, not fixed ----

async function loadPreferences() {
  try {
    const data = await api("/preferences");
    els.sensitivitySelect.value = data.sensitivity;
  } catch (err) {
    // non-critical - the select just keeps its default if this fails
  }
}

els.sensitivitySelect.addEventListener("change", async () => {
  try {
    await api("/preferences", { method: "POST", body: JSON.stringify({ sensitivity: els.sensitivitySelect.value }) });
    loadWatchlist();
  } catch (err) {
    els.error.textContent = err.message;
    els.error.hidden = false;
  }
});

function tickClock() {
  els.clock.textContent = new Date().toLocaleTimeString();
  setTimeout(tickClock, 1000);
}
let clockStarted = false;
function startClock() {
  if (clockStarted) return;
  clockStarted = true;
  tickClock();
}

// ---- Sparkline chart (canvas, no external chart library) ----

function drawSparkline(canvas, history, positive) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const points = history && history.length >= 2 ? history : [history?.[0] ?? 0, history?.[0] ?? 0];
  const min = Math.min(...points);
  const max = Math.max(...points);
  const flat = max === min;
  const range = max - min || 1;
  const stepX = w / (points.length - 1);

  ctx.beginPath();
  points.forEach((price, i) => {
    const x = i * stepX;
    // With no real variation yet (e.g. only one sample so far), draw a flat
    // line through the vertical center instead of pinning to the bottom.
    const y = flat ? h / 2 : h - ((price - min) / range) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = positive ? "#3fb950" : "#f85149";
  ctx.lineWidth = 2;
  ctx.stroke();
}

// ---- Watchlist: cards grouped by attention level ----
// Two groups only: "Needs attention" (high) and "Watching" (medium + low
// merged) - every tracked stock is shown somewhere, nothing is hidden.
// Each card still carries its own true level badge (high/medium/low).

const DISPLAY_GROUPS = [
  { dot: "high", title: "Needs attention", levels: ["high"] },
  { dot: "medium", title: "Watching", levels: ["medium", "low"] },
];

function sinceLastPill(change_since_last_check, is_new) {
  if (is_new) return '<span class="badge new">new</span>';
  if (change_since_last_check === null) return "";
  const cls = change_since_last_check > 0.01 ? "up" : change_since_last_check < -0.01 ? "down" : "flat";
  const arrow = cls === "up" ? "\u25B2" : cls === "down" ? "\u25BC" : "\u2013";
  return `<span class="since-pill ${cls}" title="Change since your last visit">${arrow} ${fmtPct(change_since_last_check)} since last check</span>`;
}

function renderCard(entry) {
  const { symbol, quote, score, level, change_since_last_check, is_new } = entry;
  const pctClass = quote.pct_change >= 0 ? "positive" : "negative";

  const badges = [];
  if (quote.stale) badges.push('<span class="badge stale" title="Live data unavailable; showing last known value">stale</span>');
  if (quote.source === "simulated") badges.push('<span class="badge simulated" title="Real market data unreachable; showing simulated data">simulated</span>');

  const div = document.createElement("div");
  div.className = `card level-${level}`;
  div.innerHTML = `
    <div class="card-top">
      <div class="symbol">${symbol}</div>
      <span class="level-badge ${level}">${level}</span>
    </div>
    <div class="price-row">
      <span class="price">${currencySymbol(quote.currency)}${quote.price.toFixed(2)}</span>
      <span class="pct ${pctClass}">${fmtPct(quote.pct_change)}</span>
    </div>
    <canvas class="sparkline" width="200" height="36"></canvas>
    <div class="meta">score ${score.toFixed(2)} ${badges.join("")}</div>
    <div class="meta">${sinceLastPill(change_since_last_check, is_new)}</div>
    <div class="card-actions">
      <button class="remove-btn" data-symbol="${symbol}">Remove</button>
    </div>
  `;
  drawSparkline(div.querySelector("canvas"), quote.history, quote.pct_change >= 0);
  div.querySelector(".remove-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    removeSymbol(symbol);
  });
  div.addEventListener("click", () => openWatchlistDetail(symbol));
  return div;
}

function renderGroups(items) {
  els.groups.innerHTML = "";
  DISPLAY_GROUPS.forEach(({ dot, title, levels }) => {
    const group = items.filter((e) => levels.includes(e.level));
    if (group.length === 0) return;

    const section = document.createElement("section");
    section.className = "group";
    section.innerHTML = `<h2 class="group-title"><span class="group-dot ${dot}"></span>${title} (${group.length})</h2>`;
    const grid = document.createElement("div");
    grid.className = "card-grid";
    group.forEach((entry) => grid.appendChild(renderCard(entry)));
    section.appendChild(grid);
    els.groups.appendChild(section);
  });
}

function renderStatsBar(items) {
  const total = items.length;
  const gainers = items.filter((e) => e.quote.pct_change > 0).length;
  const losers = items.filter((e) => e.quote.pct_change < 0).length;
  const needsAttention = items.filter((e) => e.level === "high").length;
  const avgScore = total ? items.reduce((sum, e) => sum + e.score, 0) / total : 0;

  const stats = [
    { label: "Tracked", value: total, cls: "" },
    { label: "Gainers", value: gainers, cls: "green" },
    { label: "Losers", value: losers, cls: "red" },
    { label: "Needs attention", value: needsAttention, cls: needsAttention ? "amber" : "" },
    { label: "Avg score", value: avgScore.toFixed(2), cls: "" },
  ];
  els.statsBar.innerHTML = stats
    .map((s) => `<div class="stat-card ${s.cls}"><div class="stat-label">${s.label}</div><div class="stat-value ${s.cls}">${s.value}</div></div>`)
    .join("");
}

function updateMarketStatus(items) {
  const anyLive = items.some((e) => e.quote.source === "live");
  const anyDegraded = items.some((e) => e.quote.stale);
  if (items.length === 0) {
    els.marketStatus.textContent = "no symbols yet";
    els.marketStatus.className = "market-status";
  } else if (anyLive && !anyDegraded) {
    els.marketStatus.textContent = "live data";
    els.marketStatus.className = "market-status ok";
  } else {
    els.marketStatus.textContent = "degraded - showing cached/simulated data";
    els.marketStatus.className = "market-status degraded";
  }
}

function renderWatchlist(data) {
  lastEntries = data.items;
  renderStatsBar(data.items);
  updateMarketStatus(data.items);
  els.emptyState.hidden = data.items.length > 0;
  els.emptyStateText.textContent = "Your watchlist is empty. Add a symbol above to get started.";
  renderGroups(data.items);
  els.status.textContent = `Updated ${new Date(data.generated_at * 1000).toLocaleTimeString()}`;
  loadRecommendations();
}

async function loadWatchlist(silent = false) {
  const requestedMarket = currentMarket;
  try {
    const data = await api(`/watchlist?${marketQuery()}`);
    if (requestedMarket !== currentMarket) return; // stale - market changed while this was in flight
    if (!silent) els.error.hidden = true;
    renderWatchlist(data);
  } catch (err) {
    if (requestedMarket !== currentMarket) return;
    els.error.textContent = err.message;
    els.error.hidden = false;
  }
}

async function addSymbol(symbol) {
  try {
    const data = await api(`/watchlist?${marketQuery()}`, { method: "POST", body: JSON.stringify({ symbol }) });
    els.error.hidden = true;
    renderWatchlist(data);
  } catch (err) {
    els.error.textContent = err.message;
    els.error.hidden = false;
  }
}

async function removeSymbol(symbol) {
  try {
    const data = await api(`/watchlist/${encodeURIComponent(symbol)}?${marketQuery()}`, { method: "DELETE" });
    renderWatchlist(data);
  } catch (err) {
    els.error.textContent = err.message;
    els.error.hidden = false;
  }
}

// ---- Recommendations: candidates not yet on the watchlist, ranked by the
// same attention score, each with a plain-language reason ----

function renderRecommendationCard(rec) {
  const { symbol, quote, level, reason } = rec;
  const div = document.createElement("div");
  div.className = `card level-${level} recommendation-card`;
  div.innerHTML = `
    <div class="card-top">
      <div class="symbol">${symbol}</div>
      <span class="level-badge ${level}">${level}</span>
    </div>
    <div class="price-row">
      <span class="price">${currencySymbol(quote.currency)}${quote.price.toFixed(2)}</span>
      <span class="pct ${quote.pct_change >= 0 ? "positive" : "negative"}">${fmtPct(quote.pct_change)}</span>
    </div>
    <canvas class="sparkline" width="200" height="36"></canvas>
    <div class="meta rec-reason">${reason}</div>
    <div class="card-actions">
      <button class="add-btn" data-symbol="${symbol}">+ Add to watchlist</button>
    </div>
  `;
  drawSparkline(div.querySelector("canvas"), quote.history, quote.pct_change >= 0);
  div.querySelector(".add-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    addSymbol(symbol);
  });
  return div;
}

async function loadRecommendations() {
  const requestedMarket = currentMarket;
  try {
    const list = await api(`/recommendations?market=${encodeURIComponent(requestedMarket)}`);
    if (requestedMarket !== currentMarket) return; // stale - market changed while this was in flight
    els.recommendations.hidden = list.length === 0;
    els.recommendationsGrid.innerHTML = "";
    list.forEach((rec) => els.recommendationsGrid.appendChild(renderRecommendationCard(rec)));
  } catch (err) {
    // non-critical - a failed recommendation fetch shouldn't block the watchlist itself
    if (requestedMarket !== currentMarket) return;
    els.recommendations.hidden = true;
  }
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const symbol = els.input.value.trim();
  if (!symbol) return;
  els.input.value = "";
  addSymbol(symbol);
});

// ---- Portfolio ----

function renderPortfolioStatsBar(data) {
  const currency = currentMarket === "IN" ? "INR" : "USD";
  const pnlCls = data.total_pnl > 0 ? "green" : data.total_pnl < 0 ? "red" : "";
  const stats = [
    { label: "Invested", value: fmtMoney(data.total_invested, currency), cls: "" },
    { label: "Current value", value: fmtMoney(data.total_current_value, currency), cls: "" },
    { label: "Total P&L", value: fmtMoney(data.total_pnl, currency), cls: pnlCls },
    { label: "P&L %", value: fmtPct(data.total_pnl_pct), cls: pnlCls },
    { label: "Holdings", value: data.holdings.length, cls: "" },
  ];
  els.portfolioStatsBar.innerHTML = stats
    .map((s) => `<div class="stat-card ${s.cls}"><div class="stat-label">${s.label}</div><div class="stat-value ${s.cls}">${s.value}</div></div>`)
    .join("");
}

function renderHoldingCard(holding) {
  const { symbol, quantity, avg_buy_price, current_price, invested, current_value, pnl, pnl_pct, quote } = holding;
  const pnlClass = pnl >= 0 ? "positive" : "negative";

  const badges = [];
  if (quote.stale) badges.push(`<span class="badge stale" title="Live data unavailable; showing last known value">stale</span>`);
  if (quote.source === "simulated") badges.push(`<span class="badge simulated" title="Real market data unreachable; showing simulated data">simulated</span>`);

  const div = document.createElement("div");
  div.className = `card holding-card ${pnlClass}`;
  div.innerHTML = `
    <div class="card-top">
      <div class="symbol">${symbol}</div>
      <span>${quantity} qty</span>
    </div>
    <div class="price-row">
      <span class="price">${currencySymbol(quote.currency)}${current_price.toFixed(2)}</span>
      <span class="pct ${quote.pct_change >= 0 ? "positive" : "negative"}">${fmtPct(quote.pct_change)}</span>
    </div>
    <canvas class="sparkline" width="200" height="36"></canvas>
    <div class="meta">avg buy ${currencySymbol(quote.currency)}${avg_buy_price.toFixed(2)} ${badges.join("")}</div>
    <div class="meta">invested ${fmtMoney(invested, quote.currency)} &middot; value ${fmtMoney(current_value, quote.currency)}</div>
    <div class="meta pnl ${pnlClass}">${fmtMoney(pnl, quote.currency)} (${fmtPct(pnl_pct)})</div>
  `;
  drawSparkline(div.querySelector("canvas"), quote.history, quote.pct_change >= 0);
  div.addEventListener("click", () => openPortfolioDetail(symbol));
  return div;
}

function renderPortfolio(data) {
  lastHoldings = data.holdings;
  renderPortfolioStatsBar(data);
  els.portfolioEmptyState.hidden = data.holdings.length > 0;
  els.portfolioHoldings.innerHTML = "";
  data.holdings.forEach((h) => els.portfolioHoldings.appendChild(renderHoldingCard(h)));
  renderAllocation(data.holdings);
  renderPnlChart(data.holdings);
}

// ---- Portfolio allocation pie chart (plain canvas, no charting library) ----

const ALLOCATION_COLORS = ["#4f46e5", "#16a34a", "#d97706", "#dc2626", "#0891b2", "#9333ea", "#be185d", "#65a30d"];

function drawPieChart(canvas, slices) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, radius = Math.min(w, h) / 2 - 4;
  const total = slices.reduce((sum, s) => sum + s.value, 0) || 1;

  let angle = -Math.PI / 2;
  slices.forEach((slice) => {
    const sliceAngle = (slice.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angle, angle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = slice.color;
    ctx.fill();
    angle += sliceAngle;
  });

  // donut hole, so it doubles as a clean center label area
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--panel") || "#fff";
  ctx.fill();
}

function renderAllocation(holdings) {
  if (holdings.length === 0) {
    els.allocationSection.hidden = true;
    return;
  }
  els.allocationSection.hidden = false;

  const sorted = [...holdings].sort((a, b) => b.current_value - a.current_value);
  const slices = sorted.map((h, i) => ({
    symbol: h.symbol,
    value: h.current_value,
    color: ALLOCATION_COLORS[i % ALLOCATION_COLORS.length],
  }));
  drawPieChart(els.allocationChart, slices);

  const total = slices.reduce((sum, s) => sum + s.value, 0) || 1;
  els.allocationLegend.innerHTML = slices
    .map((s) => `
    <div class="allocation-legend-row">
      <span class="allocation-swatch" style="background:${s.color}"></span>
      <span class="allocation-legend-symbol">${s.symbol}</span>
      <span class="allocation-legend-pct">${((s.value / total) * 100).toFixed(1)}%</span>
    </div>`)
    .join("");
}

// ---- Profit & loss by holding bar chart (plain canvas) ----

const PNL_ROW_HEIGHT = 42;
const PNL_TRACK_HEIGHT = 22;

// Draws a rect with rounded corners, clamping the radius so it never exceeds
// the shape's own half-width/height (canvas throws on an invalid radius).
function fillRoundedRect(ctx, x, y, w, h, r, color) {
  const radius = Math.max(Math.min(r, h / 2, Math.max(w, 0) / 2), 0);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.roundRect(x, y, Math.max(w, 0), h, radius);
  ctx.fill();
}

// Shortens text with an ellipsis if it would overflow maxWidth at the
// canvas's currently-set font (must be called with ctx.font already set).
function truncateToWidth(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let truncated = text;
  while (truncated.length > 1 && ctx.measureText(`${truncated}_`).width > maxWidth) {
    truncated = truncated.slice(0, -1);
  }
  return `${truncated}_`;
}

// Backing-store resolution is set from the canvas's actual CSS (layout)
// size * devicePixelRatio, so text/bars stay crisp instead of being
// upscaled/blurred by the browser when CSS stretches a fixed-resolution canvas.
function sizeCanvasForDisplay(canvas, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.getBoundingClientRect().width || canvas.parentElement.clientWidth || 300;
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.height = `${cssHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width: cssWidth, height: cssHeight };
}

function drawPnlBarChart(canvas, holdings) {
  const rowH = PNL_ROW_HEIGHT;
  const cssHeight = holdings.length * rowH + 4;
  const { ctx, width } = sizeCanvasForDisplay(canvas, cssHeight);
  ctx.clearRect(0, 0, width, cssHeight);
  ctx.textBaseline = "middle";

  const labelW = 118;
  const valueW = 62;
  const trackW = width - labelW - valueW;
  const textColor = getComputedStyle(document.body).getPropertyValue("--text").trim() || "#1a1a1a";
  const trackColor = getComputedStyle(document.body).getPropertyValue("--border").trim() || "#e5e5e5";
  const labelFont = "700 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const maxAbs = Math.max(...holdings.map((h) => Math.abs(h.pnl_pct)), 0.01);

  holdings.forEach((h, i) => {
    const y = i * rowH + rowH / 2;
    const positive = h.pnl_pct >= 0;
    const barColor = positive ? "#16a34a" : "#dc2626";
    const barW = Math.max((Math.abs(h.pnl_pct) / maxAbs) * trackW, 10);

    ctx.font = labelFont;
    ctx.textAlign = "left";
    ctx.fillStyle = textColor;
    ctx.fillText(truncateToWidth(ctx, h.symbol, labelW - 10), 0, y);

    fillRoundedRect(ctx, labelW, y - PNL_TRACK_HEIGHT / 2, trackW, PNL_TRACK_HEIGHT, PNL_TRACK_HEIGHT / 2, trackColor);
    fillRoundedRect(ctx, labelW, y - PNL_TRACK_HEIGHT / 2, barW, PNL_TRACK_HEIGHT, PNL_TRACK_HEIGHT / 2, barColor);

    ctx.font = "700 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "right";
    ctx.fillStyle = barColor;
    ctx.fillText(`${positive ? "+" : ""}${h.pnl_pct.toFixed(1)}%`, width, y);
  });
}

function renderPnlChart(holdings) {
  if (holdings.length === 0) {
    els.pnlSection.hidden = true;
    return;
  }
  els.pnlSection.hidden = false;

  const sorted = [...holdings].sort((a, b) => b.pnl_pct - a.pnl_pct);
  drawPnlBarChart(els.pnlChart, sorted);

  const gainers = holdings.filter((h) => h.pnl_pct > 0).length;
  const losers = holdings.filter((h) => h.pnl_pct < 0).length;
  els.pnlSummary.innerHTML = `<span class="gainers">${gainers} gaining</span><span class="losers">${losers} losing</span>`;
}

async function loadPortfolio(silent = false) {
  const requestedMarket = currentMarket;
  try {
    const data = await api(`/portfolio?${marketQuery()}`);
    if (requestedMarket !== currentMarket) return; // stale - market changed while this was in flight
    if (!silent) els.portfolioError.hidden = true;
    renderPortfolio(data);
  } catch (err) {
    if (requestedMarket !== currentMarket) return;
    els.portfolioError.textContent = err.message;
    els.portfolioError.hidden = false;
  }
}

async function addHolding(symbol, quantity, avgBuyPrice) {
  try {
    const data = await api(`/portfolio?${marketQuery()}`, {
      method: "POST",
      body: JSON.stringify({ symbol, quantity, avg_buy_price: avgBuyPrice }),
    });
    els.portfolioError.hidden = true;
    renderPortfolio(data);
  } catch (err) {
    els.portfolioError.textContent = err.message;
    els.portfolioError.hidden = false;
  }
}

els.holdingForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const symbol = els.holdingSymbol.value.trim();
  const qty = parseFloat(els.holdingQty.value);
  const price = parseFloat(els.holdingPrice.value);
  if (!symbol || !qty || !price) return;
  els.holdingSymbol.value = "";
  els.holdingQty.value = "";
  els.holdingPrice.value = "";
  addHolding(symbol, qty, price);
});

els.exportCsvBtn.addEventListener("click", async () => {
  try {
    const res = await fetch(`${API_BASE}/portfolio/export?${marketQuery()}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "portfolio.csv";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    els.portfolioError.textContent = err.message;
    els.portfolioError.hidden = false;
  }
});

// ---- Detail modal: bigger chart + analysis, shared by both views ----

function rangeStats(quote) {
  const cur = currencySymbol(quote.currency);
  const stats = [];
  if (quote.day_low != null && quote.day_high != null) {
    stats.push({ label: "Day range", value: `${cur}${quote.day_low.toFixed(2)} - ${cur}${quote.day_high.toFixed(2)}` });
  }
  if (quote.year_low != null && quote.year_high != null) {
    stats.push({ label: "52-week range", value: `${cur}${quote.year_low.toFixed(2)} - ${cur}${quote.year_high.toFixed(2)}` });
  }
  if (quote.fifty_day_avg != null) {
    stats.push({ label: "50-day avg", value: `${cur}${quote.fifty_day_avg.toFixed(2)}` });
  }
  if (quote.two_hundred_day_avg != null) {
    stats.push({ label: "200-day avg", value: `${cur}${quote.two_hundred_day_avg.toFixed(2)}` });
  }
  return stats;
}

function openWatchlistDetail(symbol) {
  const entry = lastEntries.find((e) => e.symbol === symbol);
  if (!entry) return;
  const { quote, score, level, breakdown, change_since_last_check } = entry;
  els.modalSymbol.textContent = symbol;
  els.modalLevelBadge.hidden = false;
  els.modalLevelBadge.textContent = level;
  els.modalLevelBadge.className = `level-badge ${level}`;
  els.modalPriceRow.innerHTML = `${currencySymbol(quote.currency)}${quote.price.toFixed(2)} <span class="pct ${quote.pct_change >= 0 ? "positive" : "negative"}">${fmtPct(quote.pct_change)}</span>`;

  drawSparkline(els.modalChart, quote.history, quote.pct_change >= 0);

  els.breakdownSection.hidden = false;
  const maxContribution = Math.max(breakdown.move_contribution, breakdown.volume_contribution, 0.1);
  els.breakdownBars.innerHTML = `
    <div class="breakdown-row">
      <span>Price move</span>
      <div class="breakdown-track"><div class="breakdown-fill move" style="width:${(breakdown.move_contribution / maxContribution) * 100}%"></div>
      <span>${breakdown.move_contribution.toFixed(2)}</span>
    </div>
    <div class="breakdown-row">
      <span>Volume surge</span>
      <div class="breakdown-track"><div class="breakdown-fill volume" style="width:${(breakdown.volume_contribution / maxContribution) * 100}%"></div>
      <span>${breakdown.volume_contribution.toFixed(2)}</span>
    </div>
  `;

  const stats = [
    { label: "Prev close", value: `${currencySymbol(quote.currency)}${quote.prev_close.toFixed(2)}` },
    ...rangeStats(quote),
    { label: "Volume", value: Math.round(quote.volume).toLocaleString() },
    { label: "Avg volume", value: Math.round(quote.avg_volume).toLocaleString() },
    { label: "Score", value: score.toFixed(2) },
    { label: "Data source", value: quote.source },
    { label: "As of", value: new Date(quote.as_of * 1000).toLocaleTimeString() },
    { label: "Since last check", value: change_since_last_check !== null ? fmtPct(change_since_last_check) : "first visit" },
  ];
  els.modalStats.innerHTML = stats
    .map((s) => `<div><div class="modal-stat-label">${s.label}</div><div class="modal-stat-value">${s.value}</div></div>`)
    .join("");

  els.modal.hidden = false;
}

function openPortfolioDetail(symbol) {
  const holding = lastHoldings.find((h) => h.symbol === symbol);
  if (!holding) return;
  const { quote, quantity, avg_buy_price, current_price, invested, current_value, pnl, pnl_pct } = holding;

  els.modalSymbol.textContent = symbol;
  els.modalLevelBadge.hidden = true;
  els.modalPriceRow.innerHTML = `${currencySymbol(quote.currency)}${current_price.toFixed(2)} <span class="pct ${quote.pct_change >= 0 ? "positive" : "negative"}">${fmtPct(quote.pct_change)}</span>`;

  drawSparkline(els.modalChart, quote.history, quote.pct_change >= 0);
  els.breakdownSection.hidden = true;

  const stats = [
    { label: "Quantity", value: quantity },
    { label: "Avg buy price", value: `${currencySymbol(quote.currency)}${avg_buy_price.toFixed(2)}` },
    { label: "Invested", value: fmtMoney(invested, quote.currency) },
    { label: "Current value", value: fmtMoney(current_value, quote.currency) },
    { label: "P&L", value: fmtMoney(pnl, quote.currency) },
    { label: "P&L %", value: fmtPct(pnl_pct) },
    ...rangeStats(quote),
    { label: "Data source", value: quote.source },
    { label: "As of", value: new Date(quote.as_of * 1000).toLocaleTimeString() },
  ];
  els.modalStats.innerHTML = stats
    .map((s) => `<div><div class="modal-stat-label">${s.label}</div><div class="modal-stat-value">${s.value}</div></div>`)
    .join("");

  els.modal.hidden = false;
}

function closeDetail() {
  els.modal.hidden = true;
}
els.modalClose.addEventListener("click", closeDetail);
els.modalBackdrop.addEventListener("click", closeDetail);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDetail();
});

// ---- Boot ----

if (getToken()) {
  showAppView();
} else {
  showAuthView();
}