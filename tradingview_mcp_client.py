"""
TradingView MCP Client — Loosely Coupled
=========================================
Wraps the bidouilles/mcp-tradingview-server via the MCP Python SDK.
Provides a synchronous interface so the trading agent stays fully sync.

Install the MCP server:
    pip install mcp-tradingview-server

Verify it works:
    mcp-tradingview --help

The client falls back to direct tradingview_scraper calls if the MCP
server is not installed, keeping the agent functional in both environments.

References:
  - Server: https://github.com/bidouilles/mcp-tradingview-server
  - MCP SDK: https://github.com/modelcontextprotocol/python-sdk
"""

import asyncio
import json
import logging
from typing import Optional, Any

log = logging.getLogger(__name__)

DEFAULT_SERVER_COMMAND = "mcp-tradingview"


class TradingViewMCPClient:
    """
    Synchronous MCP client for TradingView technical data.

    Loosely coupled design:
      - Primary path: MCP server via stdio (requires mcp-tradingview-server)
      - Fallback path: direct tradingview_scraper calls (requires tradingview-scraper)
      - Both paths return identical dict structures
    """

    def __init__(
        self,
        server_command: str = DEFAULT_SERVER_COMMAND,
        server_args: Optional[list] = None,
        fallback: bool = True,
    ):
        self._command  = server_command
        self._args     = server_args or []
        self._fallback = fallback
        self._available: Optional[bool] = None  # lazily checked

    # ── Public sync API ───────────────────────────────────────────────────────

    def get_indicators(
        self,
        symbol: str,
        exchange: str = "NSE",
        timeframe: str = "1h",
    ) -> dict:
        """Fetch full TradingView indicator snapshot (70+ indicators)."""
        return self._call("get_indicators", {
            "symbol":    symbol,
            "exchange":  exchange,
            "timeframe": timeframe,
        })

    def get_specific_indicators(
        self,
        symbol: str,
        indicators: list[str],
        exchange: str = "NSE",
        timeframe: str = "1h",
    ) -> dict:
        """Fetch a subset of indicators by name."""
        return self._call("get_specific_indicators", {
            "symbol":     symbol,
            "indicators": indicators,
            "exchange":   exchange,
            "timeframe":  timeframe,
        })

    def get_historical_data(
        self,
        symbol: str,
        exchange: str = "NSE",
        timeframe: str = "1h",
        bars: int = 200,
    ) -> dict:
        """Fetch OHLCV candle data (up to 500 bars)."""
        return self._call("get_historical_data", {
            "symbol":    symbol,
            "exchange":  exchange,
            "timeframe": timeframe,
            "n_bars":    min(bars, 500),
        })

    def is_available(self) -> bool:
        """Probe the MCP server — result is cached after first call."""
        if self._available is None:
            try:
                res = self._run_async(self._async_call("get_indicators", {
                    "symbol": "NIFTY", "exchange": "NSE", "timeframe": "1D"
                }))
                self._available = "error" not in res
            except Exception:
                self._available = False
        return self._available

    # ── Internal routing ──────────────────────────────────────────────────────

    def _call(self, tool: str, args: dict) -> dict:
        try:
            return self._run_async(self._async_call(tool, args))
        except Exception as exc:
            if self._fallback:
                log.warning("MCP unavailable (%s) — using direct fallback", exc)
                return self._fallback_call(tool, args)
            return {"error": str(exc), "tool": tool}

    # ── Async MCP machinery ───────────────────────────────────────────────────

    def _run_async(self, coro: Any) -> Any:
        """Bridge async→sync regardless of whether an event loop is running."""
        try:
            loop = asyncio.get_running_loop()
            # Already inside a running loop (Jupyter / async frameworks)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

    async def _async_call(self, tool: str, arguments: dict) -> dict:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ImportError(
                "mcp SDK not installed. Run: pip install mcp\n"
                "Also install the server: pip install mcp-tradingview-server"
            )

        params = StdioServerParameters(command=self._command, args=self._args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return _parse_mcp_result(result)

    # ── Fallback: tradingview_ta + yfinance ───────────────────────────────────

    def _fallback_call(self, tool: str, args: dict) -> dict:
        symbol    = args.get("symbol", "")
        exchange  = args.get("exchange", "NSE")
        timeframe = args.get("timeframe", "1h")

        if tool in ("get_indicators", "get_specific_indicators"):
            return _ta_indicators(symbol, exchange, timeframe)
        if tool == "get_historical_data":
            return _yf_history(symbol, exchange, timeframe, int(args.get("n_bars", 200)))
        return {"error": f"No fallback implemented for tool: {tool}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_mcp_result(result) -> dict:
    """Extract a dict from an MCP CallToolResult."""
    for content in result.content:
        if hasattr(content, "text"):
            try:
                return json.loads(content.text)
            except json.JSONDecodeError:
                return {"raw": content.text}
    return {"error": "Empty response from MCP server"}


# ── tradingview_ta fallback ───────────────────────────────────────────────────

_TF_MAP = {
    "1m":  "1 minute",  "5m":  "5 minutes",  "15m": "15 minutes",
    "30m": "30 minutes","1h":  "1 hour",     "2h":  "2 hours",
    "4h":  "4 hours",   "1D":  "1 day",      "1W":  "1 week",
}

_SCREENER_MAP = {
    "NSE": "india", "BSE": "india",
    "NASDAQ": "america", "NYSE": "america",
    "MCX": "india",
}


def _ta_indicators(symbol: str, exchange: str, timeframe: str) -> dict:
    try:
        from tradingview_ta import TA_Handler, Interval  # type: ignore
    except ImportError:
        return {"error": "tradingview_ta not installed. Run: pip install tradingview_ta"}

    interval_str = _TF_MAP.get(timeframe, "1 hour")
    screener     = _SCREENER_MAP.get(exchange.upper(), "india")

    # Map interval string to Interval enum
    interval_enum = {
        "1 minute":   Interval.INTERVAL_1_MINUTE,
        "5 minutes":  Interval.INTERVAL_5_MINUTES,
        "15 minutes": Interval.INTERVAL_15_MINUTES,
        "30 minutes": Interval.INTERVAL_30_MINUTES,
        "1 hour":     Interval.INTERVAL_1_HOUR,
        "2 hours":    Interval.INTERVAL_2_HOURS,
        "4 hours":    Interval.INTERVAL_4_HOURS,
        "1 day":      Interval.INTERVAL_1_DAY,
        "1 week":     Interval.INTERVAL_1_WEEK,
    }.get(interval_str, Interval.INTERVAL_1_HOUR)

    try:
        handler = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange.upper(),
            interval=interval_enum,
        )
        analysis = handler.get_analysis()
        indicators = dict(analysis.indicators)
        # Add summary recommendation (-1 strong sell → +1 strong buy)
        summary = analysis.summary
        total = summary.get("BUY", 0) + summary.get("SELL", 0)
        if total:
            indicators["Recommend.All"] = (summary.get("BUY", 0) - summary.get("SELL", 0)) / total
        indicators["close"] = indicators.get("close", indicators.get("Adj.Close"))
        return {
            "symbol":    symbol,
            "exchange":  exchange,
            "timeframe": timeframe,
            "indicators": indicators,
            "summary":   summary,
        }
    except Exception as exc:
        return {"error": f"tradingview_ta error: {exc}", "symbol": symbol}


# ── yfinance OHLCV fallback ───────────────────────────────────────────────────

_YF_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "1h",  # yfinance has no 4h — use 1h
    "1D": "1d", "1W": "1wk",
}

_YF_PERIOD_MAP = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "1h": "730d", "4h": "730d", "1D": "2y", "1W": "5y",
}


_YF_INDEX_MAP = {
    # NSE indices
    "NIFTY":       "^NSEI",
    "NIFTY50":     "^NSEI",
    "NIFTY 50":    "^NSEI",
    "BANKNIFTY":   "^NSEBANK",
    "NIFTYBANK":   "^NSEBANK",
    "FINNIFTY":    "^CNXFIN",
    "MIDCPNIFTY":  "^CNXMIDCAP",
    "NIFTYMIDCAP": "^CNXMIDCAP",
    # BSE indices
    "SENSEX":      "^BSESN",
}


def _yf_ticker(symbol: str, exchange: str) -> str:
    """Convert NSE/BSE symbol to yfinance ticker format."""
    # Check index map first (exchange-agnostic)
    upper = symbol.upper().replace(" ", "")
    if upper in _YF_INDEX_MAP:
        return _YF_INDEX_MAP[upper]
    ex = exchange.upper()
    if ex == "NSE":
        return f"{symbol}.NS"
    if ex == "BSE":
        return f"{symbol}.BO"
    return symbol  # NASDAQ/NYSE symbols work as-is


def _yf_history(symbol: str, exchange: str, timeframe: str, bars: int) -> dict:
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return {"error": "yfinance not installed. Run: pip install yfinance"}

    ticker   = _yf_ticker(symbol, exchange)
    interval = _YF_INTERVAL_MAP.get(timeframe, "1h")
    period   = _YF_PERIOD_MAP.get(timeframe, "730d")

    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return {"error": f"yfinance returned no data for {ticker}", "symbol": symbol}

        df = df.tail(bars)
        records = []
        for ts, row in df.iterrows():
            records.append({
                "time":   ts.isoformat(),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })
        return {
            "symbol":    symbol,
            "exchange":  exchange,
            "timeframe": timeframe,
            "data":      records,
        }
    except Exception as exc:
        return {"error": f"yfinance error: {exc}", "symbol": symbol}
