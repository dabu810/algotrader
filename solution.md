# Claude Trading Agents — End-to-End Solution

AI-powered trading toolkit for Indian markets (NSE/BSE) with two autonomous agents:
1. **F&O Signal Agent** — intraday options trading signals for Nifty / Bank Nifty
2. **Fundamental Analysis Agent** — deep-dive factual research on any NSE stock, delivered via WhatsApp

Both agents support four LLM providers: **Anthropic (Claude)**, **OpenAI (GPT)**, **Google (Gemini)**, and **Mistral** — switchable via a single `.env` variable.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interfaces                          │
│  Terminal CLI          WhatsApp (Twilio)        Webhook Server  │
└────────┬───────────────────┬───────────────────────┬───────────┘
         │                   │                       │
         ▼                   ▼                       ▼
┌─────────────────┐  ┌───────────────┐  ┌────────────────────────┐
│ fo_signal_agent │  │ whatsapp_     │  │ whatsapp_webhook.py    │
│      .py        │  │ notifier.py   │  │ (Flask, port 5001)     │
└────────┬────────┘  └───────┬───────┘  └────────────┬───────────┘
         │                   │                        │
         ▼                   ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│               fundamental_agent.py                              │
│  (analyze_stock — importable by webhook or run from CLI)        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    model_provider.py                            │
│  BaseProvider → AnthropicProvider / OpenAIProvider /            │
│               GeminiProvider / MistralProvider                  │
│  Unified tool-use loop · web_search · web_fetch                 │
└─────────────────────────────────────────────────────────────────┘
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────┐   ┌──────────────────┐  ┌───────────────────────┐
│ strategies  │   │ fundamental_data │  │ market_data.py        │
│    .py      │   │      .py         │  │ (MarketContext models) │
│ (OI/Vol/    │   │ (scoring engine) │  └───────────────────────┘
│  Tech/Time) │   └──────────────────┘
└─────────────┘
```

---

## File Reference

| File | Purpose |
|------|---------|
| `model_provider.py` | Unified LLM abstraction — Anthropic, OpenAI, Gemini, Mistral |
| `fo_signal_agent.py` | F&O intraday signal agent (CLI) |
| `fundamental_agent.py` | Stock fundamental research agent (CLI + importable) |
| `whatsapp_webhook.py` | Flask webhook server — receives WhatsApp messages via Twilio |
| `whatsapp_notifier.py` | Twilio messaging helper with chunking |
| `market_data.py` | Market context data models and sample data builder |
| `strategies.py` | Strategy calculation functions (OI, volatility, technicals, timing) |
| `fundamental_data.py` | Fundamental scoring engine (5-component, 0–10 scale) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment variables |

---

## Quick Start

### 1. Clone and set up environment

```bash
cd claude_trading_agents
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
# Choose your LLM provider
LLM_PROVIDER=anthropic

# Set the matching API key
ANTHROPIC_API_KEY=sk-ant-...

# For WhatsApp (only needed for the webhook server)
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
```

---

## Agent 1 — F&O Signal Agent

Analyzes live NSE option chain + technicals and generates 1–3 high-confidence intraday F&O trade signals.

### How it works

1. Loads `MarketContext` (option chain, VIX, technicals, session timing)
2. Calls four analysis tools in sequence via the LLM:
   - `analyze_open_interest` — PCR, max pain, OI buildup/unwinding
   - `analyze_volatility` — VIX regime, IV rank, buy-vs-sell-premium bias
   - `analyze_technicals` — VWAP, RSI, ORB, EMA trend
   - `analyze_session_timing` — current window, expiry-day rules
3. For each identified setup, calls `calculate_trade_parameters` for exact lot sizing, SL, targets
4. Returns structured signals

### Run

```bash
# Default provider from .env
python fo_signal_agent.py

# Custom capital and instrument
python fo_signal_agent.py --capital 300000 --instrument BANKNIFTY

# Switch provider via CLI flag
python fo_signal_agent.py --provider openai --model gpt-4o
python fo_signal_agent.py --provider gemini --instrument FINNIFTY
python fo_signal_agent.py --provider mistral

# Raw output for piping
python fo_signal_agent.py --json-output > signals.txt
```

### Signal output format

```
Signal Type: LONG CALL
Confidence:  MEDIUM
Instrument:  NIFTY 23100 CE
Entry Range: 18–22
Stop Loss:   10 (premium)
T1: 35  |  T2: 50
Risk-Reward: 1:2.5
Max Lots:    4 (for ₹5L capital)
Rationale:   Above VWAP, OI buildup at 23000 CE, VIX stable
Timing:      Morning session, exit before 2:30 PM
```

### Strategies covered

| Strategy | When triggered |
|----------|---------------|
| Long Call / Long Put | Directional ORB breakout, RSI momentum |
| ATM Straddle Sell | VIX < 13, IV Rank < 30, range-bound |
| Iron Condor | IV Rank < 20, flat PCR, midday session |
| Bull Call Spread / Bear Put Spread | Moderate directional bias |
| Long Straddle / Strangle | Pre-event, VIX > 18 |
| Gap-and-Go | Large gap-up/down on open |
| OI Shift Trap | Sudden OI reversal detection |

---

## Agent 2 — Fundamental Analysis Agent

Researches any NSE/BSE stock using live web data (Screener.in, Moneycontrol, NSE, Economic Times) and produces a structured, factual report — **no buy/sell recommendations**.

### How it works

1. Searches for quarterly results, annual financials, recent news
2. Fetches Screener.in for comprehensive ratios
3. Calls `score_fundamentals` with all metrics found
4. Generates a WhatsApp-formatted report

### Scoring engine (5 components)

| Component | Weight | Metrics used |
|-----------|--------|-------------|
| Valuation | 25% | P/E vs sector, P/B, EV/EBITDA, dividend yield |
| Profitability | 25% | ROE, ROCE, net margin, operating margin |
| Growth | 25% | Revenue CAGR 3Y, profit CAGR 3Y, YoY growth |
| Balance Sheet | 15% | D/E ratio, current ratio, interest coverage, FCF |
| Management | 10% | Promoter holding, pledge %, FII/DII trends |

Each component scores 0–10; composite = weighted average.

### Run from CLI

```bash
# Single stock
python fundamental_agent.py RELIANCE

# Multiple stocks
python fundamental_agent.py INFY TCS HDFCBANK WIPRO

# Switch provider
python fundamental_agent.py --provider openai BAJFINANCE
python fundamental_agent.py --provider gemini --model gemini-2.0-flash ZOMATO
```

### Sample output (WhatsApp format)

```
📊 *FUNDAMENTAL SNAPSHOT — RELIANCE*
━━━━━━━━━━━━━━━━━━━━━

💼 *Business Overview*
Reliance Industries is India's largest private sector company...

📈 *Financial Metrics*
• Market Cap: ₹19,50,000 Cr | Sector: Conglomerate
• CMP: ₹2,890 | P/E: 28x | Sector P/E: 25x
...

📊 *Fundamental Quality Scores*
• Valuation: 6.5/10
• Profitability: 7.8/10
• Growth: 7.2/10
• Balance Sheet: 6.9/10
• Management: 8.1/10
• *Overall: 7.3/10*
```

---

## WhatsApp Integration — Bidirectional

Users send a stock name via WhatsApp → analysis arrives back in ~60–90 seconds.

### Flow

```
User WhatsApp ──► Twilio ──► ngrok ──► Flask /webhook
                                            │
                                    Immediate TwiML ack:
                                    "🔍 Researching RELIANCE..."
                                            │
                                    Daemon thread starts
                                            │
                                    fundamental_agent.analyze_stock()
                                            │
                                    Twilio REST API
                                            │
                    User WhatsApp ◄── Full analysis (chunked if > 3500 chars)
```

### Setup — Step by step

**1. Twilio sandbox activation**

```
Go to: console.twilio.com
→ Messaging → Try it out → Send a WhatsApp message
→ Send "join <keyword>" from your phone to +1 415 523 8886
```

**2. Start the webhook server**

```bash
python whatsapp_webhook.py --no-validate    # local dev (skip signature check)
python whatsapp_webhook.py                  # production (validates Twilio signature)
python whatsapp_webhook.py --port 5001 --debug
```

**3. Expose with ngrok**

```bash
ngrok http 5001
# Copy the https URL, e.g.: https://abc123.ngrok.io
```

**4. Set Twilio webhook URL**

```
Twilio Console → Messaging → Sandbox settings
→ "When a message comes in": https://abc123.ngrok.io/webhook  (POST)
```

**5. Test**

Send any of these from your phone:
```
RELIANCE
Infosys
analyse HDFC Bank
tell me about tata motors
```

### Supported message formats

The webhook recognises 80+ company name aliases:

| User sends | Resolved symbol |
|-----------|----------------|
| `RELIANCE` | RELIANCE |
| `reliance industries` | RELIANCE |
| `hdfc bank` | HDFCBANK |
| `analyse tata motors` | TATAMOTORS |
| `infosys` | INFY |
| `sbi` | SBIN |
| `hi` / `help` | Shows usage guide |

### Rate limiting

- Per-phone-number cooldown: **120 seconds** between requests
- In-progress lock: one analysis at a time per number

### Health check

```bash
curl http://localhost:5001/health
# {"status": "ok", "in_progress": 0}
```

---

## Multi-Model Provider System

All agents use a unified `model_provider.py` abstraction. Switch providers without changing any agent code.

### Configuration

**.env file:**
```env
LLM_PROVIDER=anthropic   # or openai / gemini / mistral
LLM_MODEL=claude-opus-4-6  # optional — overrides the provider default
```

**CLI flag:**
```bash
python fo_signal_agent.py --provider gemini --model gemini-2.0-flash
python fundamental_agent.py --provider openai NIFTY
```

### Provider defaults

| Provider | Default model | API key env var |
|----------|--------------|----------------|
| `anthropic` | `claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `gemini` | `gemini-2.0-flash` | `GOOGLE_API_KEY` |
| `mistral` | `mistral-large-latest` | `MISTRAL_API_KEY` |

### Web search per provider

| Provider | Web search method |
|----------|------------------|
| Anthropic | Server-side `web_search_20260209` (Anthropic-hosted, no extra key) |
| OpenAI | DuckDuckGo (`duckduckgo-search`) + `httpx` for page fetch |
| Gemini | DuckDuckGo + `httpx` |
| Mistral | DuckDuckGo + `httpx` |

### How tool definitions work

All tools are defined in **canonical format** using the `parameters` key (OpenAI-style JSON Schema). `model_provider.py` converts internally to each provider's native format:

```python
# Canonical tool definition (used in agent code)
{
    "name": "score_fundamentals",
    "description": "Compute fundamental quality scores...",
    "parameters": {
        "type": "object",
        "properties": {
            "pe_ratio": {"type": "number"},
            ...
        }
    }
}

# Converted to Anthropic format automatically:  input_schema key
# Converted to OpenAI/Mistral format:           {"type": "function", "function": {...}}
# Converted to Gemini format:                   FunctionDeclaration objects
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_PROVIDER` | No | `anthropic` (default) / `openai` / `gemini` / `mistral` |
| `LLM_MODEL` | No | Override default model for chosen provider |
| `ANTHROPIC_API_KEY` | If using Anthropic | Claude API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `GOOGLE_API_KEY` | If using Gemini | Google AI Studio API key |
| `MISTRAL_API_KEY` | If using Mistral | Mistral API key |
| `TWILIO_ACCOUNT_SID` | WhatsApp only | From Twilio console |
| `TWILIO_AUTH_TOKEN` | WhatsApp only | From Twilio console |
| `TWILIO_WHATSAPP_FROM` | WhatsApp only | `whatsapp:+14155238886` (sandbox) |
| `WHATSAPP_TO` | CLI notify flow | Your number e.g. `whatsapp:+919876543210` |

---

## Dependencies

```
anthropic>=0.40.0       Claude API (Anthropic provider)
openai>=1.0.0           GPT API (OpenAI provider)
google-genai>=0.5.0     Gemini API (Google provider)
mistralai>=1.0.0        Mistral API (Mistral provider)
duckduckgo-search>=6.0  Free web search for non-Anthropic providers
httpx>=0.27.0           Web page fetching for non-Anthropic providers
twilio>=9.0.0           WhatsApp messaging
flask>=3.0.0            Webhook server
python-dotenv>=1.0.0    .env loading
rich>=13.0.0            Terminal formatting
```

Install all:
```bash
pip install -r requirements.txt
```

---

## Common Issues

**"API key not set" error**

The `LLM_PROVIDER` in `.env` must match an API key. If `LLM_PROVIDER=openai` then `OPENAI_API_KEY` must be set.

**WhatsApp messages not arriving**

1. Check ngrok is running and the URL is set in Twilio sandbox settings
2. Check `python whatsapp_webhook.py` console for errors
3. Verify Twilio sandbox activation (must have texted "join ..." from your phone)
4. Run with `--no-validate` during local dev to skip signature checks

**Analysis takes > 90 seconds**

Normal for Anthropic with web search enabled (server-side web browsing). For faster results use `--provider openai` or `--provider gemini`. Analysis depth may differ.

**"duckduckgo-search not installed"**

Run `pip install duckduckgo-search httpx`. Required for OpenAI / Gemini / Mistral providers.

**WhatsApp message truncated**

Messages over 3500 chars are automatically split into multiple sequential messages with a 1-second delay between each.

---

## Disclaimer

This software is for **educational purposes only**. The F&O signals and fundamental scores are AI-generated and must not be treated as financial advice. F&O trading involves substantial risk of loss. The fundamental analysis contains factual data only — no buy/sell/hold recommendations are made. Always verify data from official sources. Not SEBI-registered investment advice. Use at your own risk.
