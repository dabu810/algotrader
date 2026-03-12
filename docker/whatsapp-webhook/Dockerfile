FROM python:3.12-slim

LABEL description="WhatsApp Webhook Server — receives messages, triggers fundamental analysis, replies"

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
        httpx \
        twilio \
        flask \
        gunicorn

# Copy all source — webhook imports fundamental_agent + whatsapp_notifier + model_provider
COPY whatsapp_webhook.py \
     fundamental_agent.py \
     fundamental_data.py \
     whatsapp_notifier.py \
     model_provider.py \
     ./

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/health')"

# gunicorn: 1 worker + 4 threads keeps daemon background threads in a single process
CMD ["gunicorn", \
     "--workers", "1", \
     "--threads", "4", \
     "--bind", "0.0.0.0:5001", \
     "--timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "whatsapp_webhook:app"]
