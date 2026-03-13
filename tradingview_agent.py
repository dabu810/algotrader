"""
TradingView Technical Analysis Agent
======================================
Deep technical analysis with price direction prediction.
Integrates with TradingView MCP server for real-time indicator + OHLCV data.

Architecture (loosely coupled):
  - tradingview_mcp_client.py  →  data layer (MCP server / fallback scraper)
  - model_provider.py          →  LLM layer (Anthropic / OpenAI / Gemini / Mistral)
  - tradingview_agent.py       →  orchestration + local analysis tools

Usage:
    python3 tradingview_agent.py NIFTY
    python3 tradingview_agent.py RELIANCE --timeframe 15m
    python3 tradingview_agent.py HDFCBANK --timeframe 1h --provider gemini
    python3 tradingview_agent.py NIFTY --timeframe 4h --exchange NSE --quiet

Setup:
    pip install mcp-tradingview-server mcp
    export ANTHROPIC_API_KEY=...   (or OPENAI/GOOGLE/MISTRAL key)
"""

import argparse
import json
import os
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from model_provider import (
    SUPPORTED_PROVIDERS,
    ToolCall,
    get_provider,
    provider_info,
)
from tradingview_mcp_client import TradingViewMCPClient

load_dotenv()
console = Console()


# ── Tool Definitions (canonical format) ──────────────────────────────────────

TOOLS = [
    {
        "name": "get_indicators",
        "description": (
            "Fetch a full TradingView indicator snapshot for a symbol on a given timeframe. "
            "Returns RSI, MACD, EMA20/50/200, SMA200, Bollinger Bands, ATR, Stochastic, ADX, "
            "OBV, VWAP, Williams %R, CCI, Ichimoku, and 70+ other indicators. "
            "This is the primary data source — always call this first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol":    {"type": "string",  "description": "NSE/BSE symbol e.g. NIFTY, RELIANCE, HDFCBANK, BANKNIFTY"},
                "exchange":  {"type": "string",  "description": "Exchange: NSE | BSE | NASDAQ | NYSE | MCX (default NSE)"},
                "timeframe": {"type": "string",  "description": "Candle timeframe: 1m | 5m | 15m | 30m | 1h | 4h | 1D | 1W (default 1h)"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_historical_data",
        "description": (
            "Fetch OHLCV (Open, High, Low, Close, Volume) candle data for a symbol. "
            "Used for candlestick pattern detection, support/resistance identification, "
            "trend structure analysis, and volume profile. Fetch at least 100 bars."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol":    {"type": "string",  "description": "Trading symbol"},
                "exchange":  {"type": "string",  "description": "Exchange (default NSE)"},
                "timeframe": {"type": "string",  "description": "Candle timeframe (default 1h)"},
                "bars":      {"type": "integer", "description": "Number of bars to fetch — 100 to 500 (default 200)"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "analyze_patterns_and_sr",
        "description": (
            "Analyze OHLCV candle data to detect: \n"
            "- Candlestick patterns: Doji, Hammer, Shooting Star, Marubozu, Bullish/Bearish Engulfing, Pin Bar\n"
            "- Support and resistance levels via pivot point clustering\n"
            "- Trend structure (uptrend / downtrend / neutral via SMA-20/50)\n"
            "- Volume surge detection\n"
            "Call this after get_historical_data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ohlcv_data": {
                    "type":        "array",
                    "description": "OHLCV records from get_historical_data (the 'data' field)",
                    "items":       {"type": "object"},
                },
                "lookback_candles": {
                    "type":        "integer",
                    "description": "Number of recent candles to analyse (default 100)",
                },
            },
            "required": ["ohlcv_data"],
        },
    },
    {
        "name": "get_multi_timeframe_analysis",
        "description": (
            "Fetch indicator snapshots across 15m, 1h, 4h, and 1D timeframes for the same symbol. "
            "Multi-timeframe confluence — when all timeframes agree — dramatically increases "
            "signal conviction. Higher-timeframe trend always takes priority."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol":   {"type": "string", "description": "Trading symbol"},
                "exchange": {"type": "string", "description": "Exchange (default NSE)"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "calculate_direction_probability",
        "description": (
            "Synthesize all technical evidence into a directional probability score. "
            "Scoring weights: Trend alignment 30% | Momentum 25% | Candlestick patterns 20% | "
            "Volume 15% | Multi-timeframe confluence 10%. "
            "Returns: BULLISH / BEARISH / NEUTRAL with confidence %, key evidence, "
            "and nearest support/resistance levels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "indicators": {"type": "object", "description": "Full indicator dict from get_indicators"},
                "mtf_data":   {"type": "object", "description": "Multi-timeframe dict from get_multi_timeframe_analysis"},
                "patterns":   {"type": "object", "description": "Pattern analysis dict from analyze_patterns_and_sr"},
                "primary_tf": {"type": "string", "description": "Primary timeframe being analysed (e.g. 1h)"},
            },
            "required": ["indicators"],
        },
    },
]


# ── Tool Executor ─────────────────────────────────────────────────────────────

def make_executor(mcp: TradingViewMCPClient, default_exchange: str = "NSE"):
    """Return a tool-execute function bound to the given MCP client."""

    def execute(tc: ToolCall) -> dict:
        i        = tc.input
        symbol   = i.get("symbol", "")
        exchange = i.get("exchange", default_exchange)
        tf       = i.get("timeframe", "1h")

        if tc.name == "get_indicators":
            return mcp.get_indicators(symbol, exchange, tf)

        if tc.name == "get_historical_data":
            return mcp.get_historical_data(symbol, exchange, tf, int(i.get("bars", 200)))

        if tc.name == "analyze_patterns_and_sr":
            return _analyze_patterns(
                i.get("ohlcv_data", []),
                int(i.get("lookback_candles", 100)),
            )

        if tc.name == "get_multi_timeframe_analysis":
            return _multi_timeframe(mcp, symbol, exchange)

        if tc.name == "calculate_direction_probability":
            return _direction_probability(
                i.get("indicators", {}),
                i.get("mtf_data", {}),
                i.get("patterns", {}),
                i.get("primary_tf", "1h"),
            )

        return {"error": f"Unknown tool: {tc.name}"}

    return execute


# ── Local Analysis: Pattern Detection & S/R ──────────────────────────────────

def _analyze_patterns(ohlcv: list[dict], lookback: int = 100) -> dict:
    if not ohlcv:
        return {"error": "No OHLCV data provided"}

    candles = ohlcv[-lookback:] if len(ohlcv) > lookback else ohlcv
    opens   = [float(c.get("open",   0)) for c in candles]
    highs   = [float(c.get("high",   0)) for c in candles]
    lows    = [float(c.get("low",    0)) for c in candles]
    closes  = [float(c.get("close",  0)) for c in candles]
    volumes = [float(c.get("volume", 0)) for c in candles]

    patterns: list[dict] = []
    n = len(candles)

    for i in range(max(1, n - 10), n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        rng  = h - l
        if rng == 0:
            continue
        body       = abs(c - o)
        body_pct   = body / rng
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        # Doji
        if body_pct < 0.08:
            patterns.append({"name": "Doji", "index": i, "type": "reversal", "price": c})

        # Hammer — bullish reversal at lows
        elif lower_wick > body * 2.0 and upper_wick < body * 0.5 and c >= o:
            patterns.append({"name": "Hammer", "index": i, "type": "bullish_reversal", "price": c})

        # Inverted Hammer / Shooting Star
        elif upper_wick > body * 2.0 and lower_wick < body * 0.5:
            ptype = "bearish_reversal" if c < o else "bullish_reversal"
            name  = "Shooting Star" if c < o else "Inverted Hammer"
            patterns.append({"name": name, "index": i, "type": ptype, "price": c})

        # Marubozu — strong directional move
        elif body_pct > 0.88:
            ptype = "bullish_continuation" if c > o else "bearish_continuation"
            patterns.append({"name": "Marubozu", "index": i, "type": ptype, "price": c})

        # Pin Bar
        elif lower_wick > body * 3.0 or upper_wick > body * 3.0:
            ptype = "bullish_reversal" if lower_wick > upper_wick else "bearish_reversal"
            patterns.append({"name": "Pin Bar", "index": i, "type": ptype, "price": c})

        # 2-candle: Engulfing
        if i > 0:
            po, pc = opens[i - 1], closes[i - 1]
            if pc < po and c > o and o <= pc and c >= po:
                patterns.append({"name": "Bullish Engulfing", "index": i, "type": "bullish_reversal", "price": c})
            elif pc > po and c < o and o >= pc and c <= po:
                patterns.append({"name": "Bearish Engulfing", "index": i, "type": "bearish_reversal", "price": c})

    # ── Support / Resistance via swing pivots ──
    pivot_h, pivot_l = [], []
    for i in range(3, n - 3):
        if highs[i] == max(highs[i - 3: i + 4]):
            pivot_h.append(round(highs[i], 2))
        if lows[i]  == min(lows[i  - 3: i + 4]):
            pivot_l.append(round(lows[i], 2))

    current = closes[-1]
    resistance = sorted({h for h in pivot_h if h > current})[:5]
    support    = sorted({l for l in pivot_l if l < current}, reverse=True)[:5]

    # ── Trend via SMA ──
    sma20 = sum(closes[-20:]) / 20 if n >= 20 else None
    sma50 = sum(closes[-50:]) / 50 if n >= 50 else None
    if sma20 and sma50:
        trend = "uptrend" if current > sma20 > sma50 else ("downtrend" if current < sma20 < sma50 else "neutral")
    else:
        trend = "neutral"

    # ── Volume analysis ──
    avg_vol  = sum(volumes) / len(volumes) if volumes else 0
    last_vol = volumes[-1] if volumes else 0

    return {
        "patterns":          patterns,
        "support_levels":    support,
        "resistance_levels": resistance,
        "trend":             trend,
        "current_price":     round(current, 2),
        "sma_20":            round(sma20, 2) if sma20 else None,
        "sma_50":            round(sma50, 2) if sma50 else None,
        "volume_surge":      last_vol > avg_vol * 1.5,
        "avg_volume":        round(avg_vol),
        "last_volume":       round(last_vol),
    }


# ── Local Analysis: Multi-Timeframe ──────────────────────────────────────────

def _multi_timeframe(mcp: TradingViewMCPClient, symbol: str, exchange: str) -> dict:
    timeframes = ["15m", "1h", "4h", "1D"]
    result: dict[str, dict] = {}
    for tf in timeframes:
        try:
            raw  = mcp.get_indicators(symbol, exchange, tf)
            inds = raw.get("indicators", raw)
            result[tf] = {
                "rsi":            inds.get("RSI") or inds.get("RSI[1]"),
                "macd_hist":      inds.get("MACD.hist"),
                "macd_signal":    inds.get("MACD.signal"),
                "ema_20":         inds.get("EMA20"),
                "sma_200":        inds.get("SMA200"),
                "close":          inds.get("close"),
                "adx":            inds.get("ADX"),
                "bb_upper":       inds.get("BB.upper"),
                "bb_lower":       inds.get("BB.lower"),
                "recommendation": inds.get("Recommend.All"),  # -1 strong sell → +1 strong buy
            }
        except Exception as exc:
            result[tf] = {"error": str(exc)}
    return {"symbol": symbol, "exchange": exchange, "timeframes": result}


# ── Local Analysis: Direction Probability ────────────────────────────────────

def _direction_probability(
    indicators: dict,
    mtf_data:   dict,
    patterns:   dict,
    primary_tf: str,
) -> dict:
    score  = 0.0
    weight = 0.0
    reasons: list[str] = []

    inds  = indicators.get("indicators", indicators)
    close = _f(inds.get("close", 0))

    # ── 1. Trend alignment — 30% ──────────────────────────────────────────────
    ema20  = _f(inds.get("EMA20"))
    sma50  = _f(inds.get("SMA50"))
    sma200 = _f(inds.get("SMA200"))
    trend_score, trend_n = 0.0, 0

    if close and ema20:
        trend_n += 1
        if close > ema20:
            trend_score += 1; reasons.append(f"Price {close:.1f} > EMA20 {ema20:.1f} (bullish)")
        else:
            trend_score -= 1; reasons.append(f"Price {close:.1f} < EMA20 {ema20:.1f} (bearish)")

    if close and sma50:
        trend_n += 1
        if close > sma50:
            trend_score += 1; reasons.append(f"Price above SMA50 {sma50:.1f}")
        else:
            trend_score -= 1; reasons.append(f"Price below SMA50 {sma50:.1f}")

    if close and sma200:
        trend_n += 1
        if close > sma200:
            trend_score += 1; reasons.append(f"Price above SMA200 {sma200:.1f} (long-term bullish)")
        else:
            trend_score -= 1; reasons.append(f"Price below SMA200 {sma200:.1f} (long-term bearish)")

    if trend_n:
        score  += (trend_score / trend_n) * 0.30
        weight += 0.30

    # ── 2. Momentum — 25% ────────────────────────────────────────────────────
    rsi       = _f(inds.get("RSI") or inds.get("RSI[1]"))
    macd_hist = _f(inds.get("MACD.hist"))
    stoch_k   = _f(inds.get("Stoch.K"))
    mom_score, mom_n = 0.0, 0

    if rsi is not None:
        mom_n += 1
        if rsi < 30:
            mom_score += 1.5; reasons.append(f"RSI oversold {rsi:.1f} (strong bullish)")
        elif rsi < 45:
            mom_score += 0.4; reasons.append(f"RSI weak {rsi:.1f} (mild bullish bias)")
        elif rsi > 70:
            mom_score -= 1.5; reasons.append(f"RSI overbought {rsi:.1f} (strong bearish)")
        elif rsi > 58:
            mom_score -= 0.4; reasons.append(f"RSI elevated {rsi:.1f} (mild bearish bias)")
        else:
            reasons.append(f"RSI neutral {rsi:.1f}")

    if macd_hist is not None:
        mom_n += 1
        if macd_hist > 0:
            mom_score += 0.8; reasons.append(f"MACD histogram +{macd_hist:.4f} (bullish momentum)")
        else:
            mom_score -= 0.8; reasons.append(f"MACD histogram {macd_hist:.4f} (bearish momentum)")

    if stoch_k is not None:
        mom_n += 1
        if stoch_k < 20:
            mom_score += 0.6; reasons.append(f"Stochastic oversold {stoch_k:.1f}")
        elif stoch_k > 80:
            mom_score -= 0.6; reasons.append(f"Stochastic overbought {stoch_k:.1f}")

    if mom_n:
        score  += (mom_score / (mom_n * 1.5)) * 0.25
        weight += 0.25

    # ── 3. Volume — 15% ──────────────────────────────────────────────────────
    if patterns.get("volume_surge"):
        trend = patterns.get("trend", "neutral")
        if trend == "uptrend":
            score  += 0.15; weight += 0.15
            reasons.append("Volume surge confirms uptrend (bullish)")
        elif trend == "downtrend":
            score  -= 0.15; weight += 0.15
            reasons.append("Volume surge confirms downtrend (bearish)")

    # ── 4. Candlestick patterns — 20% ────────────────────────────────────────
    recent_patterns = [p for p in patterns.get("patterns", []) if p.get("index", 0) >= len(patterns.get("patterns", [])) - 4]
    bulls = sum(1 for p in recent_patterns if "bullish" in p.get("type", ""))
    bears = sum(1 for p in recent_patterns if "bearish" in p.get("type", ""))
    if bulls > bears:
        score  += 0.20; weight += 0.20
        reasons.append(f"Bullish patterns: {', '.join(p['name'] for p in recent_patterns if 'bullish' in p.get('type',''))}")
    elif bears > bulls:
        score  -= 0.20; weight += 0.20
        reasons.append(f"Bearish patterns: {', '.join(p['name'] for p in recent_patterns if 'bearish' in p.get('type',''))}")

    # ── 5. Multi-timeframe confluence — 10% ──────────────────────────────────
    tf_bulls, tf_bears = 0, 0
    for tf_inds in mtf_data.get("timeframes", {}).values():
        rec = _f(tf_inds.get("recommendation"))
        if rec is not None:
            if rec > 0.1:
                tf_bulls += 1
            elif rec < -0.1:
                tf_bears += 1
    total_tfs = tf_bulls + tf_bears
    if total_tfs:
        weight += 0.10
        if tf_bulls > tf_bears:
            score += (tf_bulls / total_tfs) * 0.10
            reasons.append(f"MTF confluence: {tf_bulls}/{total_tfs} timeframes bullish")
        elif tf_bears > tf_bulls:
            score -= (tf_bears / total_tfs) * 0.10
            reasons.append(f"MTF confluence: {tf_bears}/{total_tfs} timeframes bearish")

    # ── Classify ──────────────────────────────────────────────────────────────
    if weight == 0:
        direction, confidence = "NEUTRAL", 50
    else:
        norm       = score / weight          # normalised [-1, 1]
        confidence = int(abs(norm) * 50 + 50)
        confidence = min(confidence, 95)
        if norm > 0.15:
            direction = "BULLISH"
        elif norm < -0.15:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

    current_price     = patterns.get("current_price") or close
    support_levels    = patterns.get("support_levels", [])
    resistance_levels = patterns.get("resistance_levels", [])

    return {
        "direction":         direction,
        "confidence_pct":    confidence,
        "raw_score":         round(score, 4),
        "reasoning":         reasons,
        "current_price":     current_price,
        "near_support":      support_levels[0]    if support_levels    else None,
        "near_resistance":   resistance_levels[0] if resistance_levels else None,
        "support_levels":    support_levels[:4],
        "resistance_levels": resistance_levels[:4],
        "primary_timeframe": primary_tf,
    }


def _f(v) -> Optional[float]:
    """Safe float conversion — returns None if value is absent or not numeric."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional technical analyst specialising in deep market \
analysis for Indian equity and derivatives markets (NSE/BSE). You have access to \
real-time TradingView data via tool calls.

## Analytical Workflow

**Step 1 — Primary Indicators**
Call `get_indicators` for the requested symbol and timeframe. Extract:
- Trend: EMA20/50/200 alignment, price relative to key MAs
- Momentum: RSI level + divergence, MACD histogram direction, Stochastic zone
- Volatility: ATR (absolute volatility), Bollinger Band width (squeeze vs expansion)
- Strength: ADX >25 = strong trend; ADX <20 = ranging market

**Step 2 — Historical Pattern Analysis**
Call `get_historical_data` (200 bars), then `analyze_patterns_and_sr`.
Identify recent candlestick patterns, support/resistance clusters, and trend structure.

**Step 3 — Multi-Timeframe Confluence**
Call `get_multi_timeframe_analysis` to check alignment across 15m, 1h, 4h, 1D.
Higher timeframe agreement multiplies conviction significantly.

**Step 4 — Direction Synthesis**
Call `calculate_direction_probability` with all gathered data.
This returns a scored directional bias with confidence percentage.

## Output Format

```
### Technical Analysis: [SYMBOL] | [TIMEFRAME]
**Direction: BULLISH/BEARISH/NEUTRAL | Confidence: XX%**

**Current Price:** ₹XXXX

#### Trend Structure
[EMA/SMA positioning, trend description]

#### Momentum Signals
[RSI, MACD, Stochastic with actual values]

#### Candlestick Patterns
[Recent patterns detected, what they imply]

#### Support & Resistance
- Resistance: [level 1], [level 2], [level 3]
- Support:    [level 1], [level 2], [level 3]

#### Multi-Timeframe View
[15m / 1h / 4h / 1D — agree or diverge?]

#### Price Direction Outlook
[Clear directional statement, confidence, primary drivers]

#### Key Levels
- Bullish above: [breakout level]
- Bearish below: [breakdown level]
- Invalidation:  [level that invalidates bias]
```

## Rules
- Always call the tools to fetch real data — never fabricate indicator numbers or price levels.
- If a tool returns an error, note it and continue with the data that was successfully retrieved.
- Work with whatever data is available; partial data is better than no analysis.
- When signals conflict, state which takes priority and why.
- Specify actual price levels returned by tools, not vague descriptions.
- Distinguish intraday vs positional outlook where relevant.
- Do not provide buy/sell/investment recommendations.
"""


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_symbol(
    symbol:        str,
    timeframe:     str = "1h",
    exchange:      str = "NSE",
    provider_name: Optional[str] = None,
    model:         Optional[str] = None,
    mcp_server:    str = "mcp-tradingview",
    verbose:       bool = True,
) -> str:
    """
    Run deep technical analysis on a symbol. Returns the full analysis string.
    Importable for use by other agents (e.g. WhatsApp webhook).
    """
    mcp      = TradingViewMCPClient(server_command=mcp_server)
    provider = get_provider(provider_name=provider_name, model=model, max_tokens=8192)

    if verbose:
        console.print(Panel(
            f"[bold cyan]TradingView Technical Analysis Agent[/bold cyan]\n"
            f"Symbol: [yellow]{symbol}[/yellow]  |  Timeframe: [yellow]{timeframe}[/yellow]  |  "
            f"Exchange: [yellow]{exchange}[/yellow]\n"
            f"Provider: [green]{provider_info()}[/green]",
            border_style="cyan",
        ))

    user_message = (
        f"Perform a comprehensive technical analysis for {symbol} on {exchange} "
        f"using the {timeframe} timeframe as the primary chart. "
        f"Use all available tools to collect indicators, historical OHLCV data, "
        f"candlestick patterns, multi-timeframe confluence, and compute the "
        f"directional probability. State clearly whether the price is likely to "
        f"move BULLISH, BEARISH, or stay NEUTRAL, with your confidence level and "
        f"the specific levels that confirm or invalidate the bias."
    )

    def on_tool_call(tc: ToolCall):
        if verbose:
            args_str = ", ".join(f"{k}={v}" for k, v in tc.input.items())
            console.print(f"[dim]  → {tc.name}({args_str})[/dim]")

    result = provider.run(
        system=SYSTEM_PROMPT,
        user_message=user_message,
        tools=TOOLS,
        execute_fn=make_executor(mcp, default_exchange=exchange),
        on_tool_call=on_tool_call,
    )

    if verbose:
        console.print(Panel(
            Markdown(result),
            title=f"[bold green]Analysis: {symbol} ({timeframe})[/bold green]",
            border_style="green",
        ))

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TradingView Technical Analysis Agent — deep TA with price direction",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("symbol",
        help="Symbol to analyse (e.g. NIFTY, RELIANCE, HDFCBANK)")
    parser.add_argument("--timeframe", "-t", default="1h",
        help="Primary timeframe: 1m|5m|15m|30m|1h|4h|1D|1W  (default: 1h)")
    parser.add_argument("--exchange", "-e", default="NSE",
        help="Exchange: NSE|BSE|NASDAQ|NYSE|MCX  (default: NSE)")
    parser.add_argument("--provider", "-p", choices=SUPPORTED_PROVIDERS,
        help="LLM provider (overrides LLM_PROVIDER env var)")
    parser.add_argument("--model", "-m", default=None,
        help="Model override  (e.g. claude-opus-4-6, gpt-4o, gemini-2.0-flash)")
    parser.add_argument("--mcp-server", default="mcp-tradingview",
        help="MCP server command  (default: mcp-tradingview)")
    parser.add_argument("--quiet", "-q", action="store_true",
        help="Suppress progress output — print final analysis only")

    args = parser.parse_args()

    analyze_symbol(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        exchange=args.exchange,
        provider_name=args.provider,
        model=args.model,
        mcp_server=args.mcp_server,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
