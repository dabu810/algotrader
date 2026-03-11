"""
F&O Trading Signal Agent
========================
Multi-model support: Anthropic (Claude), OpenAI (GPT), Google (Gemini), Mistral.
The application admin switches providers via .env or CLI flag.

Usage:
    python fo_signal_agent.py                          # Default provider from .env
    python fo_signal_agent.py --capital 300000
    python fo_signal_agent.py --provider openai --model gpt-4o
    python fo_signal_agent.py --provider gemini --instrument BANKNIFTY
"""

import sys
import json
import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from market_data import MarketContext, build_sample_market_context
from strategies import (
    analyze_open_interest,
    analyze_volatility,
    analyze_technicals,
    analyze_session_timing,
    calculate_trade_parameters,
)
from model_provider import get_provider, ToolCall, SUPPORTED_PROVIDERS, provider_info

load_dotenv()

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions  (canonical "parameters" format)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "analyze_open_interest",
        "description": (
            "Analyze the NSE option chain open interest data to identify key support/resistance levels, "
            "put-call ratio (PCR), institutional positioning, max pain, and OI buildup/unwinding signals. "
            "Call this first to understand where institutions are positioned."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "analyze_volatility",
        "description": (
            "Analyze India VIX, IV Rank, and implied volatility to determine whether to buy or sell premium. "
            "Returns strategy bias (buy vs sell premium), IV crush risk, and ATM IV data. "
            "Call this to determine which type of strategy is most appropriate given current volatility regime."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "analyze_technicals",
        "description": (
            "Analyze technical indicators including VWAP positioning, RSI, EMA trend, Opening Range Breakout (ORB) status, "
            "and volume confirmation. Returns directional bias (bullish/bearish/neutral) and all key price levels. "
            "Call this to determine directional setup."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "analyze_session_timing",
        "description": (
            "Analyze the current trading session timing to determine which strategies are applicable right now, "
            "identify any expiry day dynamics, and flag time-based warnings. "
            "Call this to ensure strategy recommendations are appropriate for the current time window."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calculate_trade_parameters",
        "description": (
            "Calculate precise trade parameters including position sizing, stop-loss levels, profit targets, "
            "risk-reward ratio, and capital required for a specific trade setup. "
            "Call this once per trade signal to get exact execution parameters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "strategy_type": {
                    "type": "string",
                    "enum": ["BUY_CALL", "BUY_PUT", "SELL_STRADDLE", "SELL_STRANGLE",
                             "BULL_CALL_SPREAD", "BEAR_PUT_SPREAD", "IRON_CONDOR"],
                    "description": "The F&O strategy type to calculate parameters for"
                },
                "direction": {
                    "type": "string",
                    "enum": ["BULLISH", "BEARISH", "NEUTRAL"],
                    "description": "Directional bias of the trade"
                },
                "entry_strike": {
                    "type": "integer",
                    "description": "The option strike price to enter at"
                },
                "entry_premium": {
                    "type": "number",
                    "description": "The premium/price of the option or net debit/credit of the strategy"
                },
                "capital_available": {
                    "type": "number",
                    "description": "Total capital available for trading in INR"
                }
            },
            "required": ["strategy_type", "direction", "entry_strike", "entry_premium", "capital_available"]
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert F&O (Futures & Options) intraday trading signal generator for Indian markets (NSE).
You specialize in Nifty and Bank Nifty derivatives with deep expertise in:
- Option chain analysis and OI interpretation
- India VIX and implied volatility analysis
- Technical analysis (VWAP, RSI, ORB, EMA)
- Put-Call Ratio analysis
- Expiry day strategies
- Risk management and position sizing

Your job is to analyze the current market data using the available tools and generate clear, actionable trading signals.

ANALYSIS PROCESS:
1. First, call ALL four analysis tools (OI, volatility, technicals, session timing) to build a complete picture
2. Synthesize the data to identify 1-3 high-confidence trade setups
3. For each trade setup, call calculate_trade_parameters to get exact entry/exit levels
4. Present your final signals in a clear, structured format

SIGNAL FORMAT (for each trade):
- Signal Type: LONG CALL / LONG PUT / SELL STRADDLE / IRON CONDOR / etc.
- Confidence: HIGH / MEDIUM / LOW (only recommend HIGH or MEDIUM)
- Instrument & Strike
- Entry Range (premium)
- Stop Loss (premium level)
- Targets (T1, T2)
- Risk-Reward Ratio
- Max Lots (for given capital)
- Rationale (2-3 key reasons)
- Timing Notes

RULES:
- Only generate signals with confidence MEDIUM or higher
- Always provide a stop loss — no trade without a stop
- Never recommend naked short options on expiry day without strong rationale
- Flag IV crush risk clearly when relevant events are mentioned
- If market conditions are unclear or contradictory, say so and recommend staying out
- Include a brief market summary before the signals
- End with risk management reminders

Be direct, precise, and actionable. Traders need clear signals, not academic analysis."""


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────────────────────

def make_executor(ctx: MarketContext, capital: float):
    """Return an execute_fn closure bound to market context and capital."""
    def execute_fn(tc: ToolCall) -> dict:
        if tc.name == "analyze_open_interest":
            return analyze_open_interest(ctx)
        elif tc.name == "analyze_volatility":
            return analyze_volatility(ctx)
        elif tc.name == "analyze_technicals":
            return analyze_technicals(ctx)
        elif tc.name == "analyze_session_timing":
            return analyze_session_timing(ctx)
        elif tc.name == "calculate_trade_parameters":
            inp = dict(tc.input)
            inp["capital_available"] = capital   # always inject current capital
            return calculate_trade_parameters(
                ctx=ctx,
                strategy_type=inp["strategy_type"],
                direction=inp["direction"],
                entry_strike=inp["entry_strike"],
                entry_premium=inp["entry_premium"],
                capital_available=inp.get("capital_available", capital),
            )
        return {"error": f"Unknown tool: {tc.name}"}
    return execute_fn


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def display_header(ctx: MarketContext, info: str):
    console.print()
    console.print(Panel(
        f"[bold cyan]F&O Signal Agent[/bold cyan] | "
        f"[yellow]{ctx.instrument}[/yellow] @ [green]{ctx.spot_price:,.2f}[/green] | "
        f"VIX: [red]{ctx.india_vix}[/red] | "
        f"Session: [blue]{ctx.session}[/blue] | "
        f"[dim]Provider: {info}[/dim]"
        + (" [bold red]⚡ EXPIRY DAY[/bold red]" if ctx.is_expiry_day else ""),
        title="[bold]NSE F&O Trading Signal Generator[/bold]",
        border_style="cyan"
    ))
    if ctx.notes:
        console.print(f"[dim]Context: {ctx.notes}[/dim]")
    console.print()


def on_tool_call(tc: ToolCall):
    icons = {
        "analyze_open_interest":  "📊",
        "analyze_volatility":     "⚡",
        "analyze_technicals":     "📈",
        "analyze_session_timing": "⏰",
        "calculate_trade_parameters": "🎯",
    }
    icon = icons.get(tc.name, "🔧")
    console.print(f"  {icon} [dim]{tc.name}[/dim] → [green]running...[/green]")


def display_signal_output(text: str):
    console.print()
    console.print(Panel(
        text,
        title="[bold green]📡 TRADING SIGNALS[/bold green]",
        border_style="green",
        padding=(1, 2)
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Main agent function
# ─────────────────────────────────────────────────────────────────────────────

def run_signal_agent(
    ctx: MarketContext,
    capital: float = 500_000,
    provider_name: str | None = None,
    model: str | None = None,
) -> str:
    """
    Run the F&O signal generation agent.

    Args:
        ctx: Complete market context
        capital: Trading capital in INR
        provider_name: Override LLM_PROVIDER env var (anthropic/openai/gemini/mistral)
        model: Override LLM_MODEL env var

    Returns:
        Final signal text
    """
    provider = get_provider(provider_name=provider_name, model=model, max_tokens=4096)
    info = provider_info()

    display_header(ctx, info)
    console.print("[bold]Analyzing market data...[/bold]")

    user_message = (
        f"Analyze the current {ctx.instrument} F&O market and generate trading signals.\n\n"
        f"Market Snapshot:\n"
        f"- Instrument: {ctx.instrument}\n"
        f"- Spot: {ctx.spot_price}\n"
        f"- Futures: {ctx.futures_price}\n"
        f"- Time: {ctx.current_time} ({ctx.session} session)\n"
        f"- India VIX: {ctx.india_vix}\n"
        f"- IV Rank: {ctx.iv_rank}%\n"
        f"- Expiry Day: {ctx.is_expiry_day} ({ctx.expiry_type})\n"
        f"- Expiry: {ctx.option_chain.expiry}\n"
        f"- ATM Strike: {ctx.option_chain.atm_strike}\n"
        f"- Lot Size: {ctx.lot_size}\n"
        f"- Trading Capital: ₹{capital:,.0f}\n"
        f"- Notes: {ctx.notes or 'None'}\n\n"
        "Please use all available tools to perform thorough analysis, "
        "then provide 1-3 high-confidence trading signals with complete entry/exit parameters."
    )

    execute_fn = make_executor(ctx, capital)
    return provider.run(SYSTEM_PROMPT, user_message, TOOLS, execute_fn, on_tool_call=on_tool_call)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="F&O Trading Signal Agent for Indian Markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python fo_signal_agent.py\n"
            "  python fo_signal_agent.py --capital 300000\n"
            "  python fo_signal_agent.py --provider openai --model gpt-4o\n"
            "  python fo_signal_agent.py --provider gemini --instrument BANKNIFTY"
        )
    )
    parser.add_argument("--capital", type=float, default=500_000,
                        help="Trading capital in INR (default: 5,00,000)")
    parser.add_argument("--instrument", type=str, default="NIFTY",
                        choices=["NIFTY", "BANKNIFTY", "FINNIFTY"],
                        help="Instrument to analyze (default: NIFTY)")
    parser.add_argument("--provider", type=str, choices=SUPPORTED_PROVIDERS,
                        help="LLM provider (default: from LLM_PROVIDER env var or 'anthropic')")
    parser.add_argument("--model", type=str,
                        help="Model override (default: from LLM_MODEL env var or provider default)")
    parser.add_argument("--json-output", action="store_true",
                        help="Output raw signal text only (for piping)")
    args = parser.parse_args()

    ctx = build_sample_market_context()
    ctx.instrument = args.instrument

    if not args.json_output:
        console.print(f"\n[dim]Capital: ₹{args.capital:,.0f} | Instrument: {args.instrument}[/dim]")

    try:
        signals = run_signal_agent(
            ctx,
            capital=args.capital,
            provider_name=args.provider,
            model=args.model,
        )

        if args.json_output:
            print(signals)
        else:
            display_signal_output(signals)
            console.print()
            console.print(Panel(
                "[bold red]⚠ DISCLAIMER[/bold red]\n"
                "These are AI-generated signals for educational purposes only. "
                "F&O trading involves substantial risk. Past performance does not guarantee future results. "
                "Always verify signals with your own analysis. Use strict stop-losses. "
                "Never risk more than you can afford to lose.\n\n"
                "[dim]Not SEBI registered investment advice.[/dim]",
                border_style="red",
                padding=(0, 2)
            ))

    except EnvironmentError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
