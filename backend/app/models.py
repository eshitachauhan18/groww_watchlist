from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class AddSymbolRequest(BaseModel):
    symbol: str


class SetAlertRequest(BaseModel):
    target_price: Optional[float] = None
    target_direction: Optional[Literal["above", "below"]] = None


class SetNoteRequest(BaseModel):
    note: str = ""


class Quote(BaseModel):
    symbol: str
    price: float
    prev_close: float
    volume: float
    avg_volume: float
    pct_change: float
    as_of: float
    source: Literal["live", "cached", "simulated"]
    stale: bool
    currency: Literal["USD", "INR"] = "USD"
    history: list[float] = []
    day_low: Optional[float] = None
    day_high: Optional[float] = None
    year_low: Optional[float] = None
    year_high: Optional[float] = None
    fifty_day_avg: Optional[float] = None
    two_hundred_day_avg: Optional[float] = None


class ScoreBreakdown(BaseModel):
    move_contribution: float
    volume_contribution: float


class WatchlistEntry(BaseModel):
    symbol: str
    quote: Quote
    score: float
    level: Literal["low", "medium", "high"]
    breakdown: ScoreBreakdown
    change_since_last_check: Optional[float] = None
    is_new: bool = False
    target_price: Optional[float] = None
    target_direction: Optional[Literal["above", "below"]] = None
    alert_triggered: bool = False
    note: str = ""
    added_price: Optional[float] = None
    change_since_added: Optional[float] = None


class WatchlistResponse(BaseModel):
    items: list[WatchlistEntry]
    highlights: list[str]
    generated_at: float


class RecommendationEntry(BaseModel):
    symbol: str
    quote: Quote
    score: float
    level: Literal["low", "medium", "high"]
    reason: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str


class PreferencesRequest(BaseModel):
    sensitivity: str


class PreferencesResponse(BaseModel):
    sensitivity: str


class AddHoldingRequest(BaseModel):
    symbol: str
    quantity: float
    avg_buy_price: float


class HoldingEntry(BaseModel):
    symbol: str
    quantity: float
    avg_buy_price: float
    current_price: float
    invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    quote: Quote


class PortfolioResponse(BaseModel):
    holdings: list[HoldingEntry]
    total_invested: float
    total_current_value: float
    total_pnl: float
    total_pnl_pct: float
    generated_at: float