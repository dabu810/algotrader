"""
Data models and scoring logic for fundamental analysis.
"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Recommendation(Enum):
    STRONG_BUY  = "STRONG BUY"
    BUY         = "BUY"
    HOLD        = "HOLD"
    SELL        = "SELL"
    STRONG_SELL = "STRONG SELL"


@dataclass
class FundamentalMetrics:
    """Quantitative financial metrics extracted from research."""
    # Valuation
    pe_ratio:            Optional[float] = None   # Price / EPS
    pb_ratio:            Optional[float] = None   # Price / Book value
    ev_to_ebitda:        Optional[float] = None
    market_cap_cr:       Optional[float] = None   # Market cap in crores
    dividend_yield:      Optional[float] = None   # %

    # Profitability
    roe:                 Optional[float] = None   # Return on Equity %
    roce:                Optional[float] = None   # Return on Capital Employed %
    net_margin:          Optional[float] = None   # Net profit margin %
    operating_margin:    Optional[float] = None   # %
    ebitda_margin:       Optional[float] = None   # %

    # Growth (YoY or CAGR)
    revenue_growth_3y:   Optional[float] = None   # 3-year revenue CAGR %
    profit_growth_3y:    Optional[float] = None   # 3-year PAT CAGR %
    eps_growth_ttm:      Optional[float] = None   # TTM EPS growth %
    revenue_growth_yoy:  Optional[float] = None   # Latest quarter YoY %
    profit_growth_yoy:   Optional[float] = None   # Latest quarter YoY %

    # Financial health
    debt_to_equity:      Optional[float] = None   # D/E ratio
    current_ratio:       Optional[float] = None
    interest_coverage:   Optional[float] = None   # EBIT / Interest expense
    free_cash_flow_cr:   Optional[float] = None   # FCF in crores

    # Efficiency
    asset_turnover:      Optional[float] = None
    inventory_days:      Optional[float] = None

    # Shareholding
    promoter_holding:    Optional[float] = None   # %
    promoter_pledge_pct: Optional[float] = None   # % of promoter shares pledged
    fii_holding:         Optional[float] = None   # %
    dii_holding:         Optional[float] = None   # %


@dataclass
class FundamentalScores:
    """Scored components (each 0-10) for overall fundamental quality."""
    valuation_score:    float = 0.0   # Is it cheap/fair/expensive?
    profitability_score: float = 0.0  # How profitable?
    growth_score:       float = 0.0   # Growth trajectory
    balance_sheet_score: float = 0.0  # Financial health
    management_score:   float = 0.0   # Promoter quality, governance

    @property
    def overall_score(self) -> float:
        """Weighted composite score (0-10)."""
        weights = {
            "valuation":    0.25,
            "profitability": 0.25,
            "growth":       0.25,
            "balance_sheet": 0.15,
            "management":   0.10,
        }
        return round(
            self.valuation_score    * weights["valuation"]    +
            self.profitability_score * weights["profitability"] +
            self.growth_score       * weights["growth"]        +
            self.balance_sheet_score * weights["balance_sheet"] +
            self.management_score   * weights["management"],
            2
        )

    @property
    def recommendation(self) -> str:
        score = self.overall_score
        if score >= 8.0: return Recommendation.STRONG_BUY.value
        if score >= 6.5: return Recommendation.BUY.value
        if score >= 5.0: return Recommendation.HOLD.value
        if score >= 3.5: return Recommendation.SELL.value
        return Recommendation.STRONG_SELL.value


def score_fundamentals_from_dict(metrics: dict) -> FundamentalScores:
    """
    Score fundamental metrics and return component scores.
    Called by the agent's score_fundamentals tool.
    """
    scores = FundamentalScores()

    # ── Valuation Score ──────────────────────────────────────────────────────
    val_points = 0
    pe = metrics.get("pe_ratio")
    sector_pe = metrics.get("sector_pe")
    pb = metrics.get("pb_ratio")
    div_yield = metrics.get("dividend_yield")

    if pe is not None:
        if pe < 10:          val_points += 3
        elif pe < 20:        val_points += 2.5
        elif pe < 30:        val_points += 1.5
        elif pe < 40:        val_points += 0.5
        # Check vs sector
        if sector_pe and pe < sector_pe * 0.85:  val_points += 1.5
        elif sector_pe and pe < sector_pe:         val_points += 0.5

    if pb is not None:
        if pb < 1.5:         val_points += 2
        elif pb < 3:         val_points += 1
        elif pb < 5:         val_points += 0.5

    if div_yield and div_yield > 2: val_points += 1

    scores.valuation_score = min(10.0, val_points)

    # ── Profitability Score ───────────────────────────────────────────────────
    prof_points = 0
    roe = metrics.get("roe")
    roce = metrics.get("roce")
    net_margin = metrics.get("net_margin")
    op_margin = metrics.get("operating_margin")

    if roe is not None:
        if roe > 25:         prof_points += 3
        elif roe > 18:       prof_points += 2.5
        elif roe > 12:       prof_points += 1.5
        elif roe > 8:        prof_points += 0.5

    if roce is not None:
        if roce > 20:        prof_points += 2
        elif roce > 14:      prof_points += 1.5
        elif roce > 10:      prof_points += 0.5

    if net_margin is not None:
        if net_margin > 20:  prof_points += 2
        elif net_margin > 12: prof_points += 1.5
        elif net_margin > 7:  prof_points += 0.5

    if op_margin is not None:
        if op_margin > 25:   prof_points += 1.5
        elif op_margin > 15: prof_points += 1
        elif op_margin > 8:  prof_points += 0.5

    scores.profitability_score = min(10.0, prof_points)

    # ── Growth Score ──────────────────────────────────────────────────────────
    growth_points = 0
    rev_3y = metrics.get("revenue_growth_3y")
    prof_3y = metrics.get("profit_growth_3y")
    rev_yoy = metrics.get("revenue_growth_yoy")
    prof_yoy = metrics.get("profit_growth_yoy")
    eps_ttm = metrics.get("eps_growth_ttm")

    if rev_3y is not None:
        if rev_3y > 25:      growth_points += 2.5
        elif rev_3y > 15:    growth_points += 2
        elif rev_3y > 10:    growth_points += 1
        elif rev_3y > 5:     growth_points += 0.5

    if prof_3y is not None:
        if prof_3y > 25:     growth_points += 2.5
        elif prof_3y > 15:   growth_points += 2
        elif prof_3y > 10:   growth_points += 1
        elif prof_3y > 5:    growth_points += 0.5

    if rev_yoy is not None and rev_yoy > 15: growth_points += 1.5
    elif rev_yoy is not None and rev_yoy > 8: growth_points += 0.5

    if prof_yoy is not None and prof_yoy > 20: growth_points += 1.5
    elif prof_yoy is not None and prof_yoy > 10: growth_points += 0.5

    if eps_ttm is not None and eps_ttm > 15: growth_points += 1

    scores.growth_score = min(10.0, growth_points)

    # ── Balance Sheet Score ───────────────────────────────────────────────────
    bs_points = 0
    de = metrics.get("debt_to_equity")
    cr = metrics.get("current_ratio")
    ic = metrics.get("interest_coverage")
    fcf = metrics.get("free_cash_flow_cr")

    if de is not None:
        if de == 0:           bs_points += 3.5   # Debt free
        elif de < 0.3:        bs_points += 3
        elif de < 0.6:        bs_points += 2
        elif de < 1.0:        bs_points += 1
        elif de < 2.0:        bs_points += 0.5

    if cr is not None:
        if cr > 2:            bs_points += 2
        elif cr > 1.5:        bs_points += 1.5
        elif cr > 1:          bs_points += 0.5

    if ic is not None:
        if ic > 10:           bs_points += 2
        elif ic > 5:          bs_points += 1.5
        elif ic > 3:          bs_points += 0.5

    if fcf is not None and fcf > 0: bs_points += 1  # Positive FCF

    scores.balance_sheet_score = min(10.0, bs_points)

    # ── Management Score ──────────────────────────────────────────────────────
    mgmt_points = 0
    promoter = metrics.get("promoter_holding")
    pledge_pct = metrics.get("promoter_pledge_pct")
    fii = metrics.get("fii_holding")

    if promoter is not None:
        if promoter > 65:     mgmt_points += 4
        elif promoter > 50:   mgmt_points += 3
        elif promoter > 35:   mgmt_points += 2
        elif promoter > 20:   mgmt_points += 1

    if pledge_pct is not None:
        if pledge_pct == 0:   mgmt_points += 3
        elif pledge_pct < 10: mgmt_points += 2
        elif pledge_pct < 25: mgmt_points += 1
        # High pledge is a red flag — subtract
        if pledge_pct > 50:   mgmt_points -= 2

    if fii is not None and fii > 15: mgmt_points += 1  # FII interest = quality signal
    if fii is not None and fii > 25: mgmt_points += 1  # Strong FII = extra quality

    scores.management_score = min(10.0, max(0.0, mgmt_points))

    return scores
