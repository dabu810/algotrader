FROM python:3.12-slim

LABEL description="TradingView Technical Analysis Agent — deep TA with price direction prediction via MCP"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install core deps; mcp-tradingview-server and tradingview-scraper are optional —
# the agent falls back gracefully if neither is available.
RUN pip install --no-cache-dir \
        anthropic \
        python-dotenv \
        rich \
        openai \
        google-genai \
        mistralai \
        duckduckgo-search \
        httpx \
        mcp \
    && pip install --no-cache-dir mcp-tradingview-server 2>/dev/null || echo "mcp-tradingview-server not available — fallback mode" \
    && pip install --no-cache-dir tradingview-scraper 2>/dev/null || echo "tradingview-scraper not available"

COPY tradingview_agent.py \
     tradingview_mcp_client.py \
     model_provider.py \
     ./

# Verify the MCP server binary is on PATH (installed by mcp-tradingview-server)
RUN which mcp-tradingview 2>/dev/null && echo "MCP server: OK" || echo "MCP server: not found (fallback will be used)"

ENTRYPOINT ["python3", "tradingview_agent.py"]
CMD ["--help"]
