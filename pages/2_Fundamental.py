"""Fundamental Analysis Agent page."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
from dotenv import load_dotenv
load_dotenv()

from model_provider import SUPPORTED_PROVIDERS, PROVIDER_MODELS, provider_info

st.set_page_config(page_title="Fundamental Analysis", page_icon="🔍", layout="wide")

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
    .symbol-chip {
        display: inline-block; background: #0e3d35; color: #00d4aa;
        border-radius: 4px; padding: 3px 10px; margin: 3px; font-weight: 600;
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
    )
    available_models = PROVIDER_MODELS[provider]
    model_override = st.selectbox("Model", options=available_models, index=0)
    st.divider()
    st.caption(f"Active: `{provider_info()}`")
    st.divider()
    st.markdown("**Popular symbols**")
    POPULAR = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
               "BAJFINANCE", "SBIN", "LT", "TATAMOTORS", "TITAN"]
    for sym in POPULAR:
        if st.button(sym, key=f"quick_{sym}", use_container_width=True):
            st.session_state["fund_symbol_input"] = sym

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("## 🔍 Fundamental Analysis Agent")
st.markdown(
    "Researches Indian stocks using live data from Screener.in, Moneycontrol, and NSE. "
    "Returns factual fundamental data with a scored breakdown — no buy/sell recommendations."
)

# ── Symbol input ──────────────────────────────────────────────────────────────
col_inp, col_btn = st.columns([3, 1])
with col_inp:
    raw_input = st.text_input(
        "Stock symbol or company name",
        value=st.session_state.get("fund_symbol_input", ""),
        placeholder="e.g. RELIANCE  or  INFY, TCS, WIPRO  or  HDFC Bank",
        help="Enter one or more NSE symbols separated by commas, or company names",
        key="fund_symbol_input",
    )
with col_btn:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    run = st.button("🔍 Analyse", use_container_width=True)

# Parse symbols
symbols = [s.strip().upper() for s in raw_input.replace(",", " ").split() if s.strip()]

if symbols:
    chips = " ".join(f'<span class="symbol-chip">{s}</span>' for s in symbols)
    st.markdown(f"Symbols to analyse: {chips}", unsafe_allow_html=True)

# ── Execution ─────────────────────────────────────────────────────────────────
if run:
    if not symbols:
        st.warning("Please enter at least one stock symbol.")
        st.stop()

    # Set provider env var so fundamental_agent picks it up
    os.environ["LLM_PROVIDER"] = provider
    os.environ["LLM_MODEL"] = model_override

    results: dict[str, str] = {}

    for symbol in symbols:
        st.markdown(f"---\n**Analysing {symbol}...**")
        progress_ph = st.empty()
        tool_log: list[str] = []

        def _make_progress(sym: str, ph, log: list):
            def update(name: str, detail: str = ""):
                label = f"🔎 `{name}`" + (f" — {detail[:60]}" if detail else "")
                log.append(label)
                ph.markdown(
                    '<div class="tool-log">' +
                    "<br>".join(log) +
                    "</div>",
                    unsafe_allow_html=True,
                )
            return update

        progress_fn = _make_progress(symbol, progress_ph, tool_log)

        result_ph = st.empty()
        accumulated = ""

        try:
            from fundamental_agent import analyze_stock_streaming

            def _on_tool_call(tc):
                icons = {"web_search": "🔍", "web_fetch": "🌐", "score_fundamentals": "📊"}
                icon  = icons.get(tc.name, "🔧")
                detail = tc.input.get("query") or tc.input.get("url") or tc.input.get("stock_symbol", "")
                entry  = f"{icon} <span style='color:#8b949e'>{str(detail)[:70]}</span>"
                tool_log.append(entry)
                progress_ph.markdown(
                    '<div class="tool-log">' + "<br>".join(tool_log) + "</div>",
                    unsafe_allow_html=True,
                )

            with st.spinner(f"Researching {symbol}…"):
                for chunk in analyze_stock_streaming(
                    stock_symbol=symbol,
                    provider_name=provider,
                    model=model_override,
                    on_tool_call=_on_tool_call,
                ):
                    accumulated += chunk
                    result_ph.markdown(accumulated + "▌")

            result_ph.markdown(accumulated)
            results[symbol] = accumulated or f"No data returned for {symbol}."

        except EnvironmentError as e:
            st.error(f"Configuration error: {e}")
            st.stop()
        except Exception as e:
            msg = str(e)
            if "401" in msg or "authentication_error" in msg or "invalid x-api-key" in msg or "invalid_api_key" in msg:
                provider_key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                                "gemini": "GOOGLE_API_KEY", "mistral": "MISTRAL_API_KEY"}.get(provider, "API key")
                progress_ph.empty()
                st.error(f"Invalid API key for **{provider}**. Open your `.env` file and set a valid `{provider_key}`.")
                st.info("Get your Anthropic API key at https://console.anthropic.com → API Keys")
                st.stop()
            results[symbol] = f"⚠️ Error analysing {symbol}: {e}"

        progress_ph.empty()

    st.session_state["fund_results"] = results

# ── Results display ───────────────────────────────────────────────────────────
if "fund_results" in st.session_state:
    results = st.session_state["fund_results"]

    if len(results) == 1:
        symbol, text = next(iter(results.items()))
        st.markdown(f"### 📋 {symbol} — Fundamental Analysis")
        st.markdown(text)
        st.download_button(
            "⬇️ Download",
            data=text,
            file_name=f"fundamental_{symbol}.txt",
            mime="text/plain",
        )
    else:
        tabs = st.tabs([f"📋 {s}" for s in results])
        for tab, (symbol, text) in zip(tabs, results.items()):
            with tab:
                st.markdown(text)
                st.download_button(
                    f"⬇️ Download {symbol}",
                    data=text,
                    file_name=f"fundamental_{symbol}.txt",
                    mime="text/plain",
                    key=f"dl_{symbol}",
                )

    if st.button("🗑️ Clear results", key="fund_clear"):
        del st.session_state["fund_results"]
        st.rerun()

# ── Disclaimer ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
⚠️ <strong>Disclaimer:</strong> Pure factual data only — no buy/sell/hold recommendations.
AI-generated analysis for <strong>informational purposes</strong>.
Not SEBI-registered investment advice. Verify data independently before making any decisions.
</div>
""", unsafe_allow_html=True)
