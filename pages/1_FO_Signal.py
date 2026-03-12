"""F&O Signal Agent page."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
from dotenv import load_dotenv
load_dotenv()

from model_provider import SUPPORTED_PROVIDERS, provider_info, ToolCall
from market_data import build_sample_market_context

st.set_page_config(page_title="F&O Signal Agent", page_icon="📊", layout="wide")

# ── Shared styles (duplicated so each page is standalone) ─────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .tool-log {
        background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
        padding: 12px 16px; font-family: monospace; font-size: 0.82rem;
        color: #8b949e; max-height: 200px; overflow-y: auto;
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
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    provider = st.selectbox(
        "LLM Provider",
        options=SUPPORTED_PROVIDERS,
        index=SUPPORTED_PROVIDERS.index(os.environ.get("LLM_PROVIDER", "anthropic")),
        help="Override LLM_PROVIDER env var",
    )
    model_override = st.text_input(
        "Model (optional)",
        placeholder="e.g. claude-opus-4-6, gpt-4o",
        help="Leave blank to use provider default",
    )
    st.divider()
    st.markdown("**Capital**")
    capital = st.number_input(
        "Trading Capital (₹)",
        min_value=50_000,
        max_value=10_000_000,
        value=500_000,
        step=50_000,
        format="%d",
    )
    st.markdown("**Instrument**")
    instrument = st.selectbox("Instrument", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
    st.divider()
    st.caption(f"Active: `{provider_info()}`")

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("## 📊 F&O Signal Agent")
st.markdown(
    "Generates intraday F&O signals for NSE derivatives using OI analysis, "
    "India VIX, VWAP, RSI, and session timing."
)

# ── Market snapshot preview ───────────────────────────────────────────────────
ctx = build_sample_market_context()
ctx.instrument = instrument

with st.expander("📋 Market Snapshot (sample data)", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Instrument", ctx.instrument)
    c2.metric("Spot Price", f"₹{ctx.spot_price:,.2f}")
    c3.metric("India VIX", ctx.india_vix)
    c4.metric("IV Rank", f"{ctx.iv_rank}%")
    c1.metric("Session", ctx.session)
    c2.metric("Expiry Day", "Yes ⚡" if ctx.is_expiry_day else "No")
    c3.metric("ATM Strike", ctx.option_chain.atm_strike)
    c4.metric("PCR", ctx.option_chain.put_call_ratio)
    if ctx.notes:
        st.info(f"📌 {ctx.notes}")

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col_btn, col_info = st.columns([1, 3])
with col_btn:
    run = st.button("🚀 Generate Signals", use_container_width=True)
with col_info:
    st.markdown(
        f"Capital: **₹{capital:,.0f}** &nbsp;|&nbsp; "
        f"Instrument: **{instrument}** &nbsp;|&nbsp; "
        f"Provider: **{provider}**",
        unsafe_allow_html=True,
    )

# ── Execution ─────────────────────────────────────────────────────────────────
if run:
    ctx.instrument = instrument

    TOOL_ICONS = {
        "analyze_open_interest":      "📊 Open Interest",
        "analyze_volatility":         "⚡ Volatility / VIX",
        "analyze_technicals":         "📈 Technicals",
        "analyze_session_timing":     "⏰ Session Timing",
        "calculate_trade_parameters": "🎯 Trade Parameters",
    }

    progress_placeholder = st.empty()
    tool_calls_done: list[str] = []

    def on_tool_call(tc: ToolCall):
        label = TOOL_ICONS.get(tc.name, f"🔧 {tc.name}")
        tool_calls_done.append(f"✅ {label}")
        lines = "\n".join(tool_calls_done)
        progress_placeholder.markdown(
            f'<div class="tool-log">{lines.replace(chr(10), "<br>")}</div>',
            unsafe_allow_html=True,
        )

    with st.spinner("Analysing market data… this takes ~30 seconds"):
        try:
            from fo_signal_agent import run_signal_agent
            result = run_signal_agent(
                ctx=ctx,
                capital=capital,
                provider_name=provider,
                model=model_override or None,
            )
            st.session_state["fo_result"] = result
        except EnvironmentError as e:
            st.error(f"Configuration error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Agent error: {e}")
            st.stop()

    progress_placeholder.empty()

# ── Result display ────────────────────────────────────────────────────────────
if "fo_result" in st.session_state:
    st.markdown("### 📡 Trading Signals")
    st.markdown(st.session_state["fo_result"])

    col_dl, col_clr = st.columns([1, 5])
    with col_dl:
        st.download_button(
            "⬇️ Download",
            data=st.session_state["fo_result"],
            file_name=f"fo_signals_{instrument}.txt",
            mime="text/plain",
        )
    with col_clr:
        if st.button("🗑️ Clear", key="fo_clear"):
            del st.session_state["fo_result"]
            st.rerun()

# ── Disclaimer ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
⚠️ <strong>Disclaimer:</strong> AI-generated signals for <strong>educational purposes only</strong>.
Not SEBI-registered advice. F&O trading carries substantial risk. Always use stop-losses.
Never risk capital you cannot afford to lose.
</div>
""", unsafe_allow_html=True)
