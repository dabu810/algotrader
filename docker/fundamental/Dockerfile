FROM python:3.12-slim

LABEL description="Fundamental Analysis Agent — web research, scoring, WhatsApp notifications"

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
        twilio

COPY fundamental_agent.py \
     fundamental_data.py \
     whatsapp_notifier.py \
     model_provider.py \
     ./

ENTRYPOINT ["python3", "fundamental_agent.py"]
CMD ["--help"]
