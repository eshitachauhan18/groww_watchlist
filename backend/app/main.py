from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()


import asyncio
import contextlib
import csv
import io
import logging
import re
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from . import auth, db, scoring
from .models import (
    AddHoldingRequest,
    AddSymbolRequest,
    AuthResponse,
    HoldingEntry,
    LoginRequest,
    PortfolioResponse,
    PreferencesRequest,
    PreferencesResponse,
    Quote,
    RecommendationEntry,
    RegisterRequest,
    SetAlertRequest,
    SetNoteRequest,
    WatchlistEntry,
    WatchlistResponse,
)
from .poller import run_poller
from .providers.aggregator import ResilientMarketDataService
from .providers.simulated_provider import SimulatedProvider
from .providers.yfinance_provider import YFinanceProvider

logging.basicConfig(level=logging.INFO)

SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")
SIGNIFICANT_CHANGE_PCT = 1.5
VALID_MARKETS = {"US", "IN"}

# Candidate pools for "recommended for you" - a curated cross-section of
# large/mid/low priced names per market. In production these would come from
# an exchange listing or a trending-symbols feed; kept static here since the
# point is the ranking logic, not sourcing the universe. Indian tickers use
# Yahoo Finance's standard NSE suffix (".NS") - same provider, same pipeline,
# no separate integration needed for a second market.
RECOMMENDATION_UNIVERSE = {
    "US": [
        "BKNG", "AVGO", "COST", "NFLX", "MSFT",
        "AAPL", "TSLA", "GOOGL", "AMZN", "NVDA", "META", "AMD", "UBER", "DIS", "PYPL", "ROKU",
        "SNAP", "PINS", "ETSY", "F", "SIRI", "PLUG", "NOK", "T", "BAC", "INTC",
    ],
    "IN": [
        "MRF.NS", "PAGEIND.NS", "SHREECEM.NS", "BAJFINANCE.NS", "MARUTI.NS", "TCS.NS",
        "RELIANCE.NS", "HINDUNILVR.NS", "ADANIENT.NS", "KOTAKBANK.NS", "SUNPHARMA.NS",
        "HDFCBANK.NS", "LT.NS", "INFY.NS", "AXISBANK.NS",
        "ICICIBANK.NS", "TATAMOTORS.NS", "SBIN.NS", "WIPRO.NS", "ITC.NS",
        "NTPC.NS", "COALINDIA.NS", "ONGC.NS", "IDEA.NS", "YESBANK.NS",
    ],
}
MAX_RECOMMENDATIONS = 6

market_data = ResilientMarketDataService(primary=YFinanceProvider(), fallback=SimulatedProvider())


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_poller(market_data))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Smart Market Watchlist", lifespan=lifespan)

# Demo-scope CORS: wide open so a plain static file server can call the API.
# In production this must be locked to the real frontend origin(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_user(authorization: str = Header(..., alias="Authorization")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Missing bearer token")
    session = db.get_session(auth.hash_token(token))
    if session is None:
        raise HTTPException(401, "Session expired or invalid - please log in again")
    return session["user_id"]


def normalize_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Symbol must be 1-20 chars: letters, digits, '.', '-'")
    return symbol


def normalize_market(market: str) -> str:
    market = market.strip().upper()
    if market not in VALID_MARKETS:
        raise HTTPException(400, "market must be one of: US, IN")
    return market


def build_entry(user_id: str, symbol: str, sensitivity: str) -> WatchlistEntry:
    quote: Quote = market_data.get_quote(symbol)
    score, level, breakdown = scoring.compute_score(quote, sensitivity=sensitivity)

    last_seen = db.get_last_seen(user_id, symbol)
    change_since_last_check = None
    is_new = last_seen is None
    if last_seen is not None and last_seen["price"]:
        change_since_last_check = round((quote.price - last_seen["price"]) / last_seen["price"] * 100, 3)

    db.set_last_seen(user_id, symbol, quote.price, score, level)

    item = db.get_watchlist_item(user_id, symbol)
    target_price = item["target_price"] if item else None
    target_direction = item["target_direction"] if item else None
    note = (item["note"] if item and item["note"] else "") if item else ""
    added_price = item["added_price"] if item else None

    alert_triggered = False
    if target_price is not None and target_direction is not None:
        alert_triggered = (
            quote.price >= target_price if target_direction == "above" else quote.price <= target_price
        )

    change_since_added = None
    if added_price:
        change_since_added = round((quote.price - added_price) / added_price * 100, 3)

    return WatchlistEntry(
        symbol=symbol,
        quote=quote,
        score=score,
        level=level,  # type: ignore[arg-type]
        breakdown=breakdown,
        change_since_last_check=change_since_last_check,
        is_new=is_new,
        target_price=target_price,
        target_direction=target_direction,  # type: ignore[arg-type]
        alert_triggered=alert_triggered,
        note=note,
        added_price=added_price,
        change_since_added=change_since_added,
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": time.time()}


# --- auth ---


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest, request: Request) -> AuthResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not auth.check_rate_limit(f"register:{client_ip}"):
        raise HTTPException(429, "Too many signups from this network - try again in a few minutes")

    username = payload.username.strip()
    if not auth.validate_username(username):
        raise HTTPException(400, "Username must be 3-20 characters: letters, digits, underscore")
    if not auth.validate_password(payload.password):
        raise HTTPException(400, "Password must be 8-100 characters")
    if db.get_user_by_username(username) is not None:
        raise HTTPException(409, "Username already taken")

    user_id = str(uuid.uuid4())
    password_hash, salt = auth.hash_password(payload.password)
    db.create_user(user_id, username, password_hash, salt)

    raw_token, token_hash = auth.new_session_token()
    db.create_session(token_hash, user_id, auth.SESSION_TTL_SECONDS)
    return AuthResponse(token=raw_token, username=username)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request) -> AuthResponse:
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login:{client_ip}:{payload.username.strip().lower()}"
    if not auth.check_rate_limit(rate_key):
        raise HTTPException(429, "Too many login attempts - try again in a few minutes")

    user = db.get_user_by_username(payload.username.strip())
    # Same generic error whether the username doesn't exist or the password is
    # wrong - avoids leaking which usernames are registered.
    if user is None or not auth.verify_password(payload.password, user["password_hash"], user["salt"]):
        raise HTTPException(401, "Invalid username or password")

    raw_token, token_hash = auth.new_session_token()
    db.create_session(token_hash, user["id"], auth.SESSION_TTL_SECONDS)
    return AuthResponse(token=raw_token, username=user["username"])


@app.post("/api/auth/logout")
def logout(authorization: str = Header(..., alias="Authorization")) -> dict:
    if authorization.startswith("Bearer "):
        db.delete_session(auth.hash_token(authorization.removeprefix("Bearer ").strip()))
    return {"status": "ok"}


# --- preferences ---


@app.get("/api/preferences", response_model=PreferencesResponse)
def get_preferences(user_id: str = Depends(get_current_user)) -> PreferencesResponse:
    return PreferencesResponse(sensitivity=db.get_sensitivity(user_id))


@app.post("/api/preferences", response_model=PreferencesResponse)
def update_preferences(payload: PreferencesRequest, user_id: str = Depends(get_current_user)) -> PreferencesResponse:
    if payload.sensitivity not in scoring.SENSITIVITY_MULTIPLIERS:
        raise HTTPException(400, "sensitivity must be one of: conservative, balanced, aggressive")
    db.set_sensitivity(user_id, payload.sensitivity)
    return PreferencesResponse(sensitivity=payload.sensitivity)


# --- watchlist ---


@app.get("/api/watchlist", response_model=WatchlistResponse)
def get_watchlist(market: str = "US", user_id: str = Depends(get_current_user)) -> WatchlistResponse:
    market = normalize_market(market)
    sensitivity = db.get_sensitivity(user_id)
    symbols = db.list_symbols(user_id, market)
    entries = [build_entry(user_id, s, sensitivity) for s in symbols]
    entries.sort(key=lambda e: e.score, reverse=True)

    highlights = []
    for e in entries:
        if e.is_new:
            continue
        if e.change_since_last_check is not None and abs(e.change_since_last_check) >= SIGNIFICANT_CHANGE_PCT:
            direction = "up" if e.change_since_last_check > 0 else "down"
            highlights.append(f"{e.symbol} moved {direction} {abs(e.change_since_last_check):.1f}% since you last checked")

    return WatchlistResponse(items=entries, highlights=highlights, generated_at=time.time())


@app.post("/api/watchlist", response_model=WatchlistResponse)
def add_to_watchlist(payload: AddSymbolRequest, market: str = "US", user_id: str = Depends(get_current_user)) -> WatchlistResponse:
    # We deliberately don't make a synchronous "does this symbol exist" call
    # to the market data provider here: that provider is itself unreliable
    # (see ResilientMarketDataService), so a live check would either reject
    # valid symbols during an outage/rate-limit or add more load to an
    # already-struggling dependency. Format validation is enough to accept;
    # the watchlist view itself reveals real vs stale/simulated data via badges.
    market = normalize_market(market)
    symbol = normalize_symbol(payload.symbol)
    # Baseline price for the "% change since added" stat - best-effort only;
    # the resilient provider always returns something (live/cached/simulated).
    added_price = market_data.get_quote(symbol).price
    db.add_symbol(user_id, symbol, market, added_price)
    return get_watchlist(market=market, user_id=user_id)


@app.delete("/api/watchlist/{symbol}", response_model=WatchlistResponse)
def remove_from_watchlist(symbol: str, market: str = "US", user_id: str = Depends(get_current_user)) -> WatchlistResponse:
    market = normalize_market(market)
    db.remove_symbol(user_id, normalize_symbol(symbol))
    return get_watchlist(market=market, user_id=user_id)


@app.patch("/api/watchlist/{symbol}/alert", response_model=WatchlistResponse)
def set_watchlist_alert(symbol: str, payload: SetAlertRequest, market: str = "US", user_id: str = Depends(get_current_user)) -> WatchlistResponse:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol)
    if payload.target_price is not None:
        if payload.target_price <= 0:
            raise HTTPException(400, "Target price must be greater than 0")
        if payload.target_direction is None:
            raise HTTPException(400, "target_direction is required when setting a target_price")
    db.set_alert(user_id, symbol, payload.target_price, payload.target_direction)
    return get_watchlist(market=market, user_id=user_id)


@app.patch("/api/watchlist/{symbol}/note", response_model=WatchlistResponse)
def set_watchlist_note(symbol: str, payload: SetNoteRequest, market: str = "US", user_id: str = Depends(get_current_user)) -> WatchlistResponse:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol)
    if len(payload.note) > 280:
        raise HTTPException(400, "Note must be 280 characters or fewer")
    db.set_note(user_id, symbol, payload.note)
    return get_watchlist(market=market, user_id=user_id)


@app.get("/api/watchlist/export")
def export_watchlist(market: str = "US", user_id: str = Depends(get_current_user)) -> PlainTextResponse:
    market = normalize_market(market)
    data = get_watchlist(market=market, user_id=user_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["symbol", "price", "pct_change", "level", "score", "note", "target_price", "target_direction", "alert_triggered", "change_since_added"]
    )
    for e in data.items:
        writer.writerow(
            [e.symbol, e.quote.price, e.quote.pct_change, e.level, e.score, e.note, e.target_price,
             e.target_direction, e.alert_triggered, e.change_since_added]
        )
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=watchlist.csv"},
    )


@app.get("/api/recommendations", response_model=list[RecommendationEntry])
def get_recommendations(market: str = "US", user_id: str = Depends(get_current_user)) -> list[RecommendationEntry]:
    market = normalize_market(market)
    sensitivity = db.get_sensitivity(user_id)
    already_watched = set(db.list_symbols(user_id, market))
    candidates = [s for s in RECOMMENDATION_UNIVERSE[market] if s not in already_watched]

    entries = []
    for symbol in candidates:
        quote = market_data.get_quote(symbol)
        score, level, breakdown = scoring.compute_score(quote, sensitivity=sensitivity)
        reason = (
            f"Moved {quote.pct_change:+.1f}% - large for this stock's typical swing"
            if breakdown.move_contribution >= breakdown.volume_contribution
            else "Trading volume well above its average - unusual activity"
        )
        entries.append(RecommendationEntry(symbol=symbol, quote=quote, score=score, level=level, reason=reason))

    entries.sort(key=lambda e: e.score, reverse=True)
    return entries[:MAX_RECOMMENDATIONS]


# --- portfolio ---


def build_holding(user_id: str, row) -> HoldingEntry:
    quote = market_data.get_quote(row["symbol"])
    invested = row["quantity"] * row["avg_buy_price"]
    current_value = row["quantity"] * quote.price
    pnl = current_value - invested
    pnl_pct = (pnl / invested * 100) if invested else 0.0
    return HoldingEntry(
        symbol=row["symbol"],
        quantity=row["quantity"],
        avg_buy_price=row["avg_buy_price"],
        current_price=quote.price,
        invested=round(invested, 2),
        current_value=round(current_value, 2),
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 3),
        quote=quote,
    )


@app.get("/api/portfolio", response_model=PortfolioResponse)
def get_portfolio(market: str = "US", user_id: str = Depends(get_current_user)) -> PortfolioResponse:
    market = normalize_market(market)
    rows = db.list_holdings(user_id, market)
    holdings = [build_holding(user_id, r) for r in rows]
    holdings.sort(key=lambda h: h.current_value, reverse=True)

    total_invested = round(sum(h.invested for h in holdings), 2)
    total_current_value = round(sum(h.current_value for h in holdings), 2)
    total_pnl = round(total_current_value - total_invested, 2)
    total_pnl_pct = round((total_pnl / total_invested * 100) if total_invested else 0.0, 3)

    return PortfolioResponse(
        holdings=holdings,
        total_invested=total_invested,
        total_current_value=total_current_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        generated_at=time.time(),
    )


@app.post("/api/portfolio", response_model=PortfolioResponse)
def add_holding(payload: AddHoldingRequest, market: str = "US", user_id: str = Depends(get_current_user)) -> PortfolioResponse:
    market = normalize_market(market)
    symbol = normalize_symbol(payload.symbol)
    if payload.quantity <= 0:
        raise HTTPException(400, "Quantity must be greater than 0")
    if payload.avg_buy_price <= 0:
        raise HTTPException(400, "Average buy price must be greater than 0")
    db.upsert_holding(user_id, symbol, payload.quantity, payload.avg_buy_price, market)
    return get_portfolio(market=market, user_id=user_id)


@app.delete("/api/portfolio/{symbol}", response_model=PortfolioResponse)
def remove_holding(symbol: str, market: str = "US", user_id: str = Depends(get_current_user)) -> PortfolioResponse:
    market = normalize_market(market)
    db.remove_holding(user_id, normalize_symbol(symbol))
    return get_portfolio(market=market, user_id=user_id)


@app.get("/api/portfolio/export")
def export_portfolio(market: str = "US", user_id: str = Depends(get_current_user)) -> PlainTextResponse:
    market = normalize_market(market)
    data = get_portfolio(market=market, user_id=user_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["symbol", "quantity", "avg_buy_price", "current_price", "invested", "current_value", "pnl", "pnl_pct"])
    for h in data.holdings:
        writer.writerow([h.symbol, h.quantity, h.avg_buy_price, h.current_price, h.invested, h.current_value, h.pnl, h.pnl_pct])
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )