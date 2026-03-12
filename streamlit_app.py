"""
Claude Trading Agents — Dashboard
===================================
Streamlit home page. Agent pages live in pages/.
Run: streamlit run streamlit_app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Claude Trading Agents",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Hide Streamlit default header padding */
    .block-container { padding-top: 2rem; }

    /* Agent cards */
    .agent-card {
        background: #1a1d2e;
        border-radius: 12px;
        padding: 24px;
        border-left: 4px solid #00d4aa;
        margin-bottom: 16px;
        height: 100%;
    }
    .agent-card h3 { color: #00d4aa; margin-top: 0; }
    .agent-card p  { color: #c0c0c0; font-size: 0.92rem; line-height: 1.6; }
    .agent-card .badge {
        display: inline-block;
        background: #0e3d35;
        color: #00d4aa;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.78rem;
        margin: 2px 2px 8px 0;
    }

    /* Tool call log */
    .tool-log {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 12px 16px;
        font-family: monospace;
        font-size: 0.82rem;
        color: #8b949e;
        max-height: 220px;
        overflow-y: auto;
    }

    /* Result box */
    .result-panel {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 20px;
    }

    /* Disclaimer */
    .disclaimer {
        background: #1c1005;
        border: 1px solid #7d4e00;
        border-radius: 6px;
        padding: 12px 16px;
        color: #d29922;
        font-size: 0.82rem;
        margin-top: 24px;
    }

    /* Run button */
    div[data-testid="stButton"] > button {
        background-color: #238636;
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        padding: 0.5rem 2rem;
        font-size: 1rem;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #2ea043;
    }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📈 Claude Trading Agents")
st.markdown(
    "AI-powered market analysis for Indian equities. "
    "Powered by [Anthropic Claude](https://anthropic.com) with multi-model support."
)
st.divider()


# ── Agent Cards ───────────────────────────────────────────────────────────────
col2, col3 = st.columns(2)

with col2:
    st.markdown("""
    <div class="agent-card">
        <h3>🔍 Fundamental Analysis</h3>
        <span class="badge">NSE/BSE</span>
        <span class="badge">Live Web Data</span>
        <span class="badge">Scoring</span>
        <p>
            Researches any Indian stock using live data from Screener.in, Moneycontrol &amp; NSE.
            Scores valuation, profitability, growth, balance sheet &amp; management quality.
            Pure factual data — no buy/sell recommendations.
        </p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Fundamental Agent →", key="goto_fund"):
        st.switch_page("pages/2_Fundamental.py")

with col3:
    st.markdown("""
    <div class="agent-card">
        <h3>📡 TradingView TA Agent</h3>
        <span class="badge">70+ Indicators</span>
        <span class="badge">Multi-Timeframe</span>
        <span class="badge">MCP</span>
        <p>
            Deep technical analysis via TradingView MCP server. Detects candlestick patterns,
            support/resistance levels, and multi-timeframe confluence to predict price direction
            with a confidence score.
        </p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open TradingView Agent →", key="goto_tv"):
        st.switch_page("pages/3_TradingView.py")


# ── Quick Setup ───────────────────────────────────────────────────────────────
st.divider()
with st.expander("⚙️ Setup & Configuration", expanded=False):
    st.markdown("""
    #### 1. API Keys (`.env` file)
    ```ini
    LLM_PROVIDER=anthropic        # anthropic | openai | gemini | mistral
    ANTHROPIC_API_KEY=sk-ant-...  # or OPENAI_API_KEY / GOOGLE_API_KEY / MISTRAL_API_KEY
    ```

    #### 2. TradingView MCP Server (for TradingView Agent)
    ```bash
    pip install mcp-tradingview-server mcp
    ```

    #### 3. WhatsApp Notifications (optional)
    ```ini
    TWILIO_ACCOUNT_SID=ACxxx...
    TWILIO_AUTH_TOKEN=...
    TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
    WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
    ```

    #### 4. Run the dashboard
    ```bash
    streamlit run streamlit_app.py
    ```
    """)


# ── Disclaimer ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
⚠️ <strong>Disclaimer:</strong> All analysis is AI-generated and for <strong>educational and informational purposes only</strong>.
This is not SEBI-registered investment advice. F&O trading involves substantial risk of loss.
Always conduct your own research and consult a qualified financial advisor before trading.
</div>
""", unsafe_allow_html=True)
