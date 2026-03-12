"""TradingView Technical Analysis Agent page."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
from dotenv import load_dotenv
load_dotenv()

from model_provider import SUPPORTED_PROVIDERS, provider_info, ToolCall

st.set_page_config(page_title="TradingView TA Agent", page_icon="📡", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .tool-log {
        background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
        padding: 12px 16px; font-family: monospace; font-size: 0.82rem;
        color: #8b949e; max-height: 200px; overflow-y: auto;
    }
    .direction-bull  { color: #3fb950; font-size: 1.4rem; font-weight: 700; }
    .direction-bear  { color: #f85149; font-size: 1.4rem; font-weight: 700; }
    .direction-neut  { color: #d29922; font-size: 1.4rem; font-weight: 700; }
    .conf-badge {
        display: inline-block; border-radius: 20px; padding: 4px 14px;
        font-weight: 600; font-size: 0.9rem; margin-left: 10px;
    }
    .disclaimer {
        background: #1c1005; border: 1px solid #7d4e00; border-radius: 6px;
        padding: 12px 16px; color: #d29922; font-size: 0.82rem; margin-top: 24px;
    }
    div[data-testid="stButton"] > button {
        background-color: #238636; color: white; border: none;
        border-radius: 6px; font-weight: 600; padding: 0.5rem 2rem; font-size: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"]
EXCHANGES  = ["NSE", "BSE", "NASDAQ", "NYSE", "MCX", "CRYPTO"]

with st.sidebar:
    st.markdown("## ⚙️ Settings")
    provider = st.selectbox(
        "LLM Provider",
        options=SUPPORTED_PROVIDERS,
        index=SUPPORTED_PROVIDERS.index(os.environ.get("LLM_PROVIDER", "anthropic")),
    )
    model_override = st.text_input("Model (optional)", placeholder="e.g. gemini-2.0-flash")
    st.divider()
    st.markdown("**TradingView MCP Server**")
    mcp_cmd = st.text_input(
        "MCP server command",
        value=os.environ.get("TRADINGVIEW_MCP_SERVER", "mcp-tradingview"),
        help="Installed via: pip install mcp-tradingview-server",
    )
    st.divider()
    st.caption(f"Active: `{provider_info()}`")
    st.divider()
    st.markdown("**Quick symbols**")
    QUICK_SYMS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "HDFCBANK",
                  "INFY", "TCS", "TATAMOTORS", "BAJFINANCE"]
    cols = st.columns(2)
    for i, sym in enumerate(QUICK_SYMS):
        with cols[i % 2]:
            if st.button(sym, key=f"qs_{sym}", use_container_width=True):
                st.session_state["tv_symbol"] = sym

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("## 📡 TradingView Technical Analysis Agent")
st.markdown(
    "Deep technical analysis using 70+ TradingView indicators, candlestick pattern detection, "
    "S&R levels, and multi-timeframe confluence. Predicts price direction with a confidence score."
)

# ── Inputs ────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    symbol = st.text_input(
        "Symbol",
        value=st.session_state.get("tv_symbol", "NIFTY"),
        placeholder="e.g. NIFTY, RELIANCE, HDFCBANK",
        key="tv_symbol",
    ).upper().strip()
with col2:
    timeframe = st.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index("1h"))
with col3:
    exchange = st.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index("NSE"))

col_btn, col_desc = st.columns([1, 3])
with col_btn:
    run = st.button("📡 Analyse", use_container_width=True)
with col_desc:
    st.markdown(
        f"Symbol: **{symbol}** &nbsp;|&nbsp; "
        f"Timeframe: **{timeframe}** &nbsp;|&nbsp; "
        f"Exchange: **{exchange}** &nbsp;|&nbsp; "
        f"Provider: **{provider}**",
        unsafe_allow_html=True,
    )

# ── Execution ─────────────────────────────────────────────────────────────────
if run:
    if not symbol:
        st.warning("Please enter a symbol.")
        st.stop()

    os.environ["LLM_PROVIDER"] = provider
    if model_override:
        os.environ["LLM_MODEL"] = model_override
    elif "LLM_MODEL" in os.environ:
        del os.environ["LLM_MODEL"]

    TOOL_LABELS = {
        "get_indicators":               "📊 Fetching indicators",
        "get_historical_data":          "📉 Fetching OHLCV data",
        "analyze_patterns_and_sr":      "🕯️ Detecting patterns & S/R",
        "get_multi_timeframe_analysis": "🔀 Multi-timeframe analysis",
        "calculate_direction_probability": "🎯 Computing direction score",
    }

    progress_ph = st.empty()
    tool_log: list[str] = []

    def on_tool_call(tc: ToolCall):
        label = TOOL_LABELS.get(tc.name, f"🔧 {tc.name}")
        args  = ", ".join(f"{k}={v}" for k, v in tc.input.items() if k != "ohlcv_data")
        entry = f"✅ {label}" + (f" <span style='color:#555'>({args})</span>" if args else "")
        tool_log.append(entry)
        progress_ph.markdown(
            '<div class="tool-log">' + "<br>".join(tool_log) + "</div>",
            unsafe_allow_html=True,
        )

    with st.spinner(f"Analysing {symbol} on {timeframe}… ~45-90 seconds"):
        try:
            from tradingview_agent import analyze_symbol
            result = analyze_symbol(
                symbol=symbol,
                timeframe=timeframe,
                exchange=exchange,
                provider_name=provider,
                model=model_override or None,
                mcp_server=mcp_cmd,
                verbose=False,
            )
            st.session_state["tv_result"] = {
                "text": result, "symbol": symbol, "tf": timeframe
            }
        except EnvironmentError as e:
            st.error(f"Configuration error: {e}")
            st.stop()
        except Exception as e:
            msg = str(e)
            if "401" in msg or "authentication_error" in msg or "invalid x-api-key" in msg or "invalid_api_key" in msg:
                provider_key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                                "gemini": "GOOGLE_API_KEY", "mistral": "MISTRAL_API_KEY"}.get(provider, "API key")
                st.error(f"Invalid API key for **{provider}**. Check `{provider_key}` in your `.env` file.")
                st.stop()
            st.error(f"Agent error: {e}")
            st.stop()

    progress_ph.empty()

# ── Results display ───────────────────────────────────────────────────────────
if "tv_result" in st.session_state:
    res    = st.session_state["tv_result"]
    text   = res["text"]
    sym    = res["symbol"]
    tf     = res["tf"]

    # Try to extract direction headline for a visual badge
    import re
    dir_match  = re.search(r"Direction[:\s*_]+(BULLISH|BEARISH|NEUTRAL)", text, re.IGNORECASE)
    conf_match = re.search(r"Confidence[:\s*_]+(\d+)%", text, re.IGNORECASE)

    if dir_match:
        direction  = dir_match.group(1).upper()
        confidence = conf_match.group(1) if conf_match else "—"
        dir_css = {"BULLISH": "direction-bull", "BEARISH": "direction-bear"}.get(direction, "direction-neut")
        badge_bg = {"BULLISH": "#0e3d35", "BEARISH": "#3d0e14"}.get(direction, "#3d2e00")

        col_d, col_c, col_s = st.columns(3)
        col_d.markdown(
            f'<p class="{dir_css}">{"▲" if direction=="BULLISH" else "▼" if direction=="BEARISH" else "◆"} {direction}</p>',
            unsafe_allow_html=True
        )
        col_c.metric("Confidence", f"{confidence}%")
        col_s.metric("Analysed", f"{sym} / {tf}")

        st.divider()

    st.markdown(f"### 📋 Analysis: {sym} ({tf})")
    st.markdown(text)

    col_dl, col_clr = st.columns([1, 5])
    with col_dl:
        st.download_button(
            "⬇️ Download",
            data=text,
            file_name=f"ta_{sym}_{tf}.txt",
            mime="text/plain",
        )
    with col_clr:
        if st.button("🗑️ Clear", key="tv_clear"):
            del st.session_state["tv_result"]
            st.rerun()

# ── MCP server status ─────────────────────────────────────────────────────────
with st.expander("ℹ️ TradingView MCP Server Setup", expanded=False):
    st.markdown("""
    The TradingView agent connects to [mcp-tradingview-server](https://github.com/bidouilles/mcp-tradingview-server)
    for live indicator and OHLCV data.

    **Install:**
    ```bash
    pip install mcp-tradingview-server mcp
    ```

    **Verify:**
    ```bash
    mcp-tradingview --help
    ```

    If the MCP server is not installed, the agent automatically falls back to
    `tradingview-scraper` (`pip install tradingview-scraper`).
    """)

# ── Disclaimer ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
⚠️ <strong>Disclaimer:</strong> AI-generated technical analysis for <strong>informational purposes only</strong>.
Not investment advice. Past patterns do not guarantee future price movements.
Always conduct your own research.
</div>
""", unsafe_allow_html=True)
