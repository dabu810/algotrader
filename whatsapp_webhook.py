"""
WhatsApp → Fundamental Analysis Webhook Server
=============================================
Listens for incoming WhatsApp messages via Twilio, extracts stock symbols,
runs the fundamental analysis agent, and replies with the result.

HOW IT WORKS:
  User sends "RELIANCE" or "analyse infosys" via WhatsApp
      → Twilio POSTs to this server's /webhook endpoint
      → Server immediately replies "Analysing..." (TwiML response)
      → Background thread runs Claude fundamental analysis (~60-90s)
      → Result sent back to user's WhatsApp via Twilio API

SETUP:
  1. Fill .env (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM,
     ANTHROPIC_API_KEY)
  2. pip3 install flask twilio anthropic
  3. Start server:         python whatsapp_webhook.py
  4. Expose to internet:   ngrok http 5001
  5. Set Twilio webhook:   https://<ngrok-url>/webhook  (POST)
     Console → Messaging → Sandbox settings → When a message comes in

Run:
    python whatsapp_webhook.py
    python whatsapp_webhook.py --port 5001 --debug
"""

import os
import re
import sys
import logging
import threading
import argparse
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, request, Response

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("webhook")

# ─────────────────────────────────────────────────────────────────────────────
# Stock symbol helpers
# ─────────────────────────────────────────────────────────────────────────────

# Common company name → NSE symbol aliases
SYMBOL_ALIASES: dict[str, str] = {
    "reliance industries": "RELIANCE", "reliance":         "RELIANCE",
    "tcs": "TCS", "tata consultancy": "TCS", "tata consultancy services": "TCS",
    "infosys": "INFY", "infy": "INFY",
    "wipro": "WIPRO",
    "hcl": "HCLTECH", "hcl tech": "HCLTECH", "hcl technologies": "HCLTECH",
    "tech mahindra": "TECHM",
    "hdfc bank": "HDFCBANK", "hdfcbank": "HDFCBANK",
    "icici bank": "ICICIBANK", "icicibank": "ICICIBANK",
    "sbi": "SBIN", "state bank": "SBIN", "state bank of india": "SBIN",
    "axis bank": "AXISBANK", "axisbank": "AXISBANK",
    "kotak bank": "KOTAKBANK", "kotak mahindra bank": "KOTAKBANK",
    "bajaj finance": "BAJFINANCE", "bajfinance": "BAJFINANCE",
    "bajaj finserv": "BAJAJFINSV",
    "hdfc life": "HDFCLIFE",
    "sbi life": "SBILIFE",
    "l&t": "LT", "larsen": "LT", "larsen and toubro": "LT",
    "itc": "ITC",
    "hindustan unilever": "HINDUNILVR", "hul": "HINDUNILVR",
    "asian paints": "ASIANPAINT",
    "maruti": "MARUTI", "maruti suzuki": "MARUTI",
    "tata motors": "TATAMOTORS",
    "m&m": "M&M", "mahindra": "M&M", "mahindra and mahindra": "M&M",
    "hero motocorp": "HEROMOTOCO", "hero": "HEROMOTOCO",
    "bajaj auto": "BAJAJ-AUTO",
    "tvs motor": "TVSMOTOR",
    "sun pharma": "SUNPHARMA", "sunpharma": "SUNPHARMA",
    "cipla": "CIPLA",
    "dr reddy": "DRREDDY", "dr. reddy": "DRREDDY", "drreddy": "DRREDDY",
    "divi's": "DIVISLAB", "divis": "DIVISLAB",
    "tata steel": "TATASTEEL",
    "jsw steel": "JSWSTEEL",
    "hindalco": "HINDALCO",
    "vedanta": "VEDL",
    "coal india": "COALINDIA",
    "ntpc": "NTPC",
    "power grid": "POWERGRID",
    "ongc": "ONGC", "oil and natural gas": "ONGC",
    "bpcl": "BPCL", "bharat petroleum": "BPCL",
    "ioc": "IOC", "indian oil": "IOC",
    "bharti airtel": "BHARTIARTL", "airtel": "BHARTIARTL",
    "adani enterprises": "ADANIENT",
    "adani ports": "ADANIPORTS",
    "adani green": "ADANIGREEN",
    "adani power": "ADANIPOWER",
    "ultratech cement": "ULTRACEMCO",
    "ambuja cement": "AMBUJACEMENT",
    "acc": "ACC",
    "titan": "TITAN",
    "trent": "TRENT",
    "dmart": "DMART", "avenue supermarts": "DMART",
    "zomato": "ZOMATO",
    "swiggy": "SWIGGY",
    "paytm": "PAYTM",
    "nykaa": "NYKAA",
    "policybazaar": "POLICYBZR", "policy bazaar": "POLICYBZR",
    "pidilite": "PIDILITIND",
    "berger paints": "BERGEPAINT",
    "nestle": "NESTLEIND", "nestle india": "NESTLEIND",
    "britannia": "BRITANNIA",
    "dabur": "DABUR",
    "marico": "MARICO",
    "godrej consumer": "GODREJCP",
    "emami": "EMAMILTD",
}

# NSE symbols: letters (and hyphen), 2–20 chars
_SYMBOL_RE = re.compile(r"\b([A-Z][A-Z0-9&\-]{1,19})\b")

HELP_MESSAGE = (
    "📊 *Fundamental Analysis Bot*\n\n"
    "Send me a stock name or NSE symbol and I'll research it for you.\n\n"
    "*Examples:*\n"
    "• RELIANCE\n"
    "• Infosys\n"
    "• HDFC Bank\n"
    "• analyse tata motors\n\n"
    "_Analysis takes ~60-90 seconds. I'll message you when ready._\n\n"
    "⚠️ _Pure factual data only. Not investment advice._"
)


def parse_stock_symbol(message: str) -> str | None:
    """
    Extract an NSE stock symbol from a freeform WhatsApp message.
    Returns the symbol (uppercase) or None if unrecognisable.
    """
    cleaned = message.strip().lower()

    # Strip common filler words
    for filler in ("analyse", "analyze", "analysis of", "check", "tell me about",
                   "what about", "research", "fundamentals of", "fundas of",
                   "please", "?", "!"):
        cleaned = cleaned.replace(filler, " ")
    cleaned = " ".join(cleaned.split())

    # Try alias lookup first (most reliable)
    if cleaned in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[cleaned]

    # Try substrings from aliases
    for alias, symbol in SYMBOL_ALIASES.items():
        if alias in cleaned:
            return symbol

    # Try direct uppercase extraction (e.g. user typed "RELIANCE" or "INFY")
    upper = message.strip().upper()
    matches = _SYMBOL_RE.findall(upper)
    # Filter out common noise words
    noise = {"THE", "AND", "FOR", "NSE", "BSE", "INDIA", "LTD", "LIMITED",
             "CHECK", "PLEASE", "ME", "ABOUT", "HI", "HELLO", "WHAT", "HOW"}
    candidates = [m for m in matches if m not in noise and len(m) >= 2]
    if candidates:
        return candidates[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting (simple in-memory, per phone number)
# ─────────────────────────────────────────────────────────────────────────────

_in_progress: set[str] = set()          # phone numbers currently being analysed
_last_request: dict[str, datetime] = {} # phone number → last request time
COOLDOWN_SECONDS = 120                  # min gap between requests per number


def _is_rate_limited(phone: str) -> bool:
    last = _last_request.get(phone)
    if last and datetime.now() - last < timedelta(seconds=COOLDOWN_SECONDS):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Background analysis + reply
# ─────────────────────────────────────────────────────────────────────────────

def _analyse_and_reply(from_number: str, symbol: str):
    """
    Runs in a daemon thread: analyses the stock and sends the result back
    to the user's WhatsApp via Twilio API.
    """
    from whatsapp_notifier import send_text_to_whatsapp

    log.info(f"[{from_number}] Starting analysis: {symbol}")
    try:
        from fundamental_agent import analyze_stock
        analysis = analyze_stock(symbol, verbose=False)

        if not analysis:
            analysis = f"Sorry, I couldn't retrieve fundamental data for *{symbol}*. Please check the symbol and try again."

        result = send_text_to_whatsapp(to_number=from_number, text=analysis)
        if result.success:
            log.info(f"[{from_number}] Sent analysis for {symbol} (SID: {result.message_sid})")
        else:
            log.warning(f"[{from_number}] Send failed for {symbol}: {result.error}")

    except Exception as e:
        log.error(f"[{from_number}] Analysis failed for {symbol}: {e}", exc_info=True)
        try:
            from whatsapp_notifier import send_text_to_whatsapp
            send_text_to_whatsapp(
                to_number=from_number,
                text=f"⚠️ Analysis for *{symbol}* failed: {str(e)[:200]}\nPlease try again."
            )
        except Exception:
            pass
    finally:
        _in_progress.discard(from_number)


# ─────────────────────────────────────────────────────────────────────────────
# Twilio TwiML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _twiml_reply(message: str) -> Response:
    """Return a TwiML MessagingResponse with the given message body."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Message>{message}</Message></Response>'
    )
    return Response(xml, mimetype="text/xml")


def _twiml_empty() -> Response:
    """Return an empty TwiML response (no immediate reply)."""
    xml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return Response(xml, mimetype="text/xml")


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)


def create_app(validate_twilio_signature: bool = True) -> Flask:
    """
    Configure and return the Flask app.
    Call this once with the Anthropic client injected via app.config.
    """
    app.config["VALIDATE_SIGNATURE"] = validate_twilio_signature
    return app


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "in_progress": len(_in_progress)}, 200


@app.route("/webhook", methods=["POST"])
def webhook():
    # ── Optional Twilio signature validation ─────────────────────────────────
    if app.config.get("VALIDATE_SIGNATURE", False):
        try:
            from twilio.request_validator import RequestValidator  # type: ignore
            validator = RequestValidator(os.environ.get("TWILIO_AUTH_TOKEN", ""))
            url = request.url
            params = request.form.to_dict()
            sig = request.headers.get("X-Twilio-Signature", "")
            if not validator.validate(url, params, sig):
                log.warning("Invalid Twilio signature — rejected request")
                return Response("Forbidden", status=403)
        except Exception as e:
            log.warning(f"Signature validation error: {e}")

    # ── Parse incoming fields ─────────────────────────────────────────────────
    from_number = request.form.get("From", "").strip()
    body        = request.form.get("Body", "").strip()

    if not from_number or not body:
        return _twiml_empty()

    log.info(f"Incoming from {from_number}: {body!r}")

    # ── Help / greeting ───────────────────────────────────────────────────────
    lower_body = body.lower().strip()
    if lower_body in ("hi", "hello", "help", "start", "?", "menu"):
        return _twiml_reply(HELP_MESSAGE)

    # ── Parse stock symbol ────────────────────────────────────────────────────
    symbol = parse_stock_symbol(body)

    if not symbol:
        return _twiml_reply(
            f"🤔 I couldn't identify a stock symbol in: _{body}_\n\n"
            "Please send the NSE symbol (e.g. *RELIANCE*, *INFY*, *HDFCBANK*) "
            "or the company name (e.g. *Tata Motors*, *HDFC Bank*).\n\n"
            "Send *help* to see examples."
        )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    if from_number in _in_progress:
        return _twiml_reply(
            f"⏳ Analysis already in progress for a previous request.\n"
            "Please wait for that to complete before sending another."
        )

    if _is_rate_limited(from_number):
        remaining = COOLDOWN_SECONDS - int(
            (datetime.now() - _last_request[from_number]).total_seconds()
        )
        return _twiml_reply(
            f"⏳ Please wait {remaining}s before requesting another analysis."
        )

    # ── Mark in progress + start background thread ───────────────────────────
    _in_progress.add(from_number)
    _last_request[from_number] = datetime.now()

    thread = threading.Thread(
        target=_analyse_and_reply,
        args=(from_number, symbol),
        daemon=True
    )
    thread.start()

    # ── Immediate acknowledgement (Twilio requires response within 15s) ───────
    return _twiml_reply(
        f"🔍 Researching *{symbol}*...\n\n"
        "I'm pulling data from Screener.in, Moneycontrol and NSE. "
        "Your analysis will arrive in about *60–90 seconds*. ⏳\n\n"
        "_Pure factual data. Not investment advice._"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="WhatsApp Fundamental Analysis Webhook")
    parser.add_argument("--port",  type=int, default=5001, help="Port to listen on (default: 5001)")
    parser.add_argument("--host",  default="0.0.0.0",      help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--debug", action="store_true",     help="Enable Flask debug mode")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip Twilio signature validation (useful for local testing)")
    args = parser.parse_args()

    if not os.environ.get("TWILIO_ACCOUNT_SID") or not os.environ.get("TWILIO_AUTH_TOKEN"):
        print("WARNING: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set — outbound messages will fail.")

    # Validate LLM provider config at startup so errors surface early
    try:
        from model_provider import get_provider, provider_info
        get_provider()   # throws EnvironmentError if API key missing
        print(f"LLM Provider: {provider_info()}")
    except EnvironmentError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    validate = not args.no_validate
    create_app(validate_twilio_signature=validate)

    print(f"""
╔══════════════════════════════════════════════════════╗
║  WhatsApp Fundamental Analysis Webhook               ║
╠══════════════════════════════════════════════════════╣
║  Listening on  : http://{args.host}:{args.port}
║  Webhook URL   : POST /webhook
║  Signature     : {'DISABLED (--no-validate)' if not validate else 'ENABLED'}
╠══════════════════════════════════════════════════════╣
║  NEXT STEPS:                                         ║
║  1. Run:  ngrok http {args.port}                          ║
║  2. Copy the https URL from ngrok                    ║
║  3. Go to Twilio Console →                          ║
║     Messaging → Sandbox settings →                  ║
║     "When a message comes in" → paste URL + /webhook ║
║  4. Send any stock name to your sandbox WhatsApp #   ║
╚══════════════════════════════════════════════════════╝
""")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
