"""
F&O Strategy Analysis Tools
These functions are called by the Claude agent via tool use to perform
specific analytical tasks. Each returns a structured dict result.
"""
from market_data import MarketContext, OptionChain, TechnicalIndicators


def analyze_open_interest(ctx: MarketContext) -> dict:
    """
    Analyze option chain open interest to identify key levels,
    support/resistance, and institutional positioning.
    """
    oc = ctx.option_chain
    tech = ctx.technicals

    # Identify max pain (simplified: strike with lowest total OI pain)
    max_call_strike = oc.max_call_oi_strike()
    max_put_strike = oc.max_put_oi_strike()

    # OI buildup signals
    oi_signals = []
    for s in oc.strikes:
        if s.call_oi_change > 100000:
            oi_signals.append(f"Heavy call writing at {s.strike} (+{s.call_oi_change:,} OI) → Resistance")
        if s.put_oi_change > 100000:
            oi_signals.append(f"Heavy put writing at {s.strike} (+{s.put_oi_change:,} OI) → Support")
        if s.call_oi_change < -50000:
            oi_signals.append(f"Call unwinding at {s.strike} ({s.call_oi_change:,} OI) → Resistance weakening")
        if s.put_oi_change < -50000:
            oi_signals.append(f"Put unwinding at {s.strike} ({s.put_oi_change:,} OI) → Support weakening")

    # PCR interpretation
    pcr = oc.pcr
    if pcr > 1.3:
        pcr_signal = "CONTRARIAN_BULLISH"
        pcr_note = f"PCR {pcr:.2f} — Extreme bearish positioning, contrarian bullish"
    elif pcr > 1.0:
        pcr_signal = "MILDLY_BULLISH"
        pcr_note = f"PCR {pcr:.2f} — More put writers than call writers, mild bullish"
    elif pcr > 0.8:
        pcr_signal = "NEUTRAL"
        pcr_note = f"PCR {pcr:.2f} — Balanced market, range-bound expected"
    elif pcr > 0.6:
        pcr_signal = "MILDLY_BEARISH"
        pcr_note = f"PCR {pcr:.2f} — More call writers, mild bearish"
    else:
        pcr_signal = "CONTRARIAN_BEARISH"
        pcr_note = f"PCR {pcr:.2f} — Extreme bullish positioning, contrarian bearish"

    # Identify call/put wall
    return {
        "pcr": pcr,
        "pcr_signal": pcr_signal,
        "pcr_interpretation": pcr_note,
        "max_call_oi_strike": max_call_strike,
        "max_put_oi_strike": max_put_strike,
        "key_resistance": max_call_strike,
        "key_support": max_put_strike,
        "atm_straddle_premium": oc.atm_straddle_premium(),
        "total_call_oi": oc.total_call_oi,
        "total_put_oi": oc.total_put_oi,
        "oi_buildup_signals": oi_signals,
        "spot_vs_atm": "ABOVE_ATM" if ctx.spot_price > oc.atm_strike else "BELOW_ATM",
        "analysis": "Open interest analysis complete"
    }


def analyze_volatility(ctx: MarketContext) -> dict:
    """
    Analyze India VIX, IV Rank, and implied volatility to determine
    optimal strategy type (buy premium vs. sell premium).
    """
    vix = ctx.india_vix
    ivr = ctx.iv_rank
    oc = ctx.option_chain

    # VIX regime
    if vix < 12:
        vix_regime = "VERY_LOW"
        vix_strategy = "SELL_PREMIUM"
        vix_note = f"VIX {vix:.1f} — Very low volatility. Options cheap for buyers, ideal for sellers."
    elif vix < 15:
        vix_regime = "LOW"
        vix_strategy = "SELL_PREMIUM"
        vix_note = f"VIX {vix:.1f} — Low volatility. Favorable for premium selling strategies."
    elif vix < 18:
        vix_regime = "NORMAL"
        vix_strategy = "NEUTRAL"
        vix_note = f"VIX {vix:.1f} — Normal volatility. Both buying and selling viable."
    elif vix < 22:
        vix_regime = "ELEVATED"
        vix_strategy = "BUY_PREMIUM"
        vix_note = f"VIX {vix:.1f} — Elevated volatility. Favor option buying for directional plays."
    else:
        vix_regime = "HIGH"
        vix_strategy = "BUY_PREMIUM"
        vix_note = f"VIX {vix:.1f} — High volatility/fear. Buy options for protection or directional plays."

    # IV Rank
    if ivr > 70:
        ivr_signal = "SELL_IV"
        ivr_note = f"IVR {ivr:.0f}% — Options expensive vs history. Sell premium."
    elif ivr > 40:
        ivr_signal = "NEUTRAL_IV"
        ivr_note = f"IVR {ivr:.0f}% — IV in normal range. No strong bias."
    else:
        ivr_signal = "BUY_IV"
        ivr_note = f"IVR {ivr:.0f}% — Options cheap vs history. Buy premium."

    # ATM IV from option chain
    atm_call_iv = None
    atm_put_iv = None
    for s in oc.strikes:
        if s.strike == oc.atm_strike:
            atm_call_iv = s.call_iv
            atm_put_iv = s.put_iv

    # IV skew (put IV - call IV) — positive means put premium
    iv_skew = None
    if atm_call_iv and atm_put_iv:
        iv_skew = round(atm_put_iv - atm_call_iv, 2)

    # Combined recommendation
    if vix_strategy == "SELL_PREMIUM" and ivr_signal == "SELL_IV":
        combined = "STRONG_SELL_PREMIUM"
    elif vix_strategy == "BUY_PREMIUM" and ivr_signal == "BUY_IV":
        combined = "STRONG_BUY_PREMIUM"
    elif vix_strategy == "SELL_PREMIUM" or ivr_signal == "SELL_IV":
        combined = "LEAN_SELL_PREMIUM"
    elif vix_strategy == "BUY_PREMIUM" or ivr_signal == "BUY_IV":
        combined = "LEAN_BUY_PREMIUM"
    else:
        combined = "NEUTRAL"

    return {
        "india_vix": vix,
        "iv_rank": ivr,
        "vix_regime": vix_regime,
        "vix_strategy_bias": vix_strategy,
        "vix_interpretation": vix_note,
        "ivr_signal": ivr_signal,
        "ivr_interpretation": ivr_note,
        "atm_call_iv": atm_call_iv,
        "atm_put_iv": atm_put_iv,
        "iv_skew": iv_skew,
        "combined_vol_recommendation": combined,
        "iv_crush_risk": "HIGH" if ctx.notes and any(w in ctx.notes.lower() for w in ["rbi", "budget", "election", "result", "policy"]) else "LOW",
        "analysis": "Volatility analysis complete"
    }


def analyze_technicals(ctx: MarketContext) -> dict:
    """
    Analyze technical indicators: VWAP, RSI, EMA, Opening Range Breakout,
    and price action to determine directional bias.
    """
    tech = ctx.technicals
    spot = ctx.spot_price

    # VWAP positioning
    vwap_diff_pct = round((spot - tech.vwap) / tech.vwap * 100, 3)
    if spot > tech.vwap * 1.002:
        vwap_signal = "BULLISH"
        vwap_note = f"Price {spot:.0f} above VWAP {tech.vwap:.0f} (+{vwap_diff_pct:.2f}%) — Bullish bias"
    elif spot < tech.vwap * 0.998:
        vwap_signal = "BEARISH"
        vwap_note = f"Price {spot:.0f} below VWAP {tech.vwap:.0f} ({vwap_diff_pct:.2f}%) — Bearish bias"
    else:
        vwap_signal = "AT_VWAP"
        vwap_note = f"Price {spot:.0f} at VWAP {tech.vwap:.0f} — At decision point"

    # RSI signals
    rsi = tech.rsi_15min
    if rsi > 70:
        rsi_signal = "OVERBOUGHT"
    elif rsi > 60:
        rsi_signal = "BULLISH_MOMENTUM"
    elif rsi > 40:
        rsi_signal = "NEUTRAL"
    elif rsi > 30:
        rsi_signal = "BEARISH_MOMENTUM"
    else:
        rsi_signal = "OVERSOLD"

    # Opening Range Breakout analysis
    orb_high = tech.opening_range_high
    orb_low = tech.opening_range_low
    orb_range = orb_high - orb_low
    if spot > orb_high:
        orb_status = "BULLISH_BREAKOUT"
        orb_note = f"Price {spot:.0f} broke above ORB high {orb_high:.0f} — Bullish breakout confirmed"
    elif spot < orb_low:
        orb_status = "BEARISH_BREAKDOWN"
        orb_note = f"Price {spot:.0f} broke below ORB low {orb_low:.0f} — Bearish breakdown confirmed"
    elif spot > (orb_high + orb_low) / 2:
        orb_status = "INSIDE_RANGE_UPPER"
        orb_note = f"Price inside ORB ({orb_low:.0f}–{orb_high:.0f}), in upper half — Watch for breakout"
    else:
        orb_status = "INSIDE_RANGE_LOWER"
        orb_note = f"Price inside ORB ({orb_low:.0f}–{orb_high:.0f}), in lower half — Watch for breakdown"

    # EMA trend
    ema_trend = "BULLISH" if tech.ema_9 > tech.ema_21 else "BEARISH"
    ema_note = f"EMA9 {tech.ema_9:.0f} {'>' if ema_trend == 'BULLISH' else '<'} EMA21 {tech.ema_21:.0f} — {ema_trend.lower()} trend"

    # Volume confirmation
    if tech.volume_ratio > 1.5:
        vol_note = f"Volume {tech.volume_ratio:.1f}x above average — Strong confirmation"
        vol_signal = "STRONG"
    elif tech.volume_ratio > 1.0:
        vol_note = f"Volume {tech.volume_ratio:.1f}x average — Moderate confirmation"
        vol_signal = "MODERATE"
    else:
        vol_note = f"Volume {tech.volume_ratio:.1f}x average — Weak, below average"
        vol_signal = "WEAK"

    # Key levels
    key_levels = {
        "vwap": tech.vwap,
        "orb_high": orb_high,
        "orb_low": orb_low,
        "prev_day_high": tech.prev_day_high,
        "prev_day_low": tech.prev_day_low,
        "prev_day_close": tech.prev_day_close,
        "day_high": tech.day_high,
        "day_low": tech.day_low,
        "ema_9": tech.ema_9,
        "ema_21": tech.ema_21,
    }

    # Overall directional bias
    bullish_count = sum([
        vwap_signal == "BULLISH",
        rsi_signal in ("BULLISH_MOMENTUM",),
        orb_status == "BULLISH_BREAKOUT",
        ema_trend == "BULLISH"
    ])
    bearish_count = sum([
        vwap_signal == "BEARISH",
        rsi_signal in ("BEARISH_MOMENTUM",),
        orb_status == "BEARISH_BREAKDOWN",
        ema_trend == "BEARISH"
    ])

    if bullish_count >= 3:
        directional_bias = "STRONG_BULLISH"
    elif bullish_count >= 2:
        directional_bias = "MILD_BULLISH"
    elif bearish_count >= 3:
        directional_bias = "STRONG_BEARISH"
    elif bearish_count >= 2:
        directional_bias = "MILD_BEARISH"
    else:
        directional_bias = "NEUTRAL"

    return {
        "spot_price": spot,
        "vwap": tech.vwap,
        "vwap_signal": vwap_signal,
        "vwap_interpretation": vwap_note,
        "rsi_15min": rsi,
        "rsi_signal": rsi_signal,
        "orb_status": orb_status,
        "orb_interpretation": orb_note,
        "ema_trend": ema_trend,
        "ema_note": ema_note,
        "volume_signal": vol_signal,
        "volume_note": vol_note,
        "directional_bias": directional_bias,
        "key_levels": key_levels,
        "analysis": "Technical analysis complete"
    }


def analyze_session_timing(ctx: MarketContext) -> dict:
    """
    Analyze current session timing to recommend applicable strategies
    and entry windows.
    """
    session = ctx.session
    time_str = ctx.current_time
    is_expiry = ctx.is_expiry_day

    hour, minute = map(int, time_str.split(":"))
    current_mins = hour * 60 + minute

    # Session windows
    session_info = {
        "OPENING_RANGE": {"window": "09:15–09:45", "strategies": ["Opening Range Breakout", "Gap and Go", "Gap Fill"], "quality": "HIGH"},
        "MORNING":       {"window": "09:45–11:30", "strategies": ["VWAP Momentum", "ORB continuation", "OI Shift Trap"], "quality": "HIGH"},
        "MIDDAY":        {"window": "11:30–13:30", "strategies": ["Spread entries", "Iron Condor", "Straddle Sell"], "quality": "MODERATE"},
        "AFTERNOON":     {"window": "13:30–15:00", "strategies": ["OI repositioning", "Reversal setups", "Expiry ITM buying (if expiry)"], "quality": "HIGH"},
        "CLOSING":       {"window": "15:00–15:30", "strategies": ["Exit all intraday positions"], "quality": "EXIT_ONLY"},
    }

    info = session_info.get(session, session_info["MORNING"])

    # Expiry day special rules
    expiry_notes = []
    if is_expiry:
        expiry_notes = [
            "EXPIRY DAY ACTIVE — Gamma risk is elevated",
            "After 13:00: Consider ATM/ITM directional buying (theta near zero)",
            "Avoid naked short ATM options — gamma explodes",
            "Hard exit all positions by 15:15",
        ]
        if current_mins >= 13 * 60:
            expiry_notes.append("POST-1PM WINDOW: Momentum-based ITM option buying is viable now")

    # Time-based warnings
    warnings = []
    if current_mins >= 15 * 60:
        warnings.append("CRITICAL: Closing session — EXIT all intraday positions, no new entries")
    elif current_mins >= 14 * 60 + 30:
        warnings.append("WARNING: 30 mins to close — size down, start exits")
    if current_mins >= 11 * 60 + 30 and current_mins < 13 * 60 + 30:
        warnings.append("Midday lull — lower volume, avoid new entries unless very high confidence")

    # Best entry windows remaining today
    remaining_windows = []
    if current_mins < 9 * 60 + 45:
        remaining_windows.append("09:15–09:45: Opening Range (upcoming)")
    if current_mins < 11 * 60 + 30:
        remaining_windows.append("09:45–11:30: Morning momentum (upcoming/active)")
    if current_mins < 15 * 60:
        remaining_windows.append("13:30–15:00: Afternoon repositioning")
    if is_expiry and current_mins < 15 * 60:
        remaining_windows.append("13:00–15:15: Expiry ITM buying window")

    return {
        "current_time": time_str,
        "session": session,
        "session_window": info["window"],
        "session_quality": info["quality"],
        "applicable_strategies": info["strategies"],
        "is_expiry_day": is_expiry,
        "expiry_type": ctx.expiry_type,
        "expiry_notes": expiry_notes,
        "warnings": warnings,
        "remaining_windows": remaining_windows,
        "analysis": "Session timing analysis complete"
    }


def calculate_trade_parameters(
    ctx: MarketContext,
    strategy_type: str,
    direction: str,
    entry_strike: int,
    entry_premium: float,
    capital_available: float = 500000
) -> dict:
    """
    Calculate position sizing, risk-reward, and trade parameters
    for a given strategy setup.
    """
    lot_size = ctx.lot_size
    spot = ctx.spot_price

    # Risk per trade: 1.5% of capital
    risk_pct = 0.015
    max_risk = capital_available * risk_pct

    if strategy_type in ("BUY_CALL", "BUY_PUT"):
        # For long options: stop at 40% premium loss
        stop_loss_per_unit = entry_premium * 0.40
        stop_loss_price = round(entry_premium - stop_loss_per_unit, 2)
        max_lots = max(1, int(max_risk / (stop_loss_per_unit * lot_size)))

        # Targets: 1:1.5 and 1:2 R:R
        target_1 = round(entry_premium + stop_loss_per_unit * 1.5, 2)
        target_2 = round(entry_premium + stop_loss_per_unit * 2.0, 2)

        capital_required = entry_premium * lot_size * max_lots
        max_loss = stop_loss_per_unit * lot_size * max_lots
        target_profit_1 = stop_loss_per_unit * 1.5 * lot_size * max_lots
        target_profit_2 = stop_loss_per_unit * 2.0 * lot_size * max_lots

    elif strategy_type in ("SELL_STRADDLE", "SELL_STRANGLE"):
        # Premium collected; stop if premium doubles
        collected = entry_premium
        stop_loss_per_unit = collected  # stop if MTM loss = collected (2x premium)
        max_lots = max(1, int(max_risk / (stop_loss_per_unit * lot_size)))

        stop_loss_price = round(entry_premium * 2, 2)
        target_1 = round(entry_premium * 0.4, 2)   # 60% profit booking
        target_2 = round(entry_premium * 0.3, 2)    # 70% profit booking

        capital_required = 0  # Margin-based, approximation
        max_loss = stop_loss_per_unit * lot_size * max_lots
        target_profit_1 = collected * 0.60 * lot_size * max_lots
        target_profit_2 = collected * 0.70 * lot_size * max_lots

    elif strategy_type == "BULL_CALL_SPREAD":
        # Net debit; stop at 40% of net debit
        max_lots = max(1, int(max_risk / (entry_premium * 0.4 * lot_size)))
        stop_loss_price = round(entry_premium * 0.6, 2)
        target_1 = round(entry_premium * 1.6, 2)
        target_2 = round(entry_premium * 2.0, 2)

        capital_required = entry_premium * lot_size * max_lots
        max_loss = entry_premium * 0.4 * lot_size * max_lots
        target_profit_1 = entry_premium * 0.6 * lot_size * max_lots
        target_profit_2 = entry_premium * 1.0 * lot_size * max_lots

    else:
        # Generic fallback
        stop_loss_price = round(entry_premium * 0.6, 2)
        target_1 = round(entry_premium * 1.5, 2)
        target_2 = round(entry_premium * 2.0, 2)
        max_lots = 1
        capital_required = entry_premium * lot_size
        max_loss = entry_premium * 0.4 * lot_size
        target_profit_1 = entry_premium * 0.5 * lot_size
        target_profit_2 = entry_premium * 1.0 * lot_size

    rr_ratio = round((target_1 - entry_premium) / max(entry_premium - stop_loss_price, 0.01), 2)

    return {
        "strategy_type": strategy_type,
        "direction": direction,
        "instrument": ctx.instrument,
        "strike": entry_strike,
        "entry_premium": entry_premium,
        "lot_size": lot_size,
        "recommended_lots": min(max_lots, 5),  # Cap at 5 lots for safety
        "capital_required": round(capital_required, 0),
        "stop_loss_premium": stop_loss_price,
        "target_1_premium": target_1,
        "target_2_premium": target_2,
        "risk_per_lot": round(stop_loss_per_unit * lot_size if strategy_type in ("BUY_CALL", "BUY_PUT") else entry_premium * 0.4 * lot_size, 0),
        "max_loss_total": round(max_loss, 0),
        "target_profit_1": round(target_profit_1, 0),
        "target_profit_2": round(target_profit_2, 0),
        "risk_reward_ratio": rr_ratio,
        "time_stop": "Exit by 15:00 regardless of P&L",
        "analysis": "Trade parameters calculated"
    }
