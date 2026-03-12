FROM python:3.12-slim

LABEL description="F&O Intraday Signal Agent — OI, PCR, VIX, VWAP, technical signals"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential \
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
        httpx

COPY fo_signal_agent.py strategies.py market_data.py model_provider.py ./

ENTRYPOINT ["python3", "fo_signal_agent.py"]
CMD ["--help"]
