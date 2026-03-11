"""
Market data models for F&O signal generation.
Defines the input structures needed for analysis.
"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Instrument(Enum):
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    FINNIFTY = "FINNIFTY"
    MIDCPNIFTY = "MIDCPNIFTY"


class MarketSession(Enum):
    PRE_OPEN = "09:00-09:15"
    OPENING_RANGE = "09:15-09:45"
    MORNING = "09:45-11:30"
    MIDDAY = "11:30-13:30"
    AFTERNOON = "13:30-15:00"
    CLOSING = "15:00-15:30"


@dataclass
class CandleData:
    """OHLCV candle data"""
    open: float
    high: float
    low: float
    close: float
    volume: int
    timeframe: str  # "1min", "5min", "15min", "1hr", "1day"


@dataclass
class StrikeOI:
    """Open interest data for a single strike"""
    strike: int
    call_oi: int
    put_oi: int
    call_oi_change: int   # Change from previous session
    put_oi_change: int
    call_iv: float        # Implied volatility %
    put_iv: float
    call_ltp: float
    put_ltp: float


@dataclass
class OptionChain:
    """Full option chain snapshot"""
    instrument: str
    spot_price: float
    atm_strike: int
    expiry: str           # "NEAR", "NEXT", "FAR" or date string
    strikes: list[StrikeOI] = field(default_factory=list)

    @property
    def total_call_oi(self) -> int:
        return sum(s.call_oi for s in self.strikes)

    @property
    def total_put_oi(self) -> int:
        return sum(s.put_oi for s in self.strikes)

    @property
    def pcr(self) -> float:
        """Put-Call Ratio by OI"""
        if self.total_call_oi == 0:
            return 0.0
        return round(self.total_put_oi / self.total_call_oi, 3)

    def max_call_oi_strike(self) -> Optional[int]:
        if not self.strikes:
            return None
        return max(self.strikes, key=lambda s: s.call_oi).strike

    def max_put_oi_strike(self) -> Optional[int]:
        if not self.strikes:
            return None
        return max(self.strikes, key=lambda s: s.put_oi).strike

    def atm_straddle_premium(self) -> float:
        """ATM call + put premium"""
        for s in self.strikes:
            if s.strike == self.atm_strike:
                return round(s.call_ltp + s.put_ltp, 2)
        return 0.0


@dataclass
class TechnicalIndicators:
    """Technical indicator values at time of analysis"""
    vwap: float
    rsi_5min: float           # RSI on 5-min chart
    rsi_15min: float          # RSI on 15-min chart
    ema_9: float
    ema_21: float
    prev_day_high: float
    prev_day_low: float
    prev_day_close: float
    opening_range_high: float  # High of 9:15–9:45 AM
    opening_range_low: float   # Low of 9:15–9:45 AM
    day_high: float
    day_low: float
    volume_ratio: float        # Current volume / average volume (ratio)


@dataclass
class MarketContext:
    """Complete market context for signal generation"""
    instrument: str           # e.g., "NIFTY", "BANKNIFTY"
    spot_price: float
    futures_price: float
    india_vix: float
    iv_rank: float            # 0-100, where current IV stands vs 52-week range
    session: str              # Current trading session
    is_expiry_day: bool
    expiry_type: str          # "WEEKLY", "MONTHLY"
    current_time: str         # "HH:MM"
    option_chain: OptionChain
    technicals: TechnicalIndicators
    candles_15min: list[CandleData] = field(default_factory=list)  # Last 10 candles
    lot_size: int = 50        # Default Nifty lot size
    notes: str = ""           # Any additional context (events, news, etc.)


# ─────────────────────────────────────────────
# Sample data builder for testing
# ─────────────────────────────────────────────

def build_sample_market_context() -> MarketContext:
    """Create a realistic sample market context for demo/testing."""
    strikes = [
        StrikeOI(22800, call_oi=1200000, put_oi=800000,  call_oi_change=50000,  put_oi_change=-20000, call_iv=12.5, put_iv=13.0, call_ltp=120.0, put_ltp=95.0),
        StrikeOI(22900, call_oi=900000,  put_oi=950000,  call_oi_change=30000,  put_oi_change=40000,  call_iv=11.8, put_iv=12.2, call_ltp=75.0,  put_ltp=140.0),
        StrikeOI(23000, call_oi=2500000, put_oi=2200000, call_oi_change=120000, put_oi_change=80000,  call_iv=11.0, put_iv=11.5, call_ltp=42.0,  put_ltp=48.0),  # ATM
        StrikeOI(23100, call_oi=1800000, put_oi=1100000, call_oi_change=60000,  put_oi_change=-30000, call_iv=10.5, put_iv=11.0, call_ltp=22.0,  put_ltp=85.0),
        StrikeOI(23200, call_oi=3200000, put_oi=600000,  call_oi_change=200000, put_oi_change=-10000, call_iv=10.2, put_iv=10.8, call_ltp=10.0,  put_ltp=120.0),
        StrikeOI(22700, call_oi=700000,  put_oi=2800000, call_oi_change=-15000, put_oi_change=150000, call_iv=13.2, put_iv=13.8, call_ltp=185.0, put_ltp=22.0),
        StrikeOI(22600, call_oi=500000,  put_oi=3100000, call_oi_change=-10000, put_oi_change=100000, call_iv=14.0, put_iv=14.5, call_ltp=225.0, put_ltp=12.0),
    ]

    option_chain = OptionChain(
        instrument="NIFTY",
        spot_price=23005.50,
        atm_strike=23000,
        expiry="NEAR",
        strikes=strikes
    )

    technicals = TechnicalIndicators(
        vwap=22985.0,
        rsi_5min=58.5,
        rsi_15min=55.2,
        ema_9=22990.0,
        ema_21=22960.0,
        prev_day_high=23050.0,
        prev_day_low=22850.0,
        prev_day_close=22980.0,
        opening_range_high=23020.0,
        opening_range_low=22960.0,
        day_high=23025.0,
        day_low=22955.0,
        volume_ratio=1.4
    )

    candles = [
        CandleData(22960, 22975, 22950, 22968, 850000, "15min"),
        CandleData(22968, 22995, 22965, 22990, 920000, "15min"),
        CandleData(22990, 23020, 22985, 23010, 1100000, "15min"),
        CandleData(23010, 23025, 22998, 23005, 780000, "15min"),
        CandleData(23005, 23015, 22995, 23008, 650000, "15min"),
    ]

    return MarketContext(
        instrument="NIFTY",
        spot_price=23005.50,
        futures_price=23018.0,
        india_vix=13.2,
        iv_rank=38.0,
        session="MORNING",
        is_expiry_day=False,
        expiry_type="WEEKLY",
        current_time="10:45",
        option_chain=option_chain,
        technicals=technicals,
        candles_15min=candles,
        lot_size=50,
        notes="RBI policy tomorrow. Market opened gap-up 25 points."
    )
