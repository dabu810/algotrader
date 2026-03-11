"""
Fundamental Analysis Agent for Indian Stocks
=============================================
Multi-model support: Anthropic (Claude), OpenAI (GPT), Google (Gemini), Mistral.
Uses web_search + web_fetch to research stocks and produce pure factual
fundamental analysis (no buy/sell recommendations).

Importable by whatsapp_webhook.py or run directly from CLI.

Usage (CLI):
    python fundamental_agent.py RELIANCE
    python fundamental_agent.py INFY TCS WIPRO
    python fundamental_agent.py --provider openai HDFCBANK
"""

import sys
import json
import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from fundamental_data import score_fundamentals_from_dict
from model_provider import get_provider, ToolCall, SUPPORTED_PROVIDERS, provider_info, execute_web_tool

load_dotenv()

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions  (canonical "parameters" format)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information about an Indian stock. "
            "Use for quarterly results, financials, news, and sector data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch content from a URL. "
            "Use to retrieve pages from Screener.in, Moneycontrol, NSE, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "score_fundamentals",
        "description": (
            "Compute quantitative fundamental quality scores from financial metrics. "
            "Call this after gathering all available data for a stock. "
            "Returns component scores (valuation, profitability, growth, balance sheet, management) "
            "each on a 0-10 scale, plus a composite score. "
            "Use these scores to describe financial quality in your narrative — "
            "do NOT use them to make buy/sell/hold recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stock_symbol":         {"type": "string"},
                "pe_ratio":             {"type": "number"},
                "sector_pe":            {"type": "number"},
                "pb_ratio":             {"type": "number"},
                "ev_to_ebitda":         {"type": "number"},
                "market_cap_cr":        {"type": "number"},
                "dividend_yield":       {"type": "number"},
                "roe":                  {"type": "number"},
                "roce":                 {"type": "number"},
                "net_margin":           {"type": "number"},
                "operating_margin":     {"type": "number"},
                "ebitda_margin":        {"type": "number"},
                "revenue_growth_3y":    {"type": "number"},
                "profit_growth_3y":     {"type": "number"},
                "eps_growth_ttm":       {"type": "number"},
                "revenue_growth_yoy":   {"type": "number"},
                "profit_growth_yoy":    {"type": "number"},
                "debt_to_equity":       {"type": "number"},
                "current_ratio":        {"type": "number"},
                "interest_coverage":    {"type": "number"},
                "free_cash_flow_cr":    {"type": "number"},
                "promoter_holding":     {"type": "number"},
                "promoter_pledge_pct":  {"type": "number"},
                "fii_holding":          {"type": "number"},
                "dii_holding":          {"type": "number"},
            },
            "required": ["stock_symbol"]
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — pure factual analysis, no recommendations
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior fundamental equity research analyst for Indian stock markets (NSE/BSE).
Your role is to provide PURE FACTUAL FUNDAMENTAL ANALYSIS only.

STRICT RULE: Do NOT provide any of the following:
- Buy, Sell, or Hold recommendations
- Price targets or 12-month targets
- Stop loss levels
- Any advisory language ("you should...", "consider buying...", "good time to...")
Only present facts, data, and objective observations.

YOUR RESEARCH PROCESS:
1. Search for the latest quarterly results and annual financials (FY24, FY25)
2. Fetch https://www.screener.in/company/SYMBOL/ for comprehensive metrics
3. Search for recent news and management commentary
4. Search for sector benchmarks and peer comparison data
5. Call score_fundamentals with all metrics you found
6. Write your analysis in WhatsApp-friendly format (see OUTPUT FORMAT)

DATA SOURCES (priority order):
- screener.in/company/SYMBOL — P/E, ROE, growth rates, debt, shareholding
- moneycontrol.com — Quarterly results, news
- nseindia.com — FII/DII holdings, shareholding pattern
- economictimes.com — News, management commentary
- bseindia.com — Official filings
- tickertape.in — Additional ratios

OUTPUT FORMAT (WhatsApp-optimised, use * for bold, _ for italic):
Structure your response exactly like this:

📊 *FUNDAMENTAL SNAPSHOT — [SYMBOL]*
━━━━━━━━━━━━━━━━━━━━━

💼 *Business Overview*
[2-3 lines: what the company does, market position, key business segments]

📈 *Financial Metrics*
• Market Cap: ₹[X] Cr | Sector: [sector]
• CMP: ₹[price] | P/E: [X]x | Sector P/E: [Y]x
• P/B: [X]x | EV/EBITDA: [X]x
• Dividend Yield: [X]%

💹 *Profitability*
• ROE: [X]% | ROCE: [X]%
• Net Margin: [X]% | Operating Margin: [X]%
• Revenue (TTM): ₹[X] Cr

📉 *Growth Trends*
• Revenue CAGR (3Y): [X]% | Profit CAGR (3Y): [X]%
• Revenue Growth (Latest Quarter YoY): [X]%
• Profit Growth (Latest Quarter YoY): [X]%

🏦 *Balance Sheet*
• Debt/Equity: [X] | Current Ratio: [X]
• Interest Coverage: [X]x | Free Cash Flow: ₹[X] Cr

👥 *Shareholding (Latest)*
• Promoters: [X]% (Pledge: [X]%)
• FII: [X]% | DII: [X]%
• Public: [X]%

📊 *Fundamental Quality Scores*
• Valuation: [X]/10
• Profitability: [X]/10
• Growth: [X]/10
• Balance Sheet: [X]/10
• Management: [X]/10
• *Overall: [X]/10*

📰 *Recent Developments*
[3-4 bullet points of latest news, quarterly highlights, management commentary]

⚠️ *Key Areas to Watch*
[3-4 factual risk factors or concerns — no opinion, just facts]

_Data sourced from Screener.in, Moneycontrol, NSE. May not reflect latest intraday price._
_This is not investment advice. Consult a SEBI-registered advisor._

Be precise with numbers. If data is unavailable, write "N/A" rather than estimating."""


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────────────────────

def _make_executor(verbose: bool):
    """Return an execute_fn closure."""
    def execute_fn(tc: ToolCall) -> dict:
        if tc.name == "score_fundamentals":
            scores = score_fundamentals_from_dict(tc.input)
            result = {
                "stock_symbol":        tc.input.get("stock_symbol"),
                "valuation_score":     scores.valuation_score,
                "profitability_score": scores.profitability_score,
                "growth_score":        scores.growth_score,
                "balance_sheet_score": scores.balance_sheet_score,
                "management_score":    scores.management_score,
                "overall_score":       scores.overall_score,
                "score_breakdown": {
                    "Valuation (25%)":      f"{scores.valuation_score}/10",
                    "Profitability (25%)":  f"{scores.profitability_score}/10",
                    "Growth (25%)":         f"{scores.growth_score}/10",
                    "Balance Sheet (15%)":  f"{scores.balance_sheet_score}/10",
                    "Management (10%)":     f"{scores.management_score}/10",
                    "OVERALL":              f"{scores.overall_score}/10",
                },
                "status": "Scoring complete"
            }
            if verbose:
                _display_scores(result)
            return result

        # web_search / web_fetch — used by non-Anthropic providers
        # (Anthropic handles these server-side and won't call execute_fn for them)
        if tc.name in ("web_search", "web_fetch"):
            return execute_web_tool(tc.name, tc.input)

        return {"error": f"Unknown tool: {tc.name}"}
    return execute_fn


# ─────────────────────────────────────────────────────────────────────────────
# Core analysis function — used by both CLI and webhook
# ─────────────────────────────────────────────────────────────────────────────

def analyze_stock(
    stock_symbol: str,
    verbose: bool = True,
    provider_name: str | None = None,
    model: str | None = None,
) -> str:
    """
    Run fundamental analysis for a single stock.
    Returns the full analysis text.

    Args:
        stock_symbol:  NSE symbol e.g. "RELIANCE"
        verbose:       Print progress to console (False when called from webhook)
        provider_name: Override LLM_PROVIDER env var
        model:         Override LLM_MODEL env var
    """
    provider = get_provider(provider_name=provider_name, model=model, max_tokens=8192)
    info = provider_info()

    if verbose:
        console.print(f"\n[bold]Researching [cyan]{stock_symbol}[/cyan] via [dim]{info}[/dim]...[/bold]")

    user_message = (
        f"Perform a comprehensive fundamental analysis of {stock_symbol} (Indian stock, NSE/BSE).\n\n"
        f"Steps:\n"
        f'1. Search: "{stock_symbol} NSE quarterly results FY25 annual report financials"\n'
        f"2. Fetch: https://www.screener.in/company/{stock_symbol}/\n"
        f'3. Search: "{stock_symbol} latest news management commentary 2024 2025"\n'
        f'4. Search: "{stock_symbol} sector PE ratio peer comparison"\n'
        f"5. Call score_fundamentals with all metrics found\n"
        f"6. Write the analysis in the exact WhatsApp format from your instructions\n\n"
        f"Do NOT include any buy/sell/hold opinion or price targets."
    )

    def on_tool_call(tc: ToolCall):
        if not verbose:
            return
        _log_tool(tc.name, tc.input)

    execute_fn = _make_executor(verbose)
    result = provider.run(SYSTEM_PROMPT, user_message, TOOLS, execute_fn, on_tool_call=on_tool_call)
    return result.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers (CLI only)
# ─────────────────────────────────────────────────────────────────────────────

def _log_tool(tool_name: str, tool_input: dict):
    icons = {"web_search": "🔍", "web_fetch": "🌐", "score_fundamentals": "📊"}
    icon = icons.get(tool_name, "🔧")
    if tool_name == "web_search":
        console.print(f"  {icon} [dim]{tool_input.get('query', '')[:75]}[/dim]")
    elif tool_name == "web_fetch":
        console.print(f"  {icon} [dim]{tool_input.get('url', '')[:80]}[/dim]")
    elif tool_name == "score_fundamentals":
        console.print(f"  {icon} [dim]Scoring: {tool_input.get('stock_symbol', '')}[/dim]")
    else:
        console.print(f"  {icon} [dim]{tool_name}[/dim]")


def _display_scores(result: dict):
    table = Table(title=f"Scores: {result.get('stock_symbol', '')}", box=box.SIMPLE)
    table.add_column("Component", style="cyan", min_width=22)
    table.add_column("Score", justify="right")
    breakdown = result.get("score_breakdown", {})
    for k, v in breakdown.items():
        style = "bold white" if k == "OVERALL" else ""
        table.add_row(
            f"[{style}]{k}[/{style}]" if style else k,
            f"[{style}]{v}[/{style}]" if style else v,
        )
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fundamental Analysis Agent — pure factual data, no recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python fundamental_agent.py RELIANCE\n"
            "  python fundamental_agent.py INFY TCS HDFCBANK\n"
            "  python fundamental_agent.py --provider openai BAJFINANCE\n"
            "  python fundamental_agent.py --provider gemini --model gemini-2.0-flash WIPRO"
        )
    )
    parser.add_argument("stocks", nargs="+", help="NSE stock symbols (e.g. RELIANCE INFY)")
    parser.add_argument("--provider", type=str, choices=SUPPORTED_PROVIDERS,
                        help="LLM provider (default: from LLM_PROVIDER env var or 'anthropic')")
    parser.add_argument("--model", type=str,
                        help="Model override (default: from LLM_MODEL env var or provider default)")
    args = parser.parse_args()

    console.print()
    console.print(Panel(
        f"[bold cyan]Fundamental Analysis Agent[/bold cyan] | "
        f"Stocks: [yellow]{', '.join(s.upper() for s in args.stocks)}[/yellow] | "
        f"[dim]Provider: {provider_info()}[/dim]",
        title="[bold]NSE/BSE Research Agent[/bold]",
        border_style="cyan"
    ))

    for symbol in args.stocks:
        symbol = symbol.upper().strip()
        try:
            analysis = analyze_stock(
                symbol,
                verbose=True,
                provider_name=args.provider,
                model=args.model,
            )
            console.print()
            console.print(Panel(
                analysis,
                title=f"[bold green]{symbol}[/bold green]",
                border_style="green",
                padding=(1, 2)
            ))
        except EnvironmentError as e:
            console.print(f"[red]Configuration error: {e}[/red]")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            break

    console.print()
    console.print(Panel(
        "⚠ This is AI-generated factual research only. Not SEBI-registered investment advice.\n"
        "Verify all data from official sources before making financial decisions.",
        border_style="red",
        padding=(0, 2)
    ))


if __name__ == "__main__":
    main()
