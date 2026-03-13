FROM python:3.12-slim

LABEL description="Claude Trading Agents — Streamlit Dashboard UI"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
        anthropic \
        python-dotenv \
        rich \
        openai \
        google-genai \
        mistralai \
        duckduckgo-search \
        httpx \
        twilio \
        flask \
        streamlit \
        tradingview_ta \
        yfinance \
        mcp \
    && (pip install --no-cache-dir mcp-tradingview-server 2>/dev/null \
        || pip install --no-cache-dir "git+https://github.com/bidouilles/mcp-tradingview-server.git" 2>/dev/null \
        || echo "[INFO] mcp-tradingview-server unavailable — tradingview_ta fallback will be used")

# Copy all agent source + UI files
COPY *.py ./
COPY pages/ ./pages/

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
