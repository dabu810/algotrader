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

    # ── Fallback: tradingview_scraper ─────────────────────────────────────────

    def _fallback_call(self, tool: str, args: dict) -> dict:
        symbol    = args.get("symbol", "")
        exchange  = args.get("exchange", "NSE")
        timeframe = args.get("timeframe", "1h")

        try:
            if tool in ("get_indicators", "get_specific_indicators"):
                return _scraper_indicators(symbol, exchange, timeframe)
            if tool == "get_historical_data":
                return _scraper_history(symbol, exchange, timeframe, int(args.get("n_bars", 200)))
            return {"error": f"No fallback implemented for tool: {tool}"}
        except ImportError:
            return {
                "error": (
                    "Neither MCP server nor tradingview-scraper is installed.\n"
                    "Install one of:\n"
                    "  pip install mcp-tradingview-server mcp\n"
                    "  pip install tradingview-scraper"
                )
            }
        except Exception as exc:
            return {"error": f"Fallback error: {exc}"}


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


def _scraper_indicators(symbol: str, exchange: str, timeframe: str) -> dict:
    from tradingview_scraper.analysis.indicators import Indicators  # type: ignore
    data = Indicators().scrape(symbols=[symbol], exchange=exchange, timeframe=timeframe)
    if data:
        return {"symbol": symbol, "exchange": exchange, "timeframe": timeframe, "indicators": data[0]}
    return {"error": "tradingview_scraper returned no data", "symbol": symbol}


def _scraper_history(symbol: str, exchange: str, timeframe: str, bars: int) -> dict:
    from tradingview_scraper.charts.history import History  # type: ignore
    data = History().get_history(symbol=symbol, exchange=exchange, timeframe=timeframe, n_bars=bars)
    return {"symbol": symbol, "exchange": exchange, "timeframe": timeframe, "data": data}
