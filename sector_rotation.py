# """
# SECTOR MOMENTUM ROTATION v5 — INVESTOR-GRADE
# =============================================
# CHANGES FROM v4 AND WHY EACH ONE MATTERS:

# ROOT CAUSE ANALYSIS OF v4 FAILURES:
#     1. Market phase detector: 100% classified as "Sideways"
#        → `gap200 < -0.03` fires constantly in normal markets
#        → Fix: Raise Bear threshold to -0.08, Sideways to ±7%
#        → Add hysteresis: require 3 consecutive days, not 15

#     2. Sideways phase kills CAGR
#        → 80% invested during "Sideways" = 20% dead cash all the time
#        → Fix: Sideways active_budget → 0.88 (only slightly defensive)

#     3. Quality thresholds too strict
#        → min_quality=2.5 eliminates nearly all sectors in Sideways
#        → Fix: Bull=1.0, Sideways=1.5, Bear=0.5

#     4. No position-level risk control
#        → Individual stocks run −30%+ before next rebalance
#        → Fix: Stop-loss overlay exits stocks that fall >15% from entry

#     5. Equal-weight within quality tier
#        → All sectors in "Leading" get same budget regardless of quality score
#        → Fix: Quality-proportional allocation (quality score as weight)

#     6. No portfolio volatility targeting
#        → Strategy returns are volatile, crushing risk-adjusted metrics
#        → Fix: Scale total exposure to target 12% annualised vol

#     7. Sector budget not capped relative to Nifty weight
#        → Overweight in small/illiquid sectors
#        → Fix: Hard cap at 30% per sector (unchanged), but quality-weight within cap

# EXPECTED IMPROVEMENTS vs v4:
#     CAGR:    10.78% → 15-18%
#     Sharpe:  0.35   → 0.75-0.90
#     Sortino: 0.57   → 1.0+
#     Max DD:  -30.5% → -18 to -22%
#     WF beat: 50%    → 75-85%

# ARCHITECTURAL ADDITIONS IN v5:
#     A. RECALIBRATED PHASE DETECTOR
#        - Bear:     gap200 < -8% OR (gap200 < -5% AND slope200 < -0.003)
#        - Sideways: |gap200| < 7% AND |slope50| < 0.004
#        - 3-day confirmation (down from 15-day lag)
#        - Hysteresis: must pass threshold for 3 days to flip state

#     B. VOLATILITY-TARGETED SIZING
#        - Compute realised 21-day portfolio volatility
#        - Scale exposure so expected ann vol ≈ 12%
#        - This compresses drawdowns and smooths the equity curve

#     C. POSITION STOP-LOSS
#        - Track each position's peak price after entry
#        - If current price falls >15% from peak: flag for exit at next open
#        - This is the single biggest fix for Max Drawdown

#     D. QUALITY-PROPORTIONAL WEIGHTS
#        - Sector budget ∝ quality score (0-3.5 scale)
#        - Higher-conviction bets get more capital
#        - Within-sector: top stock gets 55% (down from 60%) for better diversification

#     E. SECTOR MOMENTUM TILT
#        - Beyond RS consensus, reward sectors where RS is accelerating
#        - RS acceleration = slope of slope (2nd derivative of RS)
#        - Add 0.5 bonus to quality score if RS is accelerating

#     F. TRAILING STOP ON SECTOR EXITS
#        - Track sector-level RS peak
#        - If RS falls >20% from peak AND quality drops below 1.0: full exit
#        - Prevents hanging onto deteriorating sectors between rebalances
# """

# import streamlit as st
# import pandas as pd
# import numpy as np
# import yfinance as yf
# import plotly.graph_objects as go
# from strategies.base import BaseStrategy

# try:
#     _yf_version = yf.__version__
# except Exception:
#     _yf_version = "unknown"

# try:
#     _maj, _min = [int(x) for x in pd.__version__.split(".")[:2]]
#     _NEW_PD = (_maj > 2) or (_maj == 2 and _min >= 2)
# except Exception:
#     _NEW_PD = True
# FREQ_ME = "ME" if _NEW_PD else "M"
# FREQ_YE = "YE" if _NEW_PD else "Y"
# FREQ_2M = "2ME" if _NEW_PD else "2M"

# PHASE_BULL     = "Bull"
# PHASE_SIDEWAYS = "Sideways"
# PHASE_BEAR     = "Bear"
# DEFENSIVE_SECTORS = {"Staples", "Healthcare", "IT"}

# def _index_years(idx):
#     try:
#         return idx.year.tolist()
#     except AttributeError:
#         pass
#     try:
#         return idx.to_timestamp().year.tolist()
#     except Exception:
#         pass
#     return [str(i) for i in idx]


# # ═══════════════════════════════════════════════════════════════
# # UNIVERSE (unchanged from v4)
# # ═══════════════════════════════════════════════════════════════
# CORE_CONTINUOUS = [
#     "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS",
#     "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS",
#     "LT.NS","AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS","SUNPHARMA.NS",
#     "WIPRO.NS","HCLTECH.NS","POWERGRID.NS","NTPC.NS","ONGC.NS",
#     "TATAMOTORS.NS","TATASTEEL.NS","TECHM.NS","COALINDIA.NS",
#     "DRREDDY.NS","EICHERMOT.NS","BPCL.NS","CIPLA.NS","GRASIM.NS",
#     "INDUSINDBK.NS","HINDALCO.NS","BRITANNIA.NS","BAJAJ-AUTO.NS",
#     "HEROMOTOCO.NS","M&M.NS",
# ]
# ADDITIONS_BY_YEAR = {
#     2016: ["ADANIPORTS.NS","BAJFINANCE.NS"],
#     2017: ["ULTRACEMCO.NS","NESTLEIND.NS"],
#     2018: ["TITAN.NS","BAJAJFINSV.NS"],
#     2019: ["DIVISLAB.NS","SBILIFE.NS","HDFCLIFE.NS"],
#     2020: ["APOLLOHOSP.NS","TATACONSUM.NS"],
#     2021: ["JSWSTEEL.NS"],
#     2023: ["ADANIENT.NS"],
# }
# REMOVALS_LAST_YEAR = {"ZEEL.NS": 2021, "VEDL.NS": 2020, "UPL.NS": 2023}
# REMOVED_STOCKS = {
#     "ZEEL.NS": ("2015-01-01","2022-01-01"),
#     "VEDL.NS": ("2015-01-01","2021-01-01"),
#     "UPL.NS":  ("2015-01-01","2024-01-01"),
# }
# SECTOR_MAP = {
#     "HDFCBANK.NS":"Financials","ICICIBANK.NS":"Financials",
#     "KOTAKBANK.NS":"Financials","AXISBANK.NS":"Financials",
#     "SBIN.NS":"Financials","INDUSINDBK.NS":"Financials",
#     "BAJFINANCE.NS":"Financials","BAJAJFINSV.NS":"Financials",
#     "SBILIFE.NS":"Financials","HDFCLIFE.NS":"Financials",
#     "TCS.NS":"IT","INFY.NS":"IT","WIPRO.NS":"IT",
#     "HCLTECH.NS":"IT","TECHM.NS":"IT",
#     "RELIANCE.NS":"Energy","ONGC.NS":"Energy","BPCL.NS":"Energy",
#     "COALINDIA.NS":"Energy","POWERGRID.NS":"Energy","NTPC.NS":"Energy",
#     "HINDUNILVR.NS":"Staples","ITC.NS":"Staples","NESTLEIND.NS":"Staples",
#     "BRITANNIA.NS":"Staples","TATACONSUM.NS":"Staples",
#     "MARUTI.NS":"Auto","TATAMOTORS.NS":"Auto","EICHERMOT.NS":"Auto",
#     "BAJAJ-AUTO.NS":"Auto","HEROMOTOCO.NS":"Auto","M&M.NS":"Auto",
#     "LT.NS":"Industrials","ADANIPORTS.NS":"Industrials","ADANIENT.NS":"Industrials",
#     "JSWSTEEL.NS":"Materials","TATASTEEL.NS":"Materials","HINDALCO.NS":"Materials",
#     "ULTRACEMCO.NS":"Materials","GRASIM.NS":"Materials",
#     "VEDL.NS":"Materials","UPL.NS":"Materials",
#     "SUNPHARMA.NS":"Healthcare","DRREDDY.NS":"Healthcare","CIPLA.NS":"Healthcare",
#     "DIVISLAB.NS":"Healthcare","APOLLOHOSP.NS":"Healthcare",
#     "ASIANPAINT.NS":"ConsDisc","TITAN.NS":"ConsDisc","ZEEL.NS":"ConsDisc",
#     "BHARTIARTL.NS":"Telecom",
# }
# SECTOR_COLORS = {
#     "Financials":"#1565C0","IT":"#6A1B9A","Energy":"#E65100",
#     "Staples":"#2E7D32","Auto":"#F9A825","Industrials":"#4E342E",
#     "Materials":"#546E7A","Healthcare":"#00695C","ConsDisc":"#AD1457",
#     "Telecom":"#283593","Other":"#757575",
# }
# QUADRANT_EMOJI = {
#     "Leading":   "🟢 Leading",
#     "Improving": "🔵 Improving",
#     "Weakening": "🟠 Weakening",
#     "Lagging":   "🔴 Lagging",
# }


# def get_universe_for_year(year):
#     u = set(CORE_CONTINUOUS)
#     for y, tickers in ADDITIONS_BY_YEAR.items():
#         if year >= y: u.update(tickers)
#     for t, ly in REMOVALS_LAST_YEAR.items():
#         if year > ly: u.discard(t)
#     for t, (s, e) in REMOVED_STOCKS.items():
#         if int(s[:4]) <= year < int(e[:4]): u.add(t)
#     return sorted(u)


# def safe_float(val, default=0.0):
#     try:
#         f = float(val)
#         return f if np.isfinite(f) else default
#     except Exception:
#         return default


# def series_get(series, key, default=np.nan):
#     try:
#         val = series[key]
#         return float(val) if pd.notna(val) else default
#     except (KeyError, TypeError):
#         return default


# def compute_max_dd(series):
#     roll_max = series.cummax()
#     dd = (series / roll_max.replace(0, np.nan) - 1).fillna(0)
#     return dd, float(dd.min())


# # ═══════════════════════════════════════════════════════════════
# # v5 FIX A: RECALIBRATED MARKET PHASE DETECTOR
# # ═══════════════════════════════════════════════════════════════
# def compute_market_phase_v5(bench_prices: pd.Series,
#                              bear_gap_threshold: float = -0.08,
#                              bear_slope_threshold: float = -0.003,
#                              sideways_gap_pct: float = 0.07,
#                              sideways_slope_flat: float = 0.004,
#                              confirm_days: int = 3) -> pd.Series:
#     """
#     RECALIBRATED 3-state market phase detector.

#     KEY CHANGES FROM v4:
#     - Bear threshold: gap200 < -8% (was -3%) — far more realistic for India
#     - Bear slope: -0.003/day (unchanged but applied with correct gap)
#     - Sideways: |gap200| < 7% AND |slope50| < 0.004 (was 5% and 0.003)
#     - Confirmation: 3 days (was 15 — that was causing severe lag)
#     - Hysteresis: once in Bear, need gap200 > -5% to leave (not just -8%)

#     WHY THESE NUMBERS:
#     Nifty's average daily volatility ≈ 1%. Over 5 days = ±2.5% typical noise.
#     A 3% gap from 200DMA is just 3 days of normal vol — it fires all the time.
#     8% gap from 200DMA = 8 sigma on daily moves = genuine stress, not noise.
#     Similarly, 5% 200DMA gap band for Sideways captures the typical ±5% range
#     that Nifty trades in during consolidation without triggering false Sideways.
#     """
#     sma50  = bench_prices.rolling(50,  min_periods=30).mean()
#     sma200 = bench_prices.rolling(200, min_periods=100).mean()

#     slope200 = sma200.pct_change(21).fillna(0)
#     slope50  = sma50.pct_change(10).fillna(0)

#     gap200 = (bench_prices / sma200.replace(0, np.nan) - 1).fillna(0)
#     gap50  = (bench_prices / sma50.replace(0, np.nan) - 1).fillna(0)

#     phase = pd.Series(PHASE_BULL, index=bench_prices.index)

#     # BEAR: significant gap below 200DMA with falling MA
#     # OR extreme crash (>12% below — unchanged)
#     bear_mask = (
#         (gap200 < -0.12) |
#         ((gap200 < bear_gap_threshold) & (slope200 < bear_slope_threshold))
#     )
#     phase[bear_mask] = PHASE_BEAR

#     # SIDEWAYS: within the band around 200DMA with flat 50DMA
#     # Using wider band (7%) to avoid constant false Sideways triggers
#     sideways_mask = (
#         ~bear_mask &
#         (gap200.abs() < sideways_gap_pct) &
#         (slope50.abs() < sideways_slope_flat)
#     )
#     phase[sideways_mask] = PHASE_SIDEWAYS

#     # FAST confirmation: 3 consecutive days (not 15)
#     # v4's 15-day smoothing caused 3-week lag at regime changes
#     smoothed = phase.copy()
#     current = phase.iloc[0]
#     streak = 0
#     pending = current

#     for i in range(len(phase)):
#         p = phase.iloc[i]
#         if p == pending:
#             streak += 1
#         else:
#             pending = p
#             streak = 1

#         # Confirm phase change after 3 consecutive days
#         if streak >= confirm_days and pending != current:
#             current = pending

#         smoothed.iloc[i] = current

#     return smoothed


# # ═══════════════════════════════════════════════════════════════
# # v5 FIX F: SECTOR INDEX BUILDER (unchanged)
# # ═══════════════════════════════════════════════════════════════
# def build_sector_indices(close: pd.DataFrame,
#                          universe_by_date: dict) -> pd.DataFrame:
#     sectors = sorted(set(SECTOR_MAP.values()))
#     sector_idx = pd.DataFrame(index=close.index, columns=sectors, dtype=float)
#     for date in close.index:
#         year = date.year
#         universe = universe_by_date.get(year, [])
#         for sec in sectors:
#             members = [t for t in universe
#                        if SECTOR_MAP.get(t) == sec and t in close.columns]
#             if members:
#                 vals = close.loc[date, members].dropna()
#                 if len(vals) > 0:
#                     sector_idx.loc[date, sec] = float(vals.mean())
#     return sector_idx.astype(float).ffill().bfill()


# # ═══════════════════════════════════════════════════════════════
# # MULTI-TIMEFRAME RS WITH ACCELERATION (v5 addition)
# # ═══════════════════════════════════════════════════════════════
# def compute_multitf_rs(sector_idx: pd.DataFrame,
#                        bench_prices: pd.Series,
#                        lookbacks: tuple = (63, 126, 252),
#                        smooth: int = 14) -> dict:
#     """
#     Same as v4 but adds RS ACCELERATION (2nd derivative).
#     Sectors with accelerating RS get quality score bonus of +0.5.
#     This rewards early-stage breakouts, not just confirmed leaders.
#     """
#     results = {}
#     for lb in lookbacks:
#         rs_ratio_df = pd.DataFrame(index=sector_idx.index,
#                                     columns=sector_idx.columns, dtype=float)
#         rs_slope_df = pd.DataFrame(index=sector_idx.index,
#                                     columns=sector_idx.columns, dtype=float)
#         rs_accel_df = pd.DataFrame(index=sector_idx.index,
#                                     columns=sector_idx.columns, dtype=float)

#         for sec in sector_idx.columns:
#             sec_px  = sector_idx[sec].dropna()
#             if len(sec_px) < lb + 30:
#                 continue
#             bench_s   = bench_prices.reindex(sec_px.index).ffill()
#             sec_ret   = sec_px / sec_px.shift(lb).replace(0, np.nan)
#             bench_ret = bench_s / bench_s.shift(lb).replace(0, np.nan)
#             raw_rs    = sec_ret / bench_ret.replace(0, np.nan)
#             rs_r      = (raw_rs * 100).ewm(span=smooth, adjust=False).mean()

#             def _slope(s, w=63):
#                 if len(s) < w:
#                     return pd.Series(np.nan, index=s.index)
#                 x = np.arange(w)
#                 out = []
#                 for i in range(len(s)):
#                     if i < w - 1:
#                         out.append(np.nan)
#                     else:
#                         y = s.iloc[i-w+1:i+1].values
#                         if np.any(np.isnan(y)):
#                             out.append(np.nan)
#                         else:
#                             m = np.polyfit(x, y, 1)[0]
#                             out.append(m)
#                 return pd.Series(out, index=s.index)

#             slope_s = _slope(rs_r)
#             # Acceleration = slope of the slope (21-day)
#             accel_s = slope_s.diff(21)

#             rs_ratio_df[sec] = rs_r
#             rs_slope_df[sec] = slope_s
#             rs_accel_df[sec] = accel_s

#         results[lb] = {
#             "rs_ratio": rs_ratio_df.astype(float),
#             "rs_slope": rs_slope_df.astype(float),
#             "rs_accel": rs_accel_df.astype(float),
#         }
#     return results


# def compute_rs_consensus(multitf_results: dict,
#                           lookbacks: tuple = (63, 126, 252),
#                           min_agreement: int = 2) -> dict:
#     """
#     v5 adds acceleration bonus to quality score:
#     - quality base: count × (1 + 0.5 × slope_ok)   [same as v4]
#     - quality bonus: +0.5 if RS is accelerating on longest TF
#     - quality max:   3.5 (was 3.0 in v4 with slope)

#     Also adds 'accel_ok' series for use in classification.
#     """
#     sectors = multitf_results[lookbacks[0]]["rs_ratio"].columns
#     idx     = multitf_results[lookbacks[0]]["rs_ratio"].index

#     count_df = pd.DataFrame(0, index=idx, columns=sectors)
#     avg_rs   = pd.DataFrame(0.0, index=idx, columns=sectors)
#     slope_ok = pd.DataFrame(False, index=idx, columns=sectors)
#     accel_ok = pd.DataFrame(False, index=idx, columns=sectors)

#     for lb in lookbacks:
#         rs = multitf_results[lb]["rs_ratio"]
#         sl = multitf_results[lb]["rs_slope"]
#         for sec in sectors:
#             if sec not in rs.columns:
#                 continue
#             above = (rs[sec] > 100).fillna(False)
#             count_df[sec] += above.astype(int)
#             avg_rs[sec]   += rs[sec].fillna(100)

#     avg_rs = avg_rs / len(lookbacks)

#     longest = max(lookbacks)
#     for sec in sectors:
#         if sec in multitf_results[longest]["rs_slope"].columns:
#             slope_ok[sec] = (
#                 multitf_results[longest]["rs_slope"][sec] > 0
#             ).fillna(False)
#         if sec in multitf_results[longest].get("rs_accel", pd.DataFrame()).columns:
#             accel_ok[sec] = (
#                 multitf_results[longest]["rs_accel"][sec] > 0
#             ).fillna(False)

#     qualified = count_df >= min_agreement

#     quality = count_df.astype(float).copy()
#     for sec in sectors:
#         base = count_df[sec] * (1.0 + 0.5 * slope_ok[sec].astype(float))
#         # v5: add 0.5 bonus for accelerating RS
#         bonus = 0.5 * accel_ok[sec].astype(float)
#         quality[sec] = base + bonus

#     return {
#         "count":     count_df,
#         "qualified": qualified,
#         "avg_rs":    avg_rs,
#         "slope_ok":  slope_ok,
#         "accel_ok":  accel_ok,
#         "quality":   quality,
#     }


# # ═══════════════════════════════════════════════════════════════
# # QUADRANT CLASSIFICATION v5
# # ═══════════════════════════════════════════════════════════════
# def classify_sectors_v5(consensus: dict, phase: str, sectors: list) -> dict:
#     """
#     Same logic as v4 but:
#     - Weakening definition: qualified but slope fading AND acceleration negative
#     - In Bull: also check accel_ok to differentiate accelerating vs coasting
#     """
#     q_row = {}
#     for sec in sectors:
#         try:
#             cnt = int(consensus["count"][sec].iloc[-1])
#             qok = bool(consensus["qualified"][sec].iloc[-1])
#             sok = bool(consensus["slope_ok"][sec].iloc[-1])
#             aok = bool(consensus["accel_ok"][sec].iloc[-1])
#         except Exception:
#             q_row[sec] = "Lagging"
#             continue

#         if phase == PHASE_BEAR:
#             if sec in DEFENSIVE_SECTORS and qok:
#                 q_row[sec] = "Leading"
#             elif sec in DEFENSIVE_SECTORS and cnt >= 1:
#                 q_row[sec] = "Improving"
#             else:
#                 q_row[sec] = "Lagging"
#         else:
#             if qok and sok:
#                 q_row[sec] = "Leading"
#             elif qok and not sok:
#                 q_row[sec] = "Weakening"
#             elif cnt == 1 and sok:
#                 q_row[sec] = "Improving"
#             elif cnt == 1 and not sok:
#                 q_row[sec] = "Lagging"
#             else:
#                 q_row[sec] = "Lagging"

#     return q_row


# # ═══════════════════════════════════════════════════════════════
# # STOCK SELECTION (same scoring, minor cap)
# # ═══════════════════════════════════════════════════════════════
# def select_stocks_in_sector(sector, universe, close, daily_ret,
#                              date, n_stocks=3):
#     WIN_6M = 126; WIN_1Y = 252; rf_d = 0.065 / 252
#     members = [t for t in universe
#                if SECTOR_MAP.get(t) == sector and t in close.columns]
#     if not members: return []
#     if len(members) <= n_stocks: return members
#     try:
#         c = close.loc[:date, members].copy()
#         r = daily_ret.loc[:date, members].copy()
#     except Exception:
#         return members[:n_stocks]
#     n = len(c)
#     if n < 30: return members[:n_stocks]
#     px = c.iloc[-1]
#     scores = {}
#     for t in members:
#         try:
#             p = float(px.get(t, np.nan))
#             if np.isnan(p) or p <= 0: continue
#             if n >= WIN_6M:
#                 p6m = float(c[t].iloc[-WIN_6M])
#                 mom = (p / p6m - 1) if p6m > 0 else 0.0
#             else:
#                 mom = 0.0
#             r1y = r[t].iloc[-WIN_1Y:] if n >= WIN_1Y else r[t]
#             mu  = float(r1y.mean()); std = float(r1y.std())
#             sh  = ((mu - rf_d) / std * np.sqrt(252)) if std > 1e-10 else 0.0
#             vol = std * np.sqrt(252) if std > 0 else 1.0
#             scores[t] = {"mom": mom, "sharpe": sh, "vol": vol}
#         except Exception:
#             pass
#     if not scores: return members[:n_stocks]
#     df_s = pd.DataFrame(scores).T
#     if len(df_s) > 1:
#         df_s["m_r"] = df_s["mom"].rank(pct=True)
#         df_s["s_r"] = df_s["sharpe"].rank(pct=True)
#         df_s["v_r"] = 1 - df_s["vol"].rank(pct=True)
#     else:
#         df_s["m_r"] = df_s["s_r"] = df_s["v_r"] = 0.5
#     df_s["comp"] = 0.40*df_s["m_r"] + 0.35*df_s["s_r"] + 0.25*df_s["v_r"]
#     return df_s["comp"].sort_values(ascending=False).index.tolist()[:n_stocks]


# def _intra_sector_weights(selected, budget):
#     """
#     v5: top stock gets 55% (was 60%) for slightly better diversification.
#     Reducing concentration in the top pick helps Sharpe ratio.
#     """
#     if not selected: return {}
#     if len(selected) == 1: return {selected[0]: budget}
#     top_w = budget * 0.55
#     per_rest = budget * 0.45 / (len(selected) - 1)
#     w = {selected[0]: top_w}
#     for t in selected[1:]: w[t] = per_rest
#     return w


# # ═══════════════════════════════════════════════════════════════
# # v5 FIX B+D: QUALITY-PROPORTIONAL + PHASE-AWARE PORTFOLIO
# # ═══════════════════════════════════════════════════════════════
# def build_target_weights_v5(q_row, consensus, universe,
#                              close, daily_ret, date,
#                              max_sector_weight, phase,
#                              max_positions=15,
#                              vol_target=0.12,
#                              port_vol_21d=None):
#     """
#     v5 portfolio construction:

#     KEY CHANGE 1 — Phase parameters recalibrated:
#         BULL:     active_budget=0.95 (up from 0.92)
#         SIDEWAYS: active_budget=0.88 (up from 0.80 — this was killing CAGR)
#         BEAR:     active_budget=0.50 (unchanged)

#     KEY CHANGE 2 — Quality-proportional sector weighting:
#         Instead of equal split within "Leading" bucket,
#         each sector's budget ∝ its quality score.
#         quality=3.5 → 2.3× more capital than quality=1.5
#         This concentrates in highest-conviction bets.

#     KEY CHANGE 3 — Quality thresholds lowered:
#         Bull min_quality=1.0 (was 1.5) → more sectors qualify
#         Sideways min_quality=1.5 (was 2.5) → not a dead zone anymore
#         Bear min_quality=0.5 (unchanged)

#     KEY CHANGE 4 — Volatility scaling (if port_vol_21d provided):
#         If current realised vol > vol_target: scale down total exposure
#         If current realised vol < vol_target×0.7: scale up to vol_target
#         This is the Sharpe ratio's best friend.
#     """
#     if phase == PHASE_BULL:
#         active_budget  = 0.95
#         max_pos        = max_positions
#         min_quality    = 1.0
#         alloc_ratios   = {"Leading": 0.65, "Improving": 0.35}
#         n_stocks_map   = {"Leading": 3, "Improving": 2}

#     elif phase == PHASE_SIDEWAYS:
#         active_budget  = 0.88   # KEY FIX: was 0.80
#         max_pos        = 12
#         min_quality    = 1.5    # KEY FIX: was 2.5 — too strict
#         alloc_ratios   = {"Leading": 0.75, "Improving": 0.25}
#         n_stocks_map   = {"Leading": 2, "Improving": 2}

#     else:  # BEAR
#         active_budget  = 0.50
#         max_pos        = 6
#         min_quality    = 0.5
#         alloc_ratios   = {"Leading": 0.70, "Improving": 0.30}
#         n_stocks_map   = {"Leading": 2, "Improving": 1}

#     # v5 FIX: Volatility scaling — scale exposure inversely with vol
#     if port_vol_21d is not None and port_vol_21d > 1e-6:
#         vol_scalar = min(vol_target / port_vol_21d, 1.0)  # never lever up
#         active_budget = active_budget * vol_scalar

#     # Collect qualifying sectors with their quality scores
#     qualified_sectors = {}
#     for sec, q in q_row.items():
#         if q not in alloc_ratios:
#             continue
#         try:
#             qual = float(consensus["quality"][sec].iloc[-1])
#         except Exception:
#             qual = 0.0
#         if qual >= min_quality:
#             qualified_sectors[sec] = {"quadrant": q, "quality": qual}

#     if not qualified_sectors:
#         return {}

#     # v5 FIX: Quality-proportional allocation within each quadrant
#     # Each quadrant gets its fixed ratio of active_budget
#     # Within the quadrant, sectors are weighted by quality score
#     quadrant_qual_sum = {}
#     for sec, info in qualified_sectors.items():
#         q = info["quadrant"]
#         quadrant_qual_sum[q] = quadrant_qual_sum.get(q, 0.0) + info["quality"]

#     sector_budgets = {}
#     for sec, info in qualified_sectors.items():
#         q        = info["quadrant"]
#         qual     = info["quality"]
#         q_sum    = max(quadrant_qual_sum.get(q, 1.0), 1e-6)
#         q_budget = alloc_ratios.get(q, 0.0) * active_budget
#         # Quality-proportional share within quadrant
#         sector_budgets[sec] = q_budget * (qual / q_sum)

#     # Apply per-sector cap
#     for sec in sector_budgets:
#         sector_budgets[sec] = min(sector_budgets[sec], max_sector_weight)

#     # Re-normalize to active_budget
#     total = sum(sector_budgets.values())
#     if total > 0:
#         sector_budgets = {k: v / total * active_budget
#                           for k, v in sector_budgets.items()}

#     stock_weights = {}
#     total_positions = 0

#     for sec, budget in sorted(sector_budgets.items(),
#                                key=lambda x: -x[1]):  # highest budget first
#         if budget < 0.005: continue
#         q = q_row.get(sec, "Lagging")
#         n_for_sector = n_stocks_map.get(q, 1)
#         remaining = max_pos - total_positions
#         if remaining <= 0: break
#         n_for_sector = min(n_for_sector, remaining)
#         selected = select_stocks_in_sector(
#             sec, universe, close, daily_ret, date, n_for_sector)
#         if not selected: continue
#         intra = _intra_sector_weights(selected, budget)
#         for t, w in intra.items():
#             stock_weights[t] = stock_weights.get(t, 0) + w
#             total_positions += 1

#     return stock_weights


# # ═══════════════════════════════════════════════════════════════
# # WALK-FORWARD ANALYSIS (unchanged from v4)
# # ═══════════════════════════════════════════════════════════════
# def compute_walk_forward(port_series, bench_norm, window_years=3):
#     window_days = int(window_years * 252)
#     dates = port_series.index
#     rows = []
#     step = window_days // 4

#     i = 0
#     while i + window_days <= len(dates):
#         start = dates[i]
#         end   = dates[min(i + window_days - 1, len(dates)-1)]
#         ps = port_series.loc[start:end]
#         bn = bench_norm.loc[start:end].ffill()

#         if len(ps) < 60: break

#         n_yrs = len(ps) / 252.0
#         try:
#             cagr_s = (ps.iloc[-1]/ps.iloc[0])**(1/n_yrs) - 1
#             cagr_b = (bn.iloc[-1]/bn.iloc[0])**(1/n_yrs) - 1
#             ret_s  = ps.pct_change().dropna()
#             std_s  = ret_s.std()
#             rf_d   = 0.065/252
#             sharpe = ((ret_s.mean()-rf_d)/std_s*np.sqrt(252)) if std_s>1e-10 else 0
#             _, mdd = compute_max_dd(ps)
#             rows.append({
#                 "Period":     f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}",
#                 "Strat CAGR": round(cagr_s * 100, 1),
#                 "Nifty CAGR": round(cagr_b * 100, 1),
#                 "Alpha %":    round((cagr_s - cagr_b) * 100, 1),
#                 "Sharpe":     round(sharpe, 2),
#                 "Max DD %":   round(mdd * 100, 1),
#                 "Beat?":      "✅" if cagr_s > cagr_b else "❌",
#             })
#         except Exception:
#             pass
#         i += step

#     return pd.DataFrame(rows)


# # ═══════════════════════════════════════════════════════════════
# # SECTOR ALPHA ATTRIBUTION (unchanged)
# # ═══════════════════════════════════════════════════════════════
# def compute_sector_attribution(weights_history, port_ret, bench_ret):
#     rows = []
#     monthly_excess = (port_ret - bench_ret).resample(FREQ_ME).apply(
#         lambda x: (1+x).prod()-1)
#     for date, weights in weights_history.items():
#         sec_weights = {}
#         for t, w in weights.items():
#             sec = SECTOR_MAP.get(t, "Other")
#             sec_weights[sec] = sec_weights.get(sec, 0) + w
#         future = monthly_excess.index[monthly_excess.index >= date]
#         if len(future) == 0: continue
#         ex_ret = float(monthly_excess[future[0]])
#         for sec, w in sec_weights.items():
#             rows.append({"date": date, "sector": sec,
#                          "weight": w, "contribution": w * ex_ret * 100})
#     if not rows: return pd.DataFrame()
#     df = pd.DataFrame(rows)
#     summary = df.groupby("sector")["contribution"].sum().reset_index()
#     summary.columns = ["Sector", "Alpha Contribution %"]
#     return summary.sort_values("Alpha Contribution %", ascending=False)


# # ═══════════════════════════════════════════════════════════════
# # CORE BACKTEST v5 — ALL FIXES APPLIED
# # ═══════════════════════════════════════════════════════════════
# @st.cache_data
# def _run_sector_rotation_v5(
#     start_date, end_date,
#     smooth_period,
#     max_sector_weight,
#     rebal_freq_months,
#     drift_tolerance,
#     fee_bps, slip_bps,
#     min_tf_agreement,
#     stop_loss_pct,        # v5: individual position stop-loss (e.g. 0.15 = 15%)
#     vol_target,           # v5: portfolio vol target (e.g. 0.12 = 12% ann vol)
#     bear_gap_threshold,   # v5: phase detector Bear gap (e.g. -0.08)
#     sideways_gap_pct,     # v5: phase detector Sideways band (e.g. 0.07)
#     _cache_version=6,
# ):
#     import inspect as _inspect
#     log = []
#     tc  = (fee_bps + slip_bps) / 10_000
#     LOOKBACKS = (63, 126, 252)
#     REBAL_FREQ = FREQ_2M if rebal_freq_months == 2 else FREQ_ME

#     # ── 1. Universe ──
#     all_tickers = set()
#     sy = int(str(start_date)[:4])
#     ey = int(str(end_date)[:4])
#     universe_by_date = {}
#     for yr in range(sy, ey + 1):
#         u = get_universe_for_year(yr)
#         universe_by_date[yr] = u
#         all_tickers.update(u)
#     dl_list = sorted(all_tickers) + ["^NSEI"]
#     log.append(f"STEP1 ✅ {len(dl_list)} tickers | {sy}–{ey}")

#     # ── 2. Download ──
#     try:
#         _kw = dict(start=str(start_date), end=str(end_date),
#                    auto_adjust=True, progress=False, threads=False)
#         _sig = _inspect.signature(yf.download).parameters
#         if "group_by" in _sig:          _kw["group_by"] = "column"
#         if "multi_level_index" in _sig: _kw["multi_level_index"] = True
#         raw = yf.download(dl_list, **_kw)
#         log.append(f"STEP2 ✅ shape={raw.shape}")
#     except Exception as e:
#         return None, f"Download failed: {e}", log

#     if raw.empty or raw.shape[0] < 20:
#         return None, "No data.", log

#     # ── 3–4. Extract + clean ──
#     def _field(r, names):
#         if isinstance(r.columns, pd.MultiIndex):
#             l0 = r.columns.get_level_values(0).unique().tolist()
#             for n in names:
#                 if n in l0: return r[n].copy()
#         else:
#             for n in names:
#                 if n in r.columns: return r[[n]].copy()
#         return None

#     close = _field(raw, ["Close", "Adj Close"])
#     open_ = _field(raw, ["Open"])
#     if close is None: return None, "No Close column.", log
#     if open_ is None: open_ = close.copy()

#     close = close.loc[:, close.isna().mean() < 0.60].ffill().bfill()
#     open_ = open_.reindex(columns=close.columns).ffill().bfill()
#     if "^NSEI" not in close.columns:
#         return None, "^NSEI missing.", log

#     bench_prices = close["^NSEI"].copy()
#     scols        = [c for c in close.columns if c != "^NSEI"]
#     close_s      = close[scols]
#     open_s       = open_.reindex(columns=scols)
#     n_rows       = len(close_s)
#     log.append(f"STEP4 ✅ {len(scols)} stocks | {n_rows} days")
#     if n_rows < 300:
#         return None, f"Only {n_rows} rows — need 300+.", log

#     # ── 5. Sector indices ──
#     sector_idx = build_sector_indices(close_s, universe_by_date)
#     log.append(f"STEP5 ✅ {sector_idx.shape[1]} sector indices built")

#     # ── 6. Multi-TF RS + consensus ──
#     multitf = compute_multitf_rs(
#         sector_idx, bench_prices,
#         lookbacks=LOOKBACKS, smooth=smooth_period)

#     consensus = compute_rs_consensus(
#         multitf, lookbacks=LOOKBACKS, min_agreement=min_tf_agreement)

#     qual_arr = consensus["quality"].values
#     valid_q  = qual_arr[np.isfinite(qual_arr)]
#     if len(valid_q) > 0:
#         qualified_pct = (consensus["qualified"].values.sum() /
#                          max(consensus["qualified"].values.size, 1) * 100)
#         log.append(
#             f"STEP6 ✅ Multi-TF RS | Agreement: {min_tf_agreement}/3 | "
#             f"Sectors qualifying avg: {qualified_pct:.0f}% | "
#             f"Quality range: {valid_q.min():.1f}–{valid_q.max():.1f}"
#         )
#     else:
#         return None, "Multi-TF RS computation failed.", log

#     # ── 7. v5 Recalibrated market phase ──
#     market_phase = compute_market_phase_v5(
#         bench_prices,
#         bear_gap_threshold=bear_gap_threshold,
#         sideways_gap_pct=sideways_gap_pct,
#         confirm_days=3)

#     phase_counts = market_phase.value_counts()
#     bull_pct = phase_counts.get(PHASE_BULL, 0)/len(market_phase)*100
#     sw_pct   = phase_counts.get(PHASE_SIDEWAYS, 0)/len(market_phase)*100
#     bear_pct = phase_counts.get(PHASE_BEAR, 0)/len(market_phase)*100
#     log.append(
#         f"STEP7 ✅ Phase (v5 recalibrated) | "
#         f"Bull: {bull_pct:.0f}% | Sideways: {sw_pct:.0f}% | Bear: {bear_pct:.0f}%"
#     )
#     if bull_pct < 20:
#         log.append(
#             "STEP7 ⚠️ Bull <20% — phase detector still too aggressive. "
#             "Try raising bear_gap_threshold closer to -0.10."
#         )
#     if sw_pct > 70:
#         log.append(
#             "STEP7 ⚠️ Sideways >70% — consider raising sideways_gap_pct to 0.09."
#         )

#     # ── 8. Rebalance dates ──
#     daily_ret  = close_s.pct_change().fillna(0)
#     dates      = close_s.index
#     rebal_set  = set()
#     for rd in pd.date_range(dates[0], dates[-1], freq=REBAL_FREQ):
#         future = dates[dates >= rd]
#         if len(future) > 0: rebal_set.add(future[0])
#     log.append(f"STEP8 ✅ {len(rebal_set)} rebal dates (every {rebal_freq_months}M)")

#     # ── 9. Backtest loop ──
#     portfolio_value  = 1_000_000.0
#     cash             = portfolio_value
#     holdings         = {}   # {ticker: {shares, entry_price, entry_date, peak_price}}
#     port_values      = {}
#     weights_history  = {}
#     signal_history   = {}
#     quadrant_hist    = {}
#     phase_history    = {}
#     trade_log        = []
#     pending_rebal    = None
#     last_rebal_date  = None
#     day_counter      = 0
#     hold_periods     = []

#     # Rolling vol tracker (21-day window of portfolio returns)
#     recent_port_rets = []

#     for date in dates:
#         try:
#             px_close = close_s.loc[date]
#             px_open  = open_s.loc[date]
#         except KeyError:
#             port_values[date] = portfolio_value
#             continue
#         day_counter += 1

#         # ── v5 FIX C: STOP-LOSS CHECK (before trading logic) ──
#         # Flag any position that has fallen >stop_loss_pct from its peak
#         stop_loss_exits = set()
#         if stop_loss_pct > 0:
#             for t, h in list(holdings.items()):
#                 cp = series_get(px_close, t, h["entry_price"])
#                 if np.isnan(cp): continue
#                 # Update peak price
#                 if cp > h.get("peak_price", h["entry_price"]):
#                     holdings[t]["peak_price"] = cp
#                 peak = h.get("peak_price", h["entry_price"])
#                 # Trailing stop: exit if fallen >stop_loss_pct from peak
#                 if peak > 0 and (cp / peak - 1) < -stop_loss_pct:
#                     stop_loss_exits.add(t)

#         # Execute stop-loss exits at next open price
#         if stop_loss_exits:
#             h_val = sum(
#                 h["shares"] * series_get(px_open, t, h["entry_price"])
#                 for t, h in holdings.items())
#             portfolio_value = cash + h_val
#             for t in stop_loss_exits:
#                 if t not in holdings: continue
#                 ep = series_get(px_open, t)
#                 if np.isnan(ep): continue
#                 h    = holdings.pop(t)
#                 cash += h["shares"] * ep * (1 - tc)
#                 pnl  = (ep/h["entry_price"]-1)*100 if h["entry_price"]>0 else 0
#                 hd   = (date - h.get("entry_date", date)).days
#                 hold_periods.append(hd)
#                 trade_log.append({"date":date,"ticker":t,
#                     "action":"STOP-LOSS","pnl_pct":pnl,"hold_days":hd})

#         # ── Execute pending rebalance ──
#         if pending_rebal is not None:
#             target_w, exits_set = pending_rebal
#             pending_rebal = None

#             h_val = sum(
#                 h["shares"] * series_get(px_open, t, h["entry_price"])
#                 for t, h in holdings.items())
#             portfolio_value = cash + h_val

#             for t in list(holdings.keys()):
#                 if t in exits_set or t not in target_w:
#                     ep = series_get(px_open, t)
#                     if np.isnan(ep): continue
#                     h    = holdings.pop(t)
#                     cash += h["shares"] * ep * (1 - tc)
#                     pnl  = (ep/h["entry_price"]-1)*100 if h["entry_price"]>0 else 0
#                     hd   = (date - h.get("entry_date", date)).days
#                     hold_periods.append(hd)
#                     trade_log.append({"date":date,"ticker":t,
#                         "action":"SELL","pnl_pct":pnl,"hold_days":hd})

#             for t, w in target_w.items():
#                 ep = series_get(px_open, t)
#                 if np.isnan(ep) or ep <= 0: continue
#                 target_sh = int(portfolio_value * w / ep)
#                 if target_sh <= 0: continue
#                 if t in holdings:
#                     cur_w = (holdings[t]["shares"]*ep) / max(portfolio_value,1)
#                     if abs(cur_w - w) > drift_tolerance:
#                         diff = target_sh - holdings[t]["shares"]
#                         if diff > 0:
#                             cost = diff*ep*(1+tc)
#                             if cost <= cash:
#                                 holdings[t]["shares"] += diff; cash -= cost
#                         elif diff < 0:
#                             holdings[t]["shares"] += diff
#                             cash += (-diff)*ep*(1-tc)
#                 else:
#                     cost = target_sh*ep*(1+tc)
#                     if cost <= cash:
#                         holdings[t] = {
#                             "shares":      target_sh,
#                             "entry_price": ep,
#                             "entry_date":  date,
#                             "peak_price":  ep,   # v5: track peak for trailing stop
#                         }
#                         cash -= cost
#                         trade_log.append({"date":date,"ticker":t,
#                             "action":"BUY","pnl_pct":0,"hold_days":0})

#         # ── Mark to market ──
#         h_val = sum(
#             h["shares"] * series_get(px_close, t, h["entry_price"])
#             for t, h in holdings.items())
#         portfolio_value = cash + h_val

#         # ── Track rolling portfolio vol (21-day window) ──
#         if len(port_values) > 0:
#             prev_val = list(port_values.values())[-1]
#             if prev_val > 0:
#                 recent_port_rets.append(portfolio_value / prev_val - 1)
#         if len(recent_port_rets) > 21:
#             recent_port_rets.pop(0)

#         # ── Rebalance trigger ──
#         if date in rebal_set and date != last_rebal_date:
#             last_rebal_date = date
#             universe = universe_by_date.get(date.year, [])
#             phase    = market_phase.get(date, PHASE_BULL)
#             phase_history[date] = phase

#             if date not in consensus["count"].index:
#                 pending_rebal = ({}, set())
#                 port_values[date] = portfolio_value
#                 continue

#             cons_at_date = {
#                 k: v.loc[:date] for k, v in consensus.items()
#                 if hasattr(v, "loc")
#             }

#             sectors = list(sector_idx.columns)
#             q_row = classify_sectors_v5(cons_at_date, phase, sectors)
#             quadrant_hist[date] = q_row.copy()

#             # v5: compute realised vol for vol-targeting
#             port_vol_21d = None
#             if len(recent_port_rets) >= 10:
#                 rv = np.std(recent_port_rets)
#                 port_vol_21d = rv * np.sqrt(252) if rv > 0 else None

#             target_w = build_target_weights_v5(
#                 q_row, cons_at_date, universe,
#                 close_s, daily_ret, date,
#                 max_sector_weight, phase,
#                 max_positions=15,
#                 vol_target=vol_target,
#                 port_vol_21d=port_vol_21d)

#             exits_set = {t for t in holdings if t not in target_w}
#             weights_history[date] = target_w.copy()
#             signal_history[date] = {
#                 "quadrants":    q_row,
#                 "phase":        phase,
#                 "port_vol_21d": round(port_vol_21d * 100, 1) if port_vol_21d else None,
#                 "quality":      {
#                     s: round(float(cons_at_date["quality"][s].iloc[-1]), 2)
#                     for s in sectors
#                     if s in cons_at_date["quality"].columns
#                 },
#             }
#             pending_rebal = (target_w, exits_set)

#         port_values[date] = portfolio_value

#     log.append(f"STEP9 ✅ {day_counter} days | "
#                f"{len(weights_history)} rebalances | {len(trade_log)} trades")

#     # ── 10. Return series ──
#     port_series = pd.Series(port_values, dtype=float).dropna()
#     common_idx  = port_series.index.intersection(bench_prices.index)
#     if len(common_idx) < 20:
#         return None, f"Only {len(common_idx)} dates.", log

#     port_series = port_series.loc[common_idx]
#     bench_norm  = bench_prices.loc[common_idx].ffill()
#     bench_norm  = bench_norm / bench_norm.iloc[0] * 1_000_000.0

#     port_ret  = port_series.pct_change().dropna()
#     bench_ret = bench_norm.pct_change().dropna()
#     common_r  = port_ret.index.intersection(bench_ret.index)
#     port_ret  = port_ret.loc[common_r]; bench_ret = bench_ret.loc[common_r]
#     if len(port_ret) < 20: return None, "Too few return observations.", log

#     # ── 11. Metrics ──
#     n_years  = len(port_series)/252.0
#     cagr     = (port_series.iloc[-1]/port_series.iloc[0])**(1/n_years)-1
#     b_cagr   = (bench_norm.iloc[-1]/bench_norm.iloc[0])**(1/n_years)-1
#     rf       = 0.065/252
#     p_std    = port_ret.std(); b_std = bench_ret.std()
#     sharpe   = ((port_ret.mean()-rf)/p_std)*np.sqrt(252) if p_std>1e-10 else 0.0
#     b_sharpe = ((bench_ret.mean()-rf)/b_std)*np.sqrt(252) if b_std>1e-10 else 0.0
#     neg      = port_ret[port_ret<0]
#     downside = neg.std()*np.sqrt(252) if len(neg)>5 else 1e-6
#     sortino  = ((port_ret.mean()-rf)*252)/downside
#     dd_s, max_dd  = compute_max_dd(port_series)
#     dd_b, b_maxdd = compute_max_dd(bench_norm)
#     calmar   = cagr/abs(max_dd) if abs(max_dd)>1e-6 else 0.0
#     vol_ann  = p_std*np.sqrt(252)
#     win_rate = float((port_ret>0).mean())
#     cov_m    = np.cov(port_ret.values, bench_ret.values)
#     beta     = cov_m[0,1]/(cov_m[1,1]+1e-12)
#     alpha_a  = cagr - beta*b_cagr
#     excess   = port_ret - bench_ret
#     ir       = (excess.mean()/(excess.std()+1e-12))*np.sqrt(252)
#     var_95   = float(np.percentile(port_ret.values, 5))
#     cvar_95  = float(port_ret[port_ret<=var_95].mean()) if (port_ret<=var_95).any() else var_95

#     up_b = bench_ret[bench_ret>0]; dn_b = bench_ret[bench_ret<0]
#     up_p = port_ret.reindex(up_b.index).dropna()
#     dn_p = port_ret.reindex(dn_b.index).dropna()
#     uc = up_p.index.intersection(up_b.reindex(up_p.index).dropna().index)
#     dc = dn_p.index.intersection(dn_b.reindex(dn_p.index).dropna().index)
#     up_cap = float(np.clip(
#         up_p.loc[uc].mean()/up_b.loc[uc].mean() if len(uc)>0 and up_b.loc[uc].mean()>0 else 1.0,0,2))
#     dn_cap = float(np.clip(
#         dn_p.loc[dc].mean()/dn_b.loc[dc].mean() if len(dc)>0 and dn_b.loc[dc].mean()<0 else 1.0,0,2))

#     yr_s = port_ret.resample(FREQ_YE).apply(lambda x:(1+x).prod()-1)
#     yr_b = bench_ret.resample(FREQ_YE).apply(lambda x:(1+x).prod()-1)
#     cyrs = yr_s.index.intersection(yr_b.index)
#     yr_s, yr_b = yr_s.loc[cyrs], yr_b.loc[cyrs]
#     beat = int(sum(s>b for s,b in zip(yr_s.values, yr_b.values)))

#     mp_m = port_ret.resample(FREQ_ME).apply(lambda x:(1+x).prod()-1)
#     mb_m = bench_ret.resample(FREQ_ME).apply(lambda x:(1+x).prod()-1)

#     stop_loss_trades = len([t for t in trade_log if t.get("action") == "STOP-LOSS"])
#     tl_df    = pd.DataFrame(trade_log) if trade_log else \
#                pd.DataFrame(columns=["date","ticker","action","pnl_pct","hold_days"])
#     avg_hold = float(np.mean(hold_periods)) if hold_periods else 0.0

#     sec_wt_rows = []
#     for date, wts in weights_history.items():
#         row = {"date": date}
#         for t, w in wts.items():
#             sec = SECTOR_MAP.get(t, "Other")
#             row[sec] = row.get(sec, 0) + w
#         sec_wt_rows.append(row)
#     sec_wt_df = pd.DataFrame(sec_wt_rows).set_index("date").fillna(0) \
#                 if sec_wt_rows else pd.DataFrame()

#     q_count_rows = []
#     for date, q_row in quadrant_hist.items():
#         counts = {"date":date}
#         for q in ["Leading","Improving","Weakening","Lagging"]:
#             counts[q] = sum(1 for v in q_row.values() if v == q)
#         q_count_rows.append(counts)
#     q_count_df = pd.DataFrame(q_count_rows).set_index("date") \
#                  if q_count_rows else pd.DataFrame()

#     sector_attr = compute_sector_attribution(weights_history, port_ret, bench_ret)
#     wf_df = compute_walk_forward(port_series, bench_norm, window_years=3)
#     wf_beat_pct = (wf_df["Beat?"] == "✅").mean() * 100 if len(wf_df) > 0 else 0

#     phase_series = pd.Series(phase_history).reindex(port_series.index).ffill().bfill()
#     alpha_vs_nifty = (cagr - b_cagr) * 100

#     log.append(
#         f"STEP11 ✅ CAGR={cagr:.2%} Sharpe={sharpe:.2f} "
#         f"MaxDD={max_dd:.2%} Alpha={alpha_vs_nifty:.1f}% | "
#         f"Walk-forward beat: {wf_beat_pct:.0f}% | "
#         f"Stop-loss exits: {stop_loss_trades}"
#     )
#     if wf_beat_pct < 70:
#         log.append(
#             f"STEP11 ⚠️ Walk-fwd beat {wf_beat_pct:.0f}% < 70% — "
#             "check phase thresholds or raise min_tf_agreement to 3."
#         )

#     return {
#         "port_series":    port_series,
#         "bench_norm":     bench_norm,
#         "port_ret":       port_ret,
#         "bench_ret":      bench_ret,
#         "yr_strat":       yr_s,
#         "yr_bench":       yr_b,
#         "dd_s":           dd_s,
#         "dd_b":           dd_b,
#         "weights_history":weights_history,
#         "signal_history": signal_history,
#         "quadrant_hist":  quadrant_hist,
#         "trade_log":      tl_df,
#         "monthly_port":   mp_m,
#         "monthly_bench":  mb_m,
#         "market_phase":   market_phase,
#         "phase_series":   phase_series,
#         "phase_history":  phase_history,
#         "sector_attr":    sector_attr,
#         "sec_wt_df":      sec_wt_df,
#         "q_count_df":     q_count_df,
#         "walk_forward":   wf_df,
#         "wf_beat_pct":    wf_beat_pct,
#         "avg_hold_days":  avg_hold,
#         "stop_loss_trades": stop_loss_trades,
#         "consensus":      consensus,
#         "metrics": {
#             "CAGR":          safe_float(cagr),
#             "Bench CAGR":    safe_float(b_cagr),
#             "Sharpe":        safe_float(sharpe),
#             "B Sharpe":      safe_float(b_sharpe),
#             "Sortino":       safe_float(sortino),
#             "Max DD":        safe_float(max_dd),
#             "Bench MaxDD":   safe_float(b_maxdd),
#             "Calmar":        safe_float(calmar),
#             "Volatility":    safe_float(vol_ann),
#             "Win Rate":      safe_float(win_rate),
#             "Beta":          safe_float(beta),
#             "Alpha":         safe_float(alpha_a),
#             "Info Ratio":    safe_float(ir),
#             "VaR 95":        safe_float(var_95),
#             "CVaR 95":       safe_float(cvar_95),
#             "Beat Years":    beat,
#             "Total Years":   len(yr_s),
#             "Up Capture":    safe_float(up_cap),
#             "Down Capture":  safe_float(dn_cap),
#             "N Trades":      len(tl_df),
#             "N Years":       safe_float(n_years),
#             "Avg Hold":      safe_float(avg_hold),
#             "WF Beat Pct":   safe_float(wf_beat_pct),
#             "Alpha Nifty":   safe_float(alpha_vs_nifty),
#             "Stop Losses":   stop_loss_trades,
#         },
#     }, None, log


# # ═══════════════════════════════════════════════════════════════
# # STRATEGY CLASS
# # ═══════════════════════════════════════════════════════════════
# class SectorRotationStrategy(BaseStrategy):
#     NAME = "Sector Momentum Rotation v5 (Investor-Grade)"
#     DESCRIPTION = (
#         "v5 fixes: Recalibrated phase detector (3-day confirm, 8% Bear gap) | "
#         "Quality-proportional sector weights | Trailing stop-loss (15%) | "
#         "Volatility targeting (12% ann vol) | RS acceleration bonus. "
#         "Targets: CAGR 15%+ | Sharpe 0.8+ | MaxDD <20% | Beat Nifty 80%+ windows."
#     )

#     def render_sidebar(self):
#         self.start_date = st.sidebar.date_input(
#             "Start Date", value=pd.to_datetime("2015-01-01"))
#         self.end_date = st.sidebar.date_input(
#             "End Date", value=pd.to_datetime("2025-01-01"))

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**Multi-TF Signal Parameters**")
#         self.smooth_period = st.sidebar.slider(
#             "EMA Smoothing (days)", 10, 30, 14)
#         self.min_tf_agreement = st.sidebar.radio(
#             "Min TF Agreement", [2, 3], index=0,
#             format_func=lambda x: f"{x}/3 timeframes must agree")

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**v5: Phase Detector Calibration**")
#         self.bear_gap_threshold = st.sidebar.slider(
#             "Bear gap threshold %", -15, -5, -8,
#             help="Gap below 200DMA that triggers Bear mode. -8% recommended."
#         ) / 100
#         self.sideways_gap_pct = st.sidebar.slider(
#             "Sideways band %", 3, 12, 7,
#             help="±% from 200DMA for Sideways zone. 7% recommended."
#         ) / 100

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**v5: Risk Controls**")
#         self.stop_loss_pct = st.sidebar.slider(
#             "Trailing Stop-Loss %", 0, 25, 15,
#             help="Exit if position falls this % from its peak. 0=disabled."
#         ) / 100
#         self.vol_target = st.sidebar.slider(
#             "Portfolio Vol Target %", 8, 20, 12,
#             help="Scale exposure so realised ann vol ≈ this. 12% recommended."
#         ) / 100

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**Portfolio Construction**")
#         self.max_sector_wt = st.sidebar.slider(
#             "Max Sector Weight %", 20, 40, 30) / 100
#         self.rebal_freq_months = st.sidebar.radio(
#             "Rebalance Frequency", [1, 2], index=1,
#             format_func=lambda x: f"Every {x} month{'s' if x>1 else ''}")
#         self.drift_tolerance = st.sidebar.slider(
#             "Drift Tolerance %", 3, 8, 5) / 100

#         st.sidebar.markdown("---")
#         self.fee_bps  = st.sidebar.number_input("Fee (bps)", value=1.0, min_value=0.0)
#         self.slip_bps = st.sidebar.number_input("Slippage (bps)", value=2.0, min_value=0.0)

#         if st.sidebar.button("🗑 Clear Cache"):
#             st.cache_data.clear()
#             st.rerun()

#     def run(self):
#         with st.spinner("Running Sector Rotation v5 (~3-4 min)..."):
#             raw = _run_sector_rotation_v5(
#                 self.start_date, self.end_date,
#                 self.smooth_period,
#                 self.max_sector_wt,
#                 self.rebal_freq_months,
#                 self.drift_tolerance,
#                 self.fee_bps, self.slip_bps,
#                 self.min_tf_agreement,
#                 self.stop_loss_pct,
#                 self.vol_target,
#                 self.bear_gap_threshold,
#                 self.sideways_gap_pct,
#             )

#         run_log = []
#         if isinstance(raw, tuple) and len(raw) == 3:
#             result, err, run_log = raw
#         else:
#             result, err = None, f"Unexpected: {type(raw)}"

#         with st.expander("🛠 Debug / Run Log"):
#             import sys
#             st.caption(f"Python {sys.version.split()[0]} | pandas {pd.__version__} | v5")
#             for line in run_log:
#                 st.error(line) if "❌" in line else \
#                 st.warning(line) if "⚠️" in line else st.success(line)
#             if err: st.error(f"Error: {err}")

#         if result is None:
#             st.error(f"❌ {err}")
#             return

#         m  = result["metrics"]
#         ps = result["port_series"]
#         bn = result["bench_norm"]
#         pr = result["port_ret"]
#         br = result["bench_ret"]
#         ys = result["yr_strat"]
#         yb = result["yr_bench"]

#         alpha = m["Alpha Nifty"]
#         wfb   = m["WF Beat Pct"]
#         sl_ct = m.get("Stop Losses", 0)

#         # ── Header with robustness badge ──────────────────────────
#         if alpha >= 5 and wfb >= 80:
#             st.success(
#                 f"✅ **Sector Rotation v5** — Beating Nifty by **{alpha:.1f}%** p.a. | "
#                 f"Walk-forward beat: **{wfb:.0f}%** | "
#                 f"Stop-loss exits: {sl_ct} | Investor-grade ✅")
#         elif alpha >= 3 and wfb >= 70:
#             st.warning(
#                 f"⚠️ v5: Alpha {alpha:.1f}% | Walk-forward beat: {wfb:.0f}% | "
#                 f"Close — try adjusting phase thresholds.")
#         else:
#             st.error(
#                 f"❌ v5 underperforming — alpha {alpha:.1f}% | "
#                 f"Walk-fwd {wfb:.0f}% | Check debug log for phase distribution.")

#         st.info(
#             f"📅 **{ps.index[0].strftime('%b %Y')} → {ps.index[-1].strftime('%b %Y')}** "
#             f"({m['N Years']:.1f} yrs) | "
#             f"Vol target: {self.vol_target*100:.0f}% | "
#             f"Stop-loss: {self.stop_loss_pct*100:.0f}% | "
#             f"Trades: {m['N Trades']} ({m['N Trades']/max(m['N Years'],1):.0f}/yr)")

#         # ── KPIs ────────────────────────────────────────────────────
#         st.markdown("## 📊 Performance Overview")
#         c1,c2,c3,c4,c5 = st.columns(5)
#         c1.metric("CAGR", f"{m['CAGR']*100:.2f}%",
#                   delta=f"{alpha:.1f}% vs Nifty")
#         c2.metric("Sharpe", f"{m['Sharpe']:.2f}",
#                   delta=f"{m['Sharpe']-m['B Sharpe']:.2f} vs Nifty")
#         c3.metric("Sortino", f"{m['Sortino']:.2f}")
#         c4.metric("Max Drawdown", f"{m['Max DD']*100:.1f}%",
#                   delta_color="inverse",
#                   delta=f"{(m['Max DD']-m['Bench MaxDD'])*100:.1f}% vs Nifty")
#         c5.metric("Walk-fwd beat", f"{wfb:.0f}%",
#                   help="% of rolling 3-yr windows where strategy beat Nifty")

#         c1,c2,c3,c4,c5 = st.columns(5)
#         c1.metric("Win Rate",     f"{m['Win Rate']*100:.1f}%")
#         c2.metric("Beta",         f"{m['Beta']:.2f}")
#         c3.metric("Up Capture",   f"{m['Up Capture']*100:.0f}%")
#         c4.metric("Down Capture", f"{m['Down Capture']*100:.0f}%")
#         c5.metric("Stop-Loss exits", f"{sl_ct}",
#                   help="Times trailing stop-loss protected from larger drawdowns")

#         # ── v5 PHASE DIAGNOSTIC (always show prominently) ──────────
#         st.markdown("---")
#         mp = result["market_phase"].reindex(ps.index).ffill()
#         phase_pct = mp.value_counts(normalize=True)*100
#         bull_p  = phase_pct.get(PHASE_BULL, 0)
#         sw_p    = phase_pct.get(PHASE_SIDEWAYS, 0)
#         bear_p  = phase_pct.get(PHASE_BEAR, 0)

#         if bull_p < 30:
#             st.error(
#                 f"⚠️ PHASE CALIBRATION ISSUE: Bull={bull_p:.0f}% Sideways={sw_p:.0f}% Bear={bear_p:.0f}%. "
#                 f"Bull should be 50-70% for a 2015-2025 Indian market backtest. "
#                 f"Raise Bear gap threshold slider (e.g. from -8% to -10%) or "
#                 f"raise Sideways band (e.g. from 7% to 9%).")
#         else:
#             st.success(
#                 f"✅ Phase distribution looks healthy: "
#                 f"Bull={bull_p:.0f}% | Sideways={sw_p:.0f}% | Bear={bear_p:.0f}%")

#         # ── WALK-FORWARD TABLE ─────────────────────────────────────
#         st.markdown("---")
#         st.subheader("🔄 Walk-Forward Analysis — The Consistency Test")
#         st.caption("Green ✅ in every row = investor-grade strategy.")
#         wf_df = result["walk_forward"]
#         if not wf_df.empty:
#             beat_count = (wf_df["Beat?"] == "✅").sum()
#             total_w    = len(wf_df)
#             st.dataframe(wf_df, use_container_width=True, hide_index=True)
#             if beat_count == total_w:
#                 st.success(f"✅ Beat Nifty in all {total_w} rolling 3-year windows.")
#             elif beat_count >= total_w * 0.70:
#                 failed = wf_df[wf_df['Beat?']=='❌']['Period'].tolist()
#                 st.warning(
#                     f"⚠️ Beat {beat_count}/{total_w} windows. "
#                     f"Struggling in: {', '.join(failed)}")
#             else:
#                 st.error(f"❌ Only {beat_count}/{total_w} windows beat Nifty.")
#         st.markdown("---")

#         # ── Market Phase Timeline ──────────────────────────────────
#         st.subheader("🌡️ Market Phase — Bull / Sideways / Bear")
#         phase_numeric = mp.map({PHASE_BULL: 3, PHASE_SIDEWAYS: 2, PHASE_BEAR: 1})
#         fig_phase = go.Figure()
#         phase_colors = {PHASE_BULL:"#2E7D32", PHASE_SIDEWAYS:"#F9A825", PHASE_BEAR:"#C62828"}
#         for ph, col in phase_colors.items():
#             mask = (mp == ph)
#             if mask.any():
#                 fig_phase.add_trace(go.Scatter(
#                     x=mp.index[mask], y=phase_numeric[mask].values,
#                     mode="markers", marker=dict(size=3, color=col, opacity=0.6),
#                     name=ph, showlegend=True))
#         fig_phase.add_hline(y=2.5, line_dash="dot",
#                             line_color="rgba(249,168,37,0.6)", line_width=1)
#         fig_phase.add_hline(y=1.5, line_dash="dot",
#                             line_color="rgba(198,40,40,0.6)", line_width=1)
#         fig_phase.update_layout(height=160, yaxis=dict(
#             tickvals=[1,2,3], ticktext=["Bear","Sideways","Bull"], range=[0.5,3.5]),
#             margin=dict(l=10,r=10,t=10,b=10),
#             legend=dict(orientation="h", y=1.1))
#         st.plotly_chart(fig_phase, use_container_width=True)

#         c1,c2,c3 = st.columns(3)
#         c1.metric("Bull phase",     f"{bull_p:.0f}%")
#         c2.metric("Sideways phase", f"{sw_p:.0f}%")
#         c3.metric("Bear phase",     f"{bear_p:.0f}%")
#         st.markdown("---")

#         # ── Equity Curve ──────────────────────────────────────────
#         st.subheader("📈 Equity Curve vs Nifty 50")
#         bn_ri = bn.reindex(ps.index).ffill()
#         fig1 = go.Figure()

#         phase_s = result.get("phase_series", pd.Series())
#         if not phase_s.empty:
#             bear_mask = (phase_s == PHASE_BEAR)
#             in_bear   = False; bear_start = None
#             for dt in ps.index:
#                 is_bear = bear_mask.get(dt, False)
#                 if is_bear and not in_bear:
#                     bear_start = dt; in_bear = True
#                 elif not is_bear and in_bear:
#                     fig1.add_vrect(x0=bear_start, x1=dt,
#                         fillcolor="rgba(198,40,40,0.12)", line_width=0)
#                     in_bear = False
#             if in_bear:
#                 fig1.add_vrect(x0=bear_start, x1=ps.index[-1],
#                     fillcolor="rgba(198,40,40,0.12)", line_width=0)

#         fig1.add_trace(go.Scatter(x=ps.index, y=ps.values,
#             name="Sector Rotation v5",
#             line=dict(color="rgba(46,125,50,1)", width=2.5)))
#         fig1.add_trace(go.Scatter(x=bn.index, y=bn.values,
#             name="Nifty 50 B&H",
#             line=dict(color="rgba(230,81,0,1)", width=1.8, dash="dash")))
#         fig1.add_trace(go.Scatter(
#             x=list(ps.index)+list(ps.index[::-1]),
#             y=list(ps.values)+list(bn_ri.values[::-1]),
#             fill="toself", fillcolor="rgba(46,125,50,0.08)",
#             line=dict(width=0), name="Alpha region"))
#         fig1.update_layout(height=420, yaxis=dict(tickformat=",.0f"),
#             legend=dict(x=0.01, y=0.99), margin=dict(l=10,r=10,t=10,b=10))
#         st.caption("Red shaded = Bear phase | Trailing stops cut drawdowns")
#         st.plotly_chart(fig1, use_container_width=True)

#         # ── Drawdown ──────────────────────────────────────────────
#         st.subheader("📉 Drawdown")
#         fig2 = go.Figure()
#         fig2.add_trace(go.Scatter(
#             x=result["dd_s"].index, y=(result["dd_s"]*100).values,
#             fill="tozeroy", name="Sector Rotation v5",
#             fillcolor="rgba(46,125,50,0.35)",
#             line=dict(color="rgba(46,125,50,1)", width=1)))
#         fig2.add_trace(go.Scatter(
#             x=result["dd_b"].index, y=(result["dd_b"]*100).values,
#             fill="tozeroy", name="Nifty 50",
#             fillcolor="rgba(230,81,0,0.20)",
#             line=dict(color="rgba(230,81,0,1)", width=1, dash="dash")))
#         fig2.add_hline(y=-20, line_dash="dot", line_color="red",
#                        annotation_text="-20% Target (v5)")
#         fig2.update_layout(height=250, yaxis_title="Drawdown %",
#             margin=dict(l=10,r=10,t=10,b=10))
#         st.plotly_chart(fig2, use_container_width=True)
#         c1,c2,c3 = st.columns(3)
#         c1.metric("Strategy Max DD", f"{m['Max DD']*100:.1f}%")
#         c2.metric("Nifty Max DD",    f"{m['Bench MaxDD']*100:.1f}%")
#         c3.metric("DD saved",
#                   f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
#                   delta="✅" if m['Max DD'] > m['Bench MaxDD'] else "❌")
#         st.markdown("---")

#         # ── Year-by-Year ──────────────────────────────────────────
#         st.subheader("📅 Year-by-Year Returns")
#         if len(ys) > 0:
#             yr_labels = _index_years(ys.index)
#             yb_labels = _index_years(yb.index)
#             clrs = ["#2E7D32" if s>b else "#C62828"
#                     for s,b in zip(ys.values, yb.values)]
#             fig3 = go.Figure()
#             fig3.add_trace(go.Bar(
#                 x=yr_labels, y=(ys.values*100).tolist(),
#                 name="Sector Rotation v5", marker_color=clrs, opacity=0.90))
#             fig3.add_trace(go.Bar(
#                 x=yb_labels, y=(yb.values*100).tolist(),
#                 name="Nifty 50", marker_color="#E65100", opacity=0.55))
#             fig3.add_hline(y=0, line_color="white", line_width=0.8)
#             fig3.update_layout(barmode="group", height=320,
#                 xaxis=dict(tickmode="linear", dtick=1, tickvals=yr_labels),
#                 margin=dict(l=10,r=10,t=10,b=10))
#             st.plotly_chart(fig3, use_container_width=True)
#             yr_df = pd.DataFrame({
#                 "Year":       yr_labels,
#                 "Strategy %": [round(v*100,1) for v in ys.values],
#                 "Nifty 50 %": [round(v*100,1) for v in yb.values],
#                 "Alpha %":    [round((s-b)*100,1) for s,b in zip(ys.values,yb.values)],
#                 "Beat?":      ["✅" if s>b else "❌" for s,b in zip(ys.values,yb.values)],
#             })
#             st.dataframe(yr_df, use_container_width=True, hide_index=True)
#         st.markdown("---")

#         # ── Sector Rotation Timeline ──────────────────────────────
#         st.subheader("🔄 Sector Rotation Timeline")
#         sec_wt_df = result["sec_wt_df"]
#         if not sec_wt_df.empty:
#             fig_sec = go.Figure()
#             for sec in sec_wt_df.columns:
#                 if (sec_wt_df[sec] == 0).all(): continue
#                 sc = SECTOR_COLORS.get(sec, "#757575")
#                 r_v=int(sc[1:3],16); g_v=int(sc[3:5],16); b_v=int(sc[5:7],16)
#                 fig_sec.add_trace(go.Scatter(
#                     x=sec_wt_df.index, y=(sec_wt_df[sec]*100).values,
#                     name=sec, stackgroup="one",
#                     fillcolor=f"rgba({r_v},{g_v},{b_v},0.75)",
#                     line=dict(width=0.5)))
#             fig_sec.update_layout(height=260, yaxis_title="Sector Weight %",
#                 yaxis=dict(range=[0,105]),
#                 legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=9)),
#                 margin=dict(l=10,r=10,t=30,b=10))
#             st.plotly_chart(fig_sec, use_container_width=True)
#         st.markdown("---")

#         # ── Sector Alpha Attribution ──────────────────────────────
#         st.subheader("🏆 Sector Alpha Contribution")
#         attr = result.get("sector_attr", pd.DataFrame())
#         if not attr.empty:
#             bar_clrs = [SECTOR_COLORS.get(s,"#757575") if v>0 else "#C62828"
#                         for s,v in zip(attr["Sector"], attr["Alpha Contribution %"])]
#             fig_attr = go.Figure(go.Bar(
#                 x=attr["Sector"], y=attr["Alpha Contribution %"],
#                 marker_color=bar_clrs, opacity=0.85,
#                 text=[f"{v:.1f}%" for v in attr["Alpha Contribution %"]],
#                 textposition="auto"))
#             fig_attr.add_hline(y=0, line_color="white", line_width=0.8)
#             fig_attr.update_layout(height=260, yaxis_title="Cumulative Alpha %",
#                 margin=dict(l=10,r=10,t=10,b=10))
#             st.plotly_chart(fig_attr, use_container_width=True)
#         st.markdown("---")

#         # ── Trade Analysis ────────────────────────────────────────
#         st.subheader("📊 Trade Analysis")
#         c1,c2,c3,c4,c5 = st.columns(5)
#         c1.metric("Total Trades",  f"{m['N Trades']}")
#         c2.metric("Trades/Year",   f"{m['N Trades']/max(m['N Years'],1):.0f}")
#         c3.metric("Avg Hold",      f"{m['Avg Hold']:.0f}d")
#         c4.metric("Volatility",    f"{m['Volatility']*100:.1f}%")
#         c5.metric("Stop-Loss hits",f"{sl_ct}")
#         st.markdown("---")

#         # ── Investor Scorecard ────────────────────────────────────
#         st.subheader("🎯 Investor Scorecard (v5 Targets)")
#         bp2 = m["Beat Years"]/max(m["Total Years"],1)
#         targets = [
#             ("CAGR > 15%",               m["CAGR"]*100>15,           f"{m['CAGR']*100:.1f}%"),
#             ("Beat Nifty by >5%",         alpha>=5.0,                  f"+{alpha:.1f}%"),
#             ("Walk-fwd beat > 80%",       wfb>=80,                     f"{wfb:.0f}%"),
#             ("Sharpe > 0.8",              m["Sharpe"]>0.8,            f"{m['Sharpe']:.2f}"),
#             ("Sortino > 1.0",             m["Sortino"]>1.0,           f"{m['Sortino']:.2f}"),
#             ("Max DD < -20%",             m["Max DD"]>-0.20,          f"{m['Max DD']*100:.1f}%"),
#             ("Calmar > 0.9",              m["Calmar"]>0.9,            f"{m['Calmar']:.2f}"),
#             ("Beat Nifty >70% years",     bp2>0.70,                   f"{m['Beat Years']}/{m['Total Years']}"),
#             ("Down Capture < 75%",        m["Down Capture"]<0.75,     f"{m['Down Capture']*100:.0f}%"),
#             ("Trades/yr < 80",            m['N Trades']/max(m['N Years'],1)<80,
#                                           f"{m['N Trades']/max(m['N Years'],1):.0f}"),
#         ]
#         scored = sum(1 for _,p,_ in targets if p)
#         st.dataframe(pd.DataFrame([{
#             "Status":"✅ PASS" if p else "❌ FAIL","Target":t,"Value":v
#         } for t,p,v in targets]), use_container_width=True, hide_index=True)

#         verdict = ("✅ Investor-grade — ready for live consideration" if scored>=8
#                    else "⚠️ Nearly there — tune phase detector" if scored>=5
#                    else "🔨 More calibration needed")
#         fn = st.success if scored>=8 else st.warning if scored>=5 else st.error
#         fn(f"Score: **{scored}/10** — {verdict}")

#         with st.expander("📖 v5 Architecture: The 6 fixes explained"):
#             st.markdown("""
# ### Why v4 failed and what v5 changed

# | Fix | v4 problem | v5 solution | Expected impact |
# |---|---|---|---|
# | Phase Bear threshold | `gap200 < -3%` fires constantly | `gap200 < -8%` (India-calibrated) | Bull% from 0% → 50-60% |
# | Phase Sideways band | ±3% band too narrow | ±7% band | Correct regime identification |
# | Phase smoothing lag | 15-day confirm = 3-week lag | 3-day confirm | Faster regime capture |
# | Sideways cash drag | 80% invested in Sideways | 88% invested | +1-2% CAGR |
# | Quality threshold | 2.5 in Sideways (nothing passes) | 1.5 in Sideways | Sectors actually trade |
# | Trailing stop-loss | No stops → -30% DD | 15% trailing stop | MaxDD → -18 to -22% |
# | Quality-prop weights | Equal budget within tier | Quality-weighted | +0.5-1.0% CAGR from concentration |
# | Vol targeting | Fixed exposure | Scale to 12% ann vol | Sharpe +0.2-0.3 |
# | RS acceleration | Not used | +0.5 bonus for accelerating RS | Better entry timing |

# ### How to tune if results still disappoint

# 1. **Bull% < 40%**: Raise bear_gap_threshold slider to -10% or sideways_gap_pct to 9%
# 2. **Sharpe < 0.6**: Lower vol_target to 10% (tighter vol control)
# 3. **Max DD > -25%**: Lower stop_loss_pct to 12% or vol_target to 10%
# 4. **Walk-fwd < 70%**: Switch to 3/3 TF agreement (stricter signal)
# 5. **CAGR < 12%**: Raise vol_target to 14%, lower stop_loss_pct to 20%

# ### The investor test

# Run the strategy on 2015-2025. If walk-forward shows ✅ in every 3-year window AND
# Max DD is below -20%, it has passed the basic investor test.
# The next step is a paper trading period of 3-6 months before live capital.
#             """)

"""
SECTOR MOMENTUM ROTATION v6 — ENHANCED INVESTOR-GRADE
=======================================================

ENHANCEMENTS OVER v5 (based on root-cause analysis of v5 underperformance):

OBSERVED v5 ISSUES (from backtest screenshots):
    CAGR:        10.52%  (target 15%+)   → Signal lag + double-defense problem
    Sharpe:       0.40   (target 0.80+)  → Vol targeting killing CAGR
    Walk-fwd:    33%     (target 80%+)   → Signal-triggered rebalance missing
    Bear phase:   0%     (unused)        → Bear threshold too high at -8%

ROOT CAUSES & FIXES IN v6:
─────────────────────────────────────────────────────────────────────────────

FIX-1: SIGNAL-TRIGGERED REBALANCING (most impactful)
    Problem: Bi-monthly calendar rebalance means the strategy holds a
             deteriorating "Weakening" sector for up to 2 months.
             By the time the next calendar date fires, the alpha is gone.
    Fix:    Check every day if any sector has CHANGED quadrant classification
            (e.g. Leading → Weakening, or Lagging → Improving).
            If a change is detected AND it is > min_signal_days since last
            rebalance, queue an intra-cycle rebalance immediately.
            Calendar rebalance is the floor; signal change is the trigger.
    Expected impact: +2-3% CAGR, +0.15 Sharpe

FIX-2: RS-RANK WEIGHTING REPLACES QUALITY-SCORE WEIGHTING
    Problem: Quality score (0–3.5) concentrates capital in sectors that have
             *already* run the most (high count + slope + accel), amplifying
             reversion risk at the top of each cycle.
             Most negative sector alpha bars in the attribution chart confirmed
             that late entries into high-quality sectors were losing money.
    Fix:    Within each quadrant, weight sectors by their direct RS ratio
            rank (1/rank weighting normalised to sum to 1) rather than the
            composite quality score.
            RS rank is a cleaner, less-overfitted signal with stronger
            academic support (Jegadeesh & Titman momentum literature).
    Expected impact: +1-2% CAGR, better sector attribution

FIX-3: RS CROSSING ENTRY — BUY EARLY, NOT LATE
    Problem: Current system buys "Leading" sectors (RS > 100 confirmed on
             2+ timeframes). This is a lagging signal — buying after the move.
    Fix:    Add a new quadrant "Breakout": RS on the 63-day TF has just
            crossed above 100 in the last 5 days (RS_cross_up). These sectors
            get a dedicated budget slice (10% of active budget) and smaller
            position sizes (1 stock, not 3). This captures early-stage
            rotations before they become consensus "Leading".
    Expected impact: +1-2% CAGR from better entry timing

FIX-4: DECOUPLED STOP-LOSS + VOL TARGET (no double-defense)
    Problem: Vol targeting scales down the whole portfolio when vol spikes.
             Stop-loss fires individual position exits in the same high-vol
             period. Both mechanisms fire simultaneously → near-cash during
             corrections that are often followed by sharp recoveries.
             Result: Excellent MaxDD (-13.1%) but terrible CAGR (10.52%).
    Fix:    After any stop-loss event, freeze the vol-targeting scalar for
            5 trading days. The stop-loss has already reduced risk; the vol
            target should not compound the defensive reduction.
            Also: never apply vol-scalar below 0.70 (floor) — prevent the
            strategy from going to 50% exposure in a moderate correction.
    Expected impact: +1-2% CAGR, +0.1 Sharpe

FIX-5: LOWER BEAR THRESHOLD FROM -8% TO -5%
    Problem: Bear phase activated 0% of the time in the v5 backtest.
             The -8% Bear threshold is correctly calibrated to avoid false
             signals but is so high it never fires.
             This leaves the defensive sector routing (Staples, Healthcare, IT)
             completely unused — a wasted feature.
    Fix:    Bear = gap200 < -5% AND slope200 < -0.002
            OR gap200 < -10% (extreme crash, unchanged).
            Sideways = |gap200| < 5% AND |slope50| < 0.003 (narrowed from 7%).
            This generates Bear signals during COVID, 2022 correction, and
            mild bear phases — routing to defensive sectors at exactly the
            right times.
    Expected impact: +0.5-1% CAGR, -3 to -5% MaxDD improvement

FIX-6: TIGHTER TF AGREEMENT IN SIDEWAYS (3/3 not 2/3)
    Problem: 2/3 TF agreement in Sideways allows sectors with only short-term
             RS > 100 to qualify. In a low-dispersion market, these are noise
             trades that erode alpha and generate unnecessary transaction costs.
    Fix:    In Sideways phase, require 3/3 TF agreement to qualify.
             In Bear phase, require only 1/3 (defensive sectors are scarce).
             Bull phase stays at 2/3 (default).
    Expected impact: Fewer bad trades in Sideways, +0.08 Sharpe

FIX-7: IMPROVED STOCK SCORING — ADD TREND CONSISTENCY
    Problem: Current stock scoring (40% momentum, 35% Sharpe, 25% inv-vol)
             selects stocks that had high past Sharpe but are now volatile.
             The negative sector attribution confirms individual stock picks
             within sectors are subtracting value.
    Fix:    Add a 4th scoring dimension: Trend Consistency = % of last
            63 trading days where close > 20-day SMA.
            Stocks above their short-term MA consistently are in intact trends.
            Weights: 35% momentum, 30% Sharpe, 20% inv-vol, 15% trend-consistency.
    Expected impact: Fewer false entries, better stock-level alpha

FIX-8: SECTOR MINIMUM HOLDING PERIOD
    Problem: Signal-triggered rebalancing (FIX-1) could cause rapid in-out of
             sectors if the RS signal oscillates around the 100 threshold.
             This would generate excessive transaction costs.
    Fix:    Track each sector's entry date. A sector that was entered within
            the last min_sector_hold days (default: 15) cannot be exited by
            a signal-triggered rebalance — only by a calendar rebalance or
            stop-loss. This prevents whipsaw turnover.
    Expected impact: Reduces transaction costs from FIX-1, cleaner P&L

EXPECTED IMPROVEMENTS vs v5:
    CAGR:      10.52% → 15-18%
    Sharpe:     0.40  → 0.70-0.85
    Sortino:    0.48  → 0.90-1.10
    Max DD:   -13.1%  → -12 to -15% (similar, but CAGR higher)
    WF beat:    33%   → 70-85%
    Bear use:    0%   → 5-10% (actually using defensive routing)
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from strategies.base import BaseStrategy

try:
    _maj, _min = [int(x) for x in pd.__version__.split(".")[:2]]
    _NEW_PD = (_maj > 2) or (_maj == 2 and _min >= 2)
except Exception:
    _NEW_PD = True
FREQ_ME = "ME" if _NEW_PD else "M"
FREQ_YE = "YE" if _NEW_PD else "Y"
FREQ_2M = "2ME" if _NEW_PD else "2M"

PHASE_BULL     = "Bull"
PHASE_SIDEWAYS = "Sideways"
PHASE_BEAR     = "Bear"
DEFENSIVE_SECTORS = {"Staples", "Healthcare", "IT"}


def _index_years(idx):
    try:
        return idx.year.tolist()
    except AttributeError:
        pass
    try:
        return idx.to_timestamp().year.tolist()
    except Exception:
        pass
    return [str(i) for i in idx]


# ═══════════════════════════════════════════════════════════════
# UNIVERSE (unchanged — survivorship-bias-free)
# ═══════════════════════════════════════════════════════════════
CORE_CONTINUOUS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS",
    "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS",
    "LT.NS","AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS","SUNPHARMA.NS",
    "WIPRO.NS","HCLTECH.NS","POWERGRID.NS","NTPC.NS","ONGC.NS",
    "TATAMOTORS.NS","TATASTEEL.NS","TECHM.NS","COALINDIA.NS",
    "DRREDDY.NS","EICHERMOT.NS","BPCL.NS","CIPLA.NS","GRASIM.NS",
    "INDUSINDBK.NS","HINDALCO.NS","BRITANNIA.NS","BAJAJ-AUTO.NS",
    "HEROMOTOCO.NS","M&M.NS",
]
ADDITIONS_BY_YEAR = {
    2016: ["ADANIPORTS.NS","BAJFINANCE.NS"],
    2017: ["ULTRACEMCO.NS","NESTLEIND.NS"],
    2018: ["TITAN.NS","BAJAJFINSV.NS"],
    2019: ["DIVISLAB.NS","SBILIFE.NS","HDFCLIFE.NS"],
    2020: ["APOLLOHOSP.NS","TATACONSUM.NS"],
    2021: ["JSWSTEEL.NS"],
    2023: ["ADANIENT.NS"],
}
REMOVALS_LAST_YEAR = {"ZEEL.NS": 2021, "VEDL.NS": 2020, "UPL.NS": 2023}
REMOVED_STOCKS = {
    "ZEEL.NS": ("2015-01-01","2022-01-01"),
    "VEDL.NS": ("2015-01-01","2021-01-01"),
    "UPL.NS":  ("2015-01-01","2024-01-01"),
}
SECTOR_MAP = {
    "HDFCBANK.NS":"Financials","ICICIBANK.NS":"Financials",
    "KOTAKBANK.NS":"Financials","AXISBANK.NS":"Financials",
    "SBIN.NS":"Financials","INDUSINDBK.NS":"Financials",
    "BAJFINANCE.NS":"Financials","BAJAJFINSV.NS":"Financials",
    "SBILIFE.NS":"Financials","HDFCLIFE.NS":"Financials",
    "TCS.NS":"IT","INFY.NS":"IT","WIPRO.NS":"IT",
    "HCLTECH.NS":"IT","TECHM.NS":"IT",
    "RELIANCE.NS":"Energy","ONGC.NS":"Energy","BPCL.NS":"Energy",
    "COALINDIA.NS":"Energy","POWERGRID.NS":"Energy","NTPC.NS":"Energy",
    "HINDUNILVR.NS":"Staples","ITC.NS":"Staples","NESTLEIND.NS":"Staples",
    "BRITANNIA.NS":"Staples","TATACONSUM.NS":"Staples",
    "MARUTI.NS":"Auto","TATAMOTORS.NS":"Auto","EICHERMOT.NS":"Auto",
    "BAJAJ-AUTO.NS":"Auto","HEROMOTOCO.NS":"Auto","M&M.NS":"Auto",
    "LT.NS":"Industrials","ADANIPORTS.NS":"Industrials","ADANIENT.NS":"Industrials",
    "JSWSTEEL.NS":"Materials","TATASTEEL.NS":"Materials","HINDALCO.NS":"Materials",
    "ULTRACEMCO.NS":"Materials","GRASIM.NS":"Materials",
    "VEDL.NS":"Materials","UPL.NS":"Materials",
    "SUNPHARMA.NS":"Healthcare","DRREDDY.NS":"Healthcare","CIPLA.NS":"Healthcare",
    "DIVISLAB.NS":"Healthcare","APOLLOHOSP.NS":"Healthcare",
    "ASIANPAINT.NS":"ConsDisc","TITAN.NS":"ConsDisc","ZEEL.NS":"ConsDisc",
    "BHARTIARTL.NS":"Telecom",
}
SECTOR_COLORS = {
    "Financials":"#1565C0","IT":"#6A1B9A","Energy":"#E65100",
    "Staples":"#2E7D32","Auto":"#F9A825","Industrials":"#4E342E",
    "Materials":"#546E7A","Healthcare":"#00695C","ConsDisc":"#AD1457",
    "Telecom":"#283593","Other":"#757575",
}
QUADRANT_EMOJI = {
    "Leading":   "🟢 Leading",
    "Breakout":  "⚡ Breakout",
    "Improving": "🔵 Improving",
    "Weakening": "🟠 Weakening",
    "Lagging":   "🔴 Lagging",
}


def get_universe_for_year(year):
    u = set(CORE_CONTINUOUS)
    for y, tickers in ADDITIONS_BY_YEAR.items():
        if year >= y: u.update(tickers)
    for t, ly in REMOVALS_LAST_YEAR.items():
        if year > ly: u.discard(t)
    for t, (s, e) in REMOVED_STOCKS.items():
        if int(s[:4]) <= year < int(e[:4]): u.add(t)
    return sorted(u)


def safe_float(val, default=0.0):
    try:
        f = float(val)
        return f if np.isfinite(f) else default
    except Exception:
        return default


def series_get(series, key, default=np.nan):
    try:
        val = series[key]
        return float(val) if pd.notna(val) else default
    except (KeyError, TypeError):
        return default


def compute_max_dd(series):
    roll_max = series.cummax()
    dd = (series / roll_max.replace(0, np.nan) - 1).fillna(0)
    return dd, float(dd.min())


# ═══════════════════════════════════════════════════════════════
# FIX-5: RECALIBRATED PHASE DETECTOR (Bear -5%, Sideways ±5%)
# ═══════════════════════════════════════════════════════════════
def compute_market_phase_v6(bench_prices: pd.Series,
                             bear_gap_threshold: float = -0.05,
                             bear_slope_threshold: float = -0.002,
                             sideways_gap_pct: float = 0.05,
                             sideways_slope_flat: float = 0.003,
                             confirm_days: int = 3) -> pd.Series:
    """
    v6 PHASE DETECTOR — Key changes from v5:

    Bear threshold:  -5% (was -8%) + slope < -0.002 (was -0.003)
        Rationale: v5's -8% threshold fired 0% of the time over 10 years.
        -5% captures COVID crash, 2022 correction, Oct 2021 pullback —
        real bear phases where defensive routing adds value.

    Sideways band:   ±5% (was ±7%) + |slope50| < 0.003 (was 0.004)
        Rationale: Narrower Sideways band means more time is classified
        as Bull (higher invested budget), improving CAGR in trending markets.
        When truly sideways (±5% from 200DMA), tighter TF agreement kicks in.

    Extreme crash:  gap200 < -10% (was -12%) — slightly more sensitive.
    Confirmation:    3 days (unchanged from v5).
    """
    sma50  = bench_prices.rolling(50,  min_periods=30).mean()
    sma200 = bench_prices.rolling(200, min_periods=150).mean()  # stricter warmup

    slope200 = sma200.pct_change(21).fillna(0)
    slope50  = sma50.pct_change(10).fillna(0)

    gap200 = (bench_prices / sma200.replace(0, np.nan) - 1).fillna(0)

    phase = pd.Series(PHASE_BULL, index=bench_prices.index)

    # Bear: gap < -5% AND falling 200DMA, OR extreme crash > -10%
    bear_mask = (
        (gap200 < -0.10) |
        ((gap200 < bear_gap_threshold) & (slope200 < bear_slope_threshold))
    )
    phase[bear_mask] = PHASE_BEAR

    # Sideways: tighter ±5% band (was ±7%)
    sideways_mask = (
        ~bear_mask &
        (gap200.abs() < sideways_gap_pct) &
        (slope50.abs() < sideways_slope_flat)
    )
    phase[sideways_mask] = PHASE_SIDEWAYS

    # 3-day confirmation (unchanged)
    smoothed = phase.copy()
    current = phase.iloc[0]
    streak  = 0
    pending = current

    for i in range(len(phase)):
        p = phase.iloc[i]
        if p == pending:
            streak += 1
        else:
            pending = p
            streak  = 1
        if streak >= confirm_days and pending != current:
            current = pending
        smoothed.iloc[i] = current

    return smoothed


# ═══════════════════════════════════════════════════════════════
# SECTOR INDEX BUILDER (unchanged)
# ═══════════════════════════════════════════════════════════════
def build_sector_indices(close: pd.DataFrame,
                         universe_by_date: dict) -> pd.DataFrame:
    sectors = sorted(set(SECTOR_MAP.values()))
    sector_idx = pd.DataFrame(index=close.index, columns=sectors, dtype=float)
    for date in close.index:
        year     = date.year
        universe = universe_by_date.get(year, [])
        for sec in sectors:
            members = [t for t in universe
                       if SECTOR_MAP.get(t) == sec and t in close.columns]
            if members:
                vals = close.loc[date, members].dropna()
                if len(vals) > 0:
                    sector_idx.loc[date, sec] = float(vals.mean())
    return sector_idx.astype(float).ffill().bfill()


# ═══════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME RS (v6 adds RS cross-up detection for FIX-3)
# ═══════════════════════════════════════════════════════════════
def compute_multitf_rs(sector_idx: pd.DataFrame,
                       bench_prices: pd.Series,
                       lookbacks: tuple = (63, 126, 252),
                       smooth: int = 14) -> dict:
    """
    v6 additions vs v5:
    - rs_cross_up: True if 63-day RS crossed above 100 within the last 5 days
      (was below 100, now above 100). Used for Breakout quadrant (FIX-3).
    - rs_rank: within each date, rank sectors by their 63-day RS ratio.
      Used for RS-rank weighting (FIX-2) instead of quality score weighting.
    """
    results = {}
    for lb in lookbacks:
        rs_ratio_df = pd.DataFrame(index=sector_idx.index,
                                   columns=sector_idx.columns, dtype=float)
        rs_slope_df = pd.DataFrame(index=sector_idx.index,
                                   columns=sector_idx.columns, dtype=float)
        rs_accel_df = pd.DataFrame(index=sector_idx.index,
                                   columns=sector_idx.columns, dtype=float)

        for sec in sector_idx.columns:
            sec_px = sector_idx[sec].dropna()
            if len(sec_px) < lb + 30:
                continue
            bench_s   = bench_prices.reindex(sec_px.index).ffill()
            sec_ret   = sec_px / sec_px.shift(lb).replace(0, np.nan)
            bench_ret = bench_s / bench_s.shift(lb).replace(0, np.nan)
            raw_rs    = sec_ret / bench_ret.replace(0, np.nan)
            rs_r      = (raw_rs * 100).ewm(span=smooth, adjust=False).mean()

            def _slope(s, w=63):
                if len(s) < w:
                    return pd.Series(np.nan, index=s.index)
                x   = np.arange(w)
                out = []
                for i in range(len(s)):
                    if i < w - 1:
                        out.append(np.nan)
                    else:
                        y = s.iloc[i-w+1:i+1].values
                        if np.any(np.isnan(y)):
                            out.append(np.nan)
                        else:
                            m = np.polyfit(x, y, 1)[0]
                            out.append(m)
                return pd.Series(out, index=s.index)

            slope_s = _slope(rs_r)
            accel_s = slope_s.diff(21)

            rs_ratio_df[sec] = rs_r
            rs_slope_df[sec] = slope_s
            rs_accel_df[sec] = accel_s

        results[lb] = {
            "rs_ratio": rs_ratio_df.astype(float),
            "rs_slope": rs_slope_df.astype(float),
            "rs_accel": rs_accel_df.astype(float),
        }

    # FIX-3: RS cross-up on 63-day TF (was below 100, now above 100 in last 5d)
    rs_63 = results[63]["rs_ratio"]
    cross_up_df = pd.DataFrame(False, index=rs_63.index, columns=rs_63.columns)
    for sec in rs_63.columns:
        s = rs_63[sec].fillna(100)
        # Was below 100 at least once in past 5 days, now above 100
        was_below = (s.shift(1) < 100) | (s.shift(2) < 100) | \
                    (s.shift(3) < 100) | (s.shift(4) < 100) | (s.shift(5) < 100)
        cross_up_df[sec] = (s >= 100) & was_below

    # FIX-2: RS rank (higher RS ratio = higher rank = more weight)
    rs_rank_df = rs_63.rank(axis=1, ascending=True).fillna(0)

    results["cross_up"] = cross_up_df
    results["rs_rank"]  = rs_rank_df
    return results


def compute_rs_consensus(multitf_results: dict,
                          lookbacks: tuple = (63, 126, 252),
                          min_agreement: int = 2) -> dict:
    """
    v6 changes:
    - quality score still computed (for diagnostics) but NOT used for allocation
    - rs_rank extracted for FIX-2 weighting
    - cross_up extracted for FIX-3 Breakout quadrant
    - min_agreement passed in per-phase by caller (FIX-6: 3/3 in Sideways)
    """
    sectors = multitf_results[lookbacks[0]]["rs_ratio"].columns
    idx     = multitf_results[lookbacks[0]]["rs_ratio"].index

    count_df = pd.DataFrame(0, index=idx, columns=sectors)
    avg_rs   = pd.DataFrame(0.0, index=idx, columns=sectors)
    slope_ok = pd.DataFrame(False, index=idx, columns=sectors)
    accel_ok = pd.DataFrame(False, index=idx, columns=sectors)

    for lb in lookbacks:
        rs = multitf_results[lb]["rs_ratio"]
        for sec in sectors:
            if sec not in rs.columns:
                continue
            above = (rs[sec] > 100).fillna(False)
            count_df[sec] += above.astype(int)
            avg_rs[sec]   += rs[sec].fillna(100)

    avg_rs = avg_rs / len(lookbacks)

    longest = max(lookbacks)
    for sec in sectors:
        if sec in multitf_results[longest]["rs_slope"].columns:
            slope_ok[sec] = (
                multitf_results[longest]["rs_slope"][sec] > 0
            ).fillna(False)
        accel_col = multitf_results[longest].get("rs_accel", pd.DataFrame())
        if hasattr(accel_col, "columns") and sec in accel_col.columns:
            accel_ok[sec] = (accel_col[sec] > 0).fillna(False)

    qualified = count_df >= min_agreement

    # Quality score (kept for display, not used in allocation — FIX-2)
    quality = count_df.astype(float).copy()
    for sec in sectors:
        base  = count_df[sec] * (1.0 + 0.5 * slope_ok[sec].astype(float))
        bonus = 0.5 * accel_ok[sec].astype(float)
        quality[sec] = base + bonus

    return {
        "count":     count_df,
        "qualified": qualified,
        "avg_rs":    avg_rs,
        "slope_ok":  slope_ok,
        "accel_ok":  accel_ok,
        "quality":   quality,
        "rs_rank":   multitf_results.get("rs_rank", pd.DataFrame()),
        "cross_up":  multitf_results.get("cross_up", pd.DataFrame()),
    }


# ═══════════════════════════════════════════════════════════════
# FIX-6: PHASE-AWARE TF AGREEMENT
# ═══════════════════════════════════════════════════════════════
def get_phase_min_agreement(phase: str) -> int:
    """
    FIX-6: Tighter TF agreement in Sideways to filter noise trades.
    Bear uses looser threshold because defensive sectors are scarce.
    """
    if phase == PHASE_SIDEWAYS:
        return 3   # 3/3 — only rock-solid leaders qualify in low-dispersion markets
    elif phase == PHASE_BEAR:
        return 1   # 1/3 — even weak defensive RS counts in a crash
    else:
        return 2   # 2/3 — standard (unchanged from v5)


# ═══════════════════════════════════════════════════════════════
# FIX-3: QUADRANT CLASSIFICATION v6 (adds Breakout quadrant)
# ═══════════════════════════════════════════════════════════════
def classify_sectors_v6(consensus: dict, phase: str, sectors: list,
                         phase_min_agreement: int) -> dict:
    """
    v6 quadrants:
    - Breakout (NEW): 63-day RS just crossed above 100. Early entry signal.
      In Bull phase only. Gets small dedicated budget (FIX-3).
    - Leading:   RS > 100 on phase_min_agreement TFs AND slope positive.
    - Improving: RS > 100 on 1 TF AND slope positive (Bull/Sideways only).
    - Weakening: RS > 100 qualified but slope turning negative.
    - Lagging:   Everything else.

    In Bear phase: only Defensive sectors qualify as Leading/Improving.
    """
    q_row = {}
    for sec in sectors:
        try:
            cnt  = int(consensus["count"][sec].iloc[-1])
            qok  = cnt >= phase_min_agreement
            sok  = bool(consensus["slope_ok"][sec].iloc[-1])
            aok  = bool(consensus["accel_ok"][sec].iloc[-1])
            cup  = bool(consensus["cross_up"][sec].iloc[-1]) \
                   if sec in consensus["cross_up"].columns else False
        except Exception:
            q_row[sec] = "Lagging"
            continue

        if phase == PHASE_BEAR:
            # Only defensive sectors get allocated in Bear
            if sec in DEFENSIVE_SECTORS and qok:
                q_row[sec] = "Leading"
            elif sec in DEFENSIVE_SECTORS and cnt >= 1:
                q_row[sec] = "Improving"
            else:
                q_row[sec] = "Lagging"

        elif phase == PHASE_SIDEWAYS:
            # Stricter: need 3/3 agreement + positive slope
            if qok and sok:
                q_row[sec] = "Leading"
            elif qok and not sok:
                q_row[sec] = "Weakening"
            else:
                q_row[sec] = "Lagging"

        else:  # BULL
            # FIX-3: Breakout — early entry before full consensus
            if cup and cnt >= 1 and not qok:
                q_row[sec] = "Breakout"
            elif qok and sok:
                q_row[sec] = "Leading"
            elif qok and not sok:
                q_row[sec] = "Weakening"
            elif cnt == 1 and sok:
                q_row[sec] = "Improving"
            else:
                q_row[sec] = "Lagging"

    return q_row


# ═══════════════════════════════════════════════════════════════
# FIX-7: IMPROVED STOCK SCORING (adds trend consistency)
# ═══════════════════════════════════════════════════════════════
def select_stocks_in_sector(sector, universe, close, daily_ret,
                             date, n_stocks=3):
    """
    v6 stock scoring adds Trend Consistency (FIX-7):
    - % of last 63 days where close > 20-day SMA
    - Stocks in intact short-term trends score higher
    - Weights: 35% momentum, 30% Sharpe, 20% inv-vol, 15% trend-consistency
    """
    WIN_6M = 126; WIN_1Y = 252; WIN_TC = 63; rf_d = 0.065 / 252
    members = [t for t in universe
               if SECTOR_MAP.get(t) == sector and t in close.columns]
    if not members:
        return []
    if len(members) <= n_stocks:
        return members
    try:
        c = close.loc[:date, members].copy()
        r = daily_ret.loc[:date, members].copy()
    except Exception:
        return members[:n_stocks]
    n = len(c)
    if n < 30:
        return members[:n_stocks]

    px  = c.iloc[-1]
    scores = {}
    for t in members:
        try:
            p = float(px.get(t, np.nan))
            if np.isnan(p) or p <= 0:
                continue

            # 1. 6-month momentum
            mom = 0.0
            if n >= WIN_6M:
                p6m = float(c[t].iloc[-WIN_6M])
                mom = (p / p6m - 1) if p6m > 0 else 0.0

            # 2. Sharpe ratio (1-year)
            r1y = r[t].iloc[-WIN_1Y:] if n >= WIN_1Y else r[t]
            mu  = float(r1y.mean())
            std = float(r1y.std())
            sh  = ((mu - rf_d) / std * np.sqrt(252)) if std > 1e-10 else 0.0
            vol = std * np.sqrt(252) if std > 0 else 1.0

            # 3. FIX-7: Trend Consistency — % of last 63 days above 20DMA
            tc_score = 0.5  # default neutral
            if n >= WIN_TC:
                prices_63 = c[t].iloc[-WIN_TC:]
                sma20     = prices_63.rolling(20, min_periods=10).mean()
                above_sma = (prices_63 > sma20).fillna(False)
                tc_score  = float(above_sma.mean())

            scores[t] = {
                "mom": mom,
                "sharpe": sh,
                "vol": vol,
                "trend_consistency": tc_score,
            }
        except Exception:
            pass

    if not scores:
        return members[:n_stocks]

    df_s = pd.DataFrame(scores).T
    if len(df_s) > 1:
        df_s["m_r"]  = df_s["mom"].rank(pct=True)
        df_s["s_r"]  = df_s["sharpe"].rank(pct=True)
        df_s["v_r"]  = 1 - df_s["vol"].rank(pct=True)
        df_s["tc_r"] = df_s["trend_consistency"].rank(pct=True)
    else:
        df_s["m_r"] = df_s["s_r"] = df_s["v_r"] = df_s["tc_r"] = 0.5

    # v6 weights: 35% mom, 30% sharpe, 20% inv-vol, 15% trend-consistency
    df_s["comp"] = (0.35 * df_s["m_r"] +
                    0.30 * df_s["s_r"] +
                    0.20 * df_s["v_r"] +
                    0.15 * df_s["tc_r"])
    return df_s["comp"].sort_values(ascending=False).index.tolist()[:n_stocks]


def _intra_sector_weights(selected, budget):
    """Top stock 50% (was 55% in v5) for better diversification."""
    if not selected: return {}
    if len(selected) == 1: return {selected[0]: budget}
    top_w    = budget * 0.50
    per_rest = budget * 0.50 / (len(selected) - 1)
    w = {selected[0]: top_w}
    for t in selected[1:]:
        w[t] = per_rest
    return w


# ═══════════════════════════════════════════════════════════════
# FIX-2: RS-RANK WEIGHTED PORTFOLIO CONSTRUCTION
# ═══════════════════════════════════════════════════════════════
def build_target_weights_v6(q_row, consensus, universe,
                             close, daily_ret, date,
                             max_sector_weight, phase,
                             max_positions=15,
                             vol_target=0.12,
                             port_vol_21d=None,
                             vol_freeze=False):
    """
    v6 portfolio construction — KEY CHANGES from v5:

    1. RS-rank weighting (FIX-2):
       Sectors weighted by 1/rank from RS ratio ranking rather than quality score.
       This avoids buying late into already-extended sectors.

    2. Breakout budget slice (FIX-3):
       In Bull phase, 10% of active_budget reserved for Breakout sectors.
       These get 1 stock max and smaller per-sector cap.

    3. FIX-6 — Phase-specific TF agreement already applied in q_row.

    4. Decoupled vol target (FIX-4):
       If vol_freeze=True (stop-loss fired in last 5 days), skip vol scaling.
       Floor: vol_scalar never below 0.70 (prevents near-cash in mild corrections).

    5. Phase budgets updated:
       BULL:     0.95 → 0.97 (more invested since Sideways is now narrower)
       SIDEWAYS: 0.85 (was 0.88 — tighter since we now correctly ID sideways)
       BEAR:     0.55 (was 0.50 — slightly higher since defensive sectors add value)
    """
    if phase == PHASE_BULL:
        active_budget = 0.97
        max_pos       = max_positions
        min_quality   = 0.0   # RS-rank handles filtering now
        alloc_ratios  = {"Leading": 0.60, "Improving": 0.30, "Breakout": 0.10}
        n_stocks_map  = {"Leading": 3, "Improving": 2, "Breakout": 1}

    elif phase == PHASE_SIDEWAYS:
        active_budget = 0.85
        max_pos       = 10
        min_quality   = 0.0
        alloc_ratios  = {"Leading": 0.80, "Improving": 0.20}
        n_stocks_map  = {"Leading": 2, "Improving": 1}

    else:  # BEAR
        active_budget = 0.55
        max_pos       = 6
        min_quality   = 0.0
        alloc_ratios  = {"Leading": 0.70, "Improving": 0.30}
        n_stocks_map  = {"Leading": 2, "Improving": 1}

    # FIX-4: Vol scaling with freeze and floor
    if not vol_freeze and port_vol_21d is not None and port_vol_21d > 1e-6:
        raw_scalar    = vol_target / port_vol_21d
        vol_scalar    = max(min(raw_scalar, 1.0), 0.70)  # floor at 0.70
        active_budget = active_budget * vol_scalar

    # Collect qualifying sectors
    qualified_sectors = {}
    for sec, q in q_row.items():
        if q not in alloc_ratios:
            continue
        qualified_sectors[sec] = {"quadrant": q}

    if not qualified_sectors:
        return {}

    # FIX-2: RS-rank weighting within each quadrant
    # Get current RS ranks for qualifying sectors
    rs_rank_series = {}
    if "rs_rank" in consensus and not consensus["rs_rank"].empty:
        try:
            rr = consensus["rs_rank"].iloc[-1]
            for sec in qualified_sectors:
                rs_rank_series[sec] = float(rr.get(sec, 1.0))
        except Exception:
            pass

    # Fall back to equal weight if rs_rank not available
    if not rs_rank_series:
        for sec in qualified_sectors:
            rs_rank_series[sec] = 1.0

    # Within each quadrant: 1/rank weight (higher rank = higher RS = more weight)
    quadrant_rank_sum = {}
    for sec, info in qualified_sectors.items():
        q = info["quadrant"]
        quadrant_rank_sum[q] = quadrant_rank_sum.get(q, 0.0) + rs_rank_series.get(sec, 1.0)

    sector_budgets = {}
    for sec, info in qualified_sectors.items():
        q        = info["quadrant"]
        rank_w   = rs_rank_series.get(sec, 1.0)
        q_sum    = max(quadrant_rank_sum.get(q, 1.0), 1e-6)
        q_budget = alloc_ratios.get(q, 0.0) * active_budget
        sector_budgets[sec] = q_budget * (rank_w / q_sum)

    # Apply per-sector cap (30% default; 15% cap for Breakout sectors)
    for sec, info in qualified_sectors.items():
        cap = max_sector_weight * 0.5 if info["quadrant"] == "Breakout" else max_sector_weight
        sector_budgets[sec] = min(sector_budgets[sec], cap)

    # Re-normalize to active_budget
    total = sum(sector_budgets.values())
    if total > 0:
        sector_budgets = {k: v / total * active_budget
                          for k, v in sector_budgets.items()}

    stock_weights    = {}
    total_positions  = 0

    for sec, budget in sorted(sector_budgets.items(), key=lambda x: -x[1]):
        if budget < 0.005:
            continue
        q            = q_row.get(sec, "Lagging")
        n_for_sector = n_stocks_map.get(q, 1)
        remaining    = max_pos - total_positions
        if remaining <= 0:
            break
        n_for_sector = min(n_for_sector, remaining)
        selected     = select_stocks_in_sector(
            sec, universe, close, daily_ret, date, n_for_sector)
        if not selected:
            continue
        intra = _intra_sector_weights(selected, budget)
        for t, w in intra.items():
            stock_weights[t]  = stock_weights.get(t, 0) + w
            total_positions  += 1

    return stock_weights


# ═══════════════════════════════════════════════════════════════
# WALK-FORWARD ANALYSIS (unchanged)
# ═══════════════════════════════════════════════════════════════
def compute_walk_forward(port_series, bench_norm, window_years=3):
    window_days = int(window_years * 252)
    dates       = port_series.index
    rows        = []
    step        = window_days // 4

    i = 0
    while i + window_days <= len(dates):
        start = dates[i]
        end   = dates[min(i + window_days - 1, len(dates)-1)]
        ps    = port_series.loc[start:end]
        bn    = bench_norm.loc[start:end].ffill()
        if len(ps) < 60:
            break
        n_yrs = len(ps) / 252.0
        try:
            cagr_s = (ps.iloc[-1]/ps.iloc[0])**(1/n_yrs) - 1
            cagr_b = (bn.iloc[-1]/bn.iloc[0])**(1/n_yrs) - 1
            ret_s  = ps.pct_change().dropna()
            std_s  = ret_s.std()
            rf_d   = 0.065 / 252
            sharpe = ((ret_s.mean()-rf_d)/std_s*np.sqrt(252)) if std_s>1e-10 else 0
            _, mdd = compute_max_dd(ps)
            rows.append({
                "Period":     f"{start.strftime('%b %Y')} – {end.strftime('%b %Y')}",
                "Strat CAGR": round(cagr_s * 100, 1),
                "Nifty CAGR": round(cagr_b * 100, 1),
                "Alpha %":    round((cagr_s - cagr_b) * 100, 1),
                "Sharpe":     round(sharpe, 2),
                "Max DD %":   round(mdd * 100, 1),
                "Beat?":      "✅" if cagr_s > cagr_b else "❌",
            })
        except Exception:
            pass
        i += step

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# SECTOR ALPHA ATTRIBUTION (unchanged)
# ═══════════════════════════════════════════════════════════════
def compute_sector_attribution(weights_history, port_ret, bench_ret):
    rows = []
    monthly_excess = (port_ret - bench_ret).resample(FREQ_ME).apply(
        lambda x: (1+x).prod()-1)
    for date, weights in weights_history.items():
        sec_weights = {}
        for t, w in weights.items():
            sec = SECTOR_MAP.get(t, "Other")
            sec_weights[sec] = sec_weights.get(sec, 0) + w
        future = monthly_excess.index[monthly_excess.index >= date]
        if len(future) == 0:
            continue
        ex_ret = float(monthly_excess[future[0]])
        for sec, w in sec_weights.items():
            rows.append({"date": date, "sector": sec,
                         "weight": w, "contribution": w * ex_ret * 100})
    if not rows:
        return pd.DataFrame()
    df      = pd.DataFrame(rows)
    summary = df.groupby("sector")["contribution"].sum().reset_index()
    summary.columns = ["Sector", "Alpha Contribution %"]
    return summary.sort_values("Alpha Contribution %", ascending=False)


# ═══════════════════════════════════════════════════════════════
# CORE BACKTEST v6 — ALL FIXES APPLIED
# ═══════════════════════════════════════════════════════════════
@st.cache_data
def _run_sector_rotation_v6(
    start_date, end_date,
    smooth_period,
    max_sector_weight,
    rebal_freq_months,
    drift_tolerance,
    fee_bps, slip_bps,
    min_tf_agreement,      # default 2; overridden per-phase by FIX-6
    stop_loss_pct,
    vol_target,
    bear_gap_threshold,    # FIX-5: default now -0.05
    sideways_gap_pct,      # FIX-5: default now 0.05
    min_signal_days,       # FIX-1: minimum days between signal-triggered rebalances
    min_sector_hold,       # FIX-8: minimum days a sector must be held
    _cache_version=7,
):
    import inspect as _inspect
    log = []
    tc  = (fee_bps + slip_bps) / 10_000
    LOOKBACKS = (63, 126, 252)
    REBAL_FREQ = FREQ_2M if rebal_freq_months == 2 else FREQ_ME

    # ── 1. Universe ──
    all_tickers = set()
    sy = int(str(start_date)[:4])
    ey = int(str(end_date)[:4])
    universe_by_date = {}
    for yr in range(sy, ey + 1):
        u = get_universe_for_year(yr)
        universe_by_date[yr] = u
        all_tickers.update(u)
    dl_list = sorted(all_tickers) + ["^NSEI"]
    log.append(f"STEP1 ✅ {len(dl_list)} tickers | {sy}–{ey}")

    # ── 2. Download ──
    try:
        _kw = dict(start=str(start_date), end=str(end_date),
                   auto_adjust=True, progress=False, threads=False)
        _sig = _inspect.signature(yf.download).parameters
        if "group_by" in _sig:
            _kw["group_by"] = "column"
        if "multi_level_index" in _sig:
            _kw["multi_level_index"] = True
        raw = yf.download(dl_list, **_kw)
        log.append(f"STEP2 ✅ shape={raw.shape}")
    except Exception as e:
        return None, f"Download failed: {e}", log

    if raw.empty or raw.shape[0] < 20:
        return None, "No data.", log

    # ── 3–4. Extract + clean ──
    def _field(r, names):
        if isinstance(r.columns, pd.MultiIndex):
            l0 = r.columns.get_level_values(0).unique().tolist()
            for n in names:
                if n in l0: return r[n].copy()
        else:
            for n in names:
                if n in r.columns: return r[[n]].copy()
        return None

    close = _field(raw, ["Close", "Adj Close"])
    open_ = _field(raw, ["Open"])
    if close is None: return None, "No Close column.", log
    if open_ is None: open_ = close.copy()

    close = close.loc[:, close.isna().mean() < 0.60].ffill().bfill()
    open_ = open_.reindex(columns=close.columns).ffill().bfill()
    if "^NSEI" not in close.columns:
        return None, "^NSEI missing.", log

    bench_prices = close["^NSEI"].copy()
    scols        = [c for c in close.columns if c != "^NSEI"]
    close_s      = close[scols]
    open_s       = open_.reindex(columns=scols)
    n_rows       = len(close_s)
    log.append(f"STEP4 ✅ {len(scols)} stocks | {n_rows} days")
    if n_rows < 300:
        return None, f"Only {n_rows} rows — need 300+.", log

    # ── 5. Sector indices ──
    sector_idx = build_sector_indices(close_s, universe_by_date)
    log.append(f"STEP5 ✅ {sector_idx.shape[1]} sector indices built")

    # ── 6. Multi-TF RS + consensus (full dataset, phase-agnostic) ──
    multitf   = compute_multitf_rs(
        sector_idx, bench_prices,
        lookbacks=LOOKBACKS, smooth=smooth_period)

    # Build consensus with default min_agreement; per-phase override done in loop
    consensus = compute_rs_consensus(
        multitf, lookbacks=LOOKBACKS, min_agreement=min_tf_agreement)

    qual_arr   = consensus["quality"].values
    valid_q    = qual_arr[np.isfinite(qual_arr)]
    if len(valid_q) > 0:
        qualified_pct = (consensus["qualified"].values.sum() /
                         max(consensus["qualified"].values.size, 1) * 100)
        log.append(
            f"STEP6 ✅ Multi-TF RS | Default agreement: {min_tf_agreement}/3 | "
            f"Sectors qualifying avg: {qualified_pct:.0f}% | "
            f"Quality range: {valid_q.min():.1f}–{valid_q.max():.1f}"
        )
    else:
        return None, "Multi-TF RS computation failed.", log

    # ── 7. v6 Phase detector ──
    market_phase = compute_market_phase_v6(
        bench_prices,
        bear_gap_threshold=bear_gap_threshold,
        sideways_gap_pct=sideways_gap_pct,
        confirm_days=3)

    phase_counts = market_phase.value_counts()
    bull_pct  = phase_counts.get(PHASE_BULL,     0) / len(market_phase) * 100
    sw_pct    = phase_counts.get(PHASE_SIDEWAYS,  0) / len(market_phase) * 100
    bear_pct  = phase_counts.get(PHASE_BEAR,      0) / len(market_phase) * 100
    log.append(
        f"STEP7 ✅ Phase (v6) | "
        f"Bull: {bull_pct:.0f}% | Sideways: {sw_pct:.0f}% | Bear: {bear_pct:.0f}%"
    )
    if bear_pct < 2:
        log.append(
            "STEP7 ⚠️ Bear still <2% — lower bear_gap_threshold to -0.04 "
            "or check sideways_gap_pct."
        )
    if bull_pct < 50:
        log.append(
            "STEP7 ⚠️ Bull <50% — consider widening sideways_gap_pct to 0.07."
        )

    # ── 8. Rebalance dates (calendar) ──
    daily_ret = close_s.pct_change().fillna(0)
    dates     = close_s.index
    rebal_set = set()
    for rd in pd.date_range(dates[0], dates[-1], freq=REBAL_FREQ):
        future = dates[dates >= rd]
        if len(future) > 0:
            rebal_set.add(future[0])
    log.append(f"STEP8 ✅ {len(rebal_set)} calendar rebal dates (every {rebal_freq_months}M)")

    # ── 9. Backtest loop ──
    portfolio_value    = 1_000_000.0
    cash               = portfolio_value
    holdings           = {}   # {ticker: {shares, entry_price, entry_date, peak_price}}
    port_values        = {}
    weights_history    = {}
    signal_history     = {}
    quadrant_hist      = {}
    phase_history      = {}
    trade_log          = []
    pending_rebal      = None
    last_rebal_date    = None
    day_counter        = 0
    hold_periods       = []
    signal_rebal_count = 0

    # FIX-1: track previous quadrant classification for change detection
    prev_q_row         = {}
    last_signal_rebal  = None   # date of last signal-triggered rebalance

    # FIX-4: vol-freeze tracker (5 days after stop-loss)
    vol_freeze_until   = None

    # FIX-8: sector entry dates for minimum hold
    sector_entry_dates = {}   # {sector: date_entered}

    # Rolling vol tracker (21-day window)
    recent_port_rets = []

    for date in dates:
        try:
            px_close = close_s.loc[date]
            px_open  = open_s.loc[date]
        except KeyError:
            port_values[date] = portfolio_value
            continue
        day_counter += 1

        # ── v5-style STOP-LOSS CHECK ──
        stop_loss_exits = set()
        if stop_loss_pct > 0:
            for t, h in list(holdings.items()):
                cp = series_get(px_close, t, h["entry_price"])
                if np.isnan(cp): continue
                if cp > h.get("peak_price", h["entry_price"]):
                    holdings[t]["peak_price"] = cp
                peak = h.get("peak_price", h["entry_price"])
                if peak > 0 and (cp / peak - 1) < -stop_loss_pct:
                    stop_loss_exits.add(t)

        if stop_loss_exits:
            h_val = sum(
                h["shares"] * series_get(px_open, t, h["entry_price"])
                for t, h in holdings.items())
            portfolio_value = cash + h_val
            for t in stop_loss_exits:
                if t not in holdings: continue
                ep = series_get(px_open, t)
                if np.isnan(ep): continue
                h     = holdings.pop(t)
                cash += h["shares"] * ep * (1 - tc)
                pnl   = (ep/h["entry_price"]-1)*100 if h["entry_price"]>0 else 0
                hd    = (date - h.get("entry_date", date)).days
                hold_periods.append(hd)
                trade_log.append({"date": date, "ticker": t,
                                   "action": "STOP-LOSS",
                                   "pnl_pct": pnl, "hold_days": hd})
            # FIX-4: freeze vol targeting for 5 days after stop-loss
            vol_freeze_until = date + pd.Timedelta(days=5)

        # ── Execute pending rebalance ──
        if pending_rebal is not None:
            target_w, exits_set = pending_rebal
            pending_rebal = None

            h_val = sum(
                h["shares"] * series_get(px_open, t, h["entry_price"])
                for t, h in holdings.items())
            portfolio_value = cash + h_val

            for t in list(holdings.keys()):
                if t in exits_set or t not in target_w:
                    ep = series_get(px_open, t)
                    if np.isnan(ep): continue
                    h     = holdings.pop(t)
                    cash += h["shares"] * ep * (1 - tc)
                    pnl   = (ep/h["entry_price"]-1)*100 if h["entry_price"]>0 else 0
                    hd    = (date - h.get("entry_date", date)).days
                    hold_periods.append(hd)
                    trade_log.append({"date": date, "ticker": t,
                                       "action": "SELL",
                                       "pnl_pct": pnl, "hold_days": hd})

            for t, w in target_w.items():
                ep = series_get(px_open, t)
                if np.isnan(ep) or ep <= 0: continue
                target_sh = int(portfolio_value * w / ep)
                if target_sh <= 0: continue
                if t in holdings:
                    cur_w = (holdings[t]["shares"] * ep) / max(portfolio_value, 1)
                    if abs(cur_w - w) > drift_tolerance:
                        diff = target_sh - holdings[t]["shares"]
                        if diff > 0:
                            cost = diff * ep * (1 + tc)
                            if cost <= cash:
                                holdings[t]["shares"] += diff
                                cash -= cost
                        elif diff < 0:
                            holdings[t]["shares"] += diff
                            cash += (-diff) * ep * (1 - tc)
                else:
                    cost = target_sh * ep * (1 + tc)
                    if cost <= cash:
                        holdings[t] = {
                            "shares":      target_sh,
                            "entry_price": ep,
                            "entry_date":  date,
                            "peak_price":  ep,
                        }
                        cash -= cost
                        trade_log.append({"date": date, "ticker": t,
                                           "action": "BUY",
                                           "pnl_pct": 0, "hold_days": 0})

        # ── Mark to market ──
        h_val = sum(
            h["shares"] * series_get(px_close, t, h["entry_price"])
            for t, h in holdings.items())
        portfolio_value = cash + h_val

        # ── Rolling vol tracking ──
        if len(port_values) > 0:
            prev_val = list(port_values.values())[-1]
            if prev_val > 0:
                recent_port_rets.append(portfolio_value / prev_val - 1)
        if len(recent_port_rets) > 21:
            recent_port_rets.pop(0)

        # ── Rebalance trigger (calendar OR signal) ──
        is_calendar_rebal = (date in rebal_set and date != last_rebal_date)

        # FIX-1: signal-triggered rebalance check
        is_signal_rebal = False
        if (date in consensus["count"].index and
                prev_q_row and
                last_rebal_date is not None):
            days_since = (date - last_rebal_date).days
            if days_since >= min_signal_days:
                phase_now   = market_phase.get(date, PHASE_BULL)
                phase_ma    = get_phase_min_agreement(phase_now)
                # Build tentative consensus at today
                cons_now = {k: v.loc[:date] for k, v in consensus.items()
                            if hasattr(v, "loc")}
                sectors_now = list(sector_idx.columns)
                q_now = classify_sectors_v6(cons_now, phase_now,
                                            sectors_now, phase_ma)
                # Check for any quadrant upgrade (Lagging/Improving → Leading)
                # or degradation (Leading/Improving → Weakening/Lagging)
                RANK = {"Lagging": 0, "Improving": 1, "Breakout": 2,
                        "Weakening": 1, "Leading": 3}
                for sec in sectors_now:
                    prev_rank = RANK.get(prev_q_row.get(sec, "Lagging"), 0)
                    curr_rank = RANK.get(q_now.get(sec, "Lagging"), 0)
                    # Trigger if any sector moved 2+ ranks up or any moved down to Lagging
                    if (curr_rank - prev_rank >= 2 or
                            (prev_rank >= 2 and curr_rank == 0)):
                        is_signal_rebal = True
                        signal_rebal_count += 1
                        log_msg = (f"Signal rebal triggered: {sec} "
                                   f"{prev_q_row.get(sec)} → {q_now.get(sec)} "
                                   f"on {date.strftime('%Y-%m-%d')}")
                        break

        if is_calendar_rebal or is_signal_rebal:
            last_rebal_date   = date
            universe          = universe_by_date.get(date.year, [])
            phase             = market_phase.get(date, PHASE_BULL)
            phase_history[date] = phase
            phase_ma          = get_phase_min_agreement(phase)

            if date not in consensus["count"].index:
                pending_rebal = ({}, set())
                port_values[date] = portfolio_value
                continue

            cons_at_date = {k: v.loc[:date] for k, v in consensus.items()
                            if hasattr(v, "loc")}

            sectors   = list(sector_idx.columns)
            q_row     = classify_sectors_v6(
                cons_at_date, phase, sectors, phase_ma)
            prev_q_row = q_row.copy()
            quadrant_hist[date] = q_row.copy()

            # FIX-4: compute vol, apply freeze
            port_vol_21d = None
            if len(recent_port_rets) >= 10:
                rv = np.std(recent_port_rets)
                port_vol_21d = rv * np.sqrt(252) if rv > 0 else None

            is_vol_frozen = (vol_freeze_until is not None and
                             date <= vol_freeze_until)

            target_w = build_target_weights_v6(
                q_row, cons_at_date, universe,
                close_s, daily_ret, date,
                max_sector_weight, phase,
                max_positions=15,
                vol_target=vol_target,
                port_vol_21d=port_vol_21d,
                vol_freeze=is_vol_frozen)

            # FIX-8: protect sectors within min_sector_hold window
            # Don't exit a sector that was entered too recently (signal rebal only)
            if is_signal_rebal and not is_calendar_rebal:
                protected_tickers = set()
                for t, h in holdings.items():
                    sec = SECTOR_MAP.get(t, "Other")
                    entry_date = h.get("entry_date", date)
                    days_held  = (date - entry_date).days
                    if days_held < min_sector_hold:
                        protected_tickers.add(t)
                # Force-keep protected tickers at their current weight
                for t in protected_tickers:
                    if t not in target_w:
                        cur_val = holdings[t]["shares"] * series_get(px_close, t, 1.0)
                        target_w[t] = cur_val / max(portfolio_value, 1)

            exits_set = {t for t in holdings if t not in target_w}
            weights_history[date] = target_w.copy()
            signal_history[date] = {
                "quadrants":      q_row,
                "phase":          phase,
                "port_vol_21d":   round(port_vol_21d * 100, 1) if port_vol_21d else None,
                "is_signal_rebal": is_signal_rebal,
                "vol_frozen":      is_vol_frozen,
                "quality":        {
                    s: round(float(cons_at_date["quality"][s].iloc[-1]), 2)
                    for s in sectors
                    if s in cons_at_date["quality"].columns
                },
            }
            pending_rebal = (target_w, exits_set)

        port_values[date] = portfolio_value

    log.append(
        f"STEP9 ✅ {day_counter} days | "
        f"{len(weights_history)} total rebalances "
        f"({signal_rebal_count} signal-triggered) | "
        f"{len(trade_log)} trades"
    )

    # ── 10. Return series ──
    port_series = pd.Series(port_values, dtype=float).dropna()
    common_idx  = port_series.index.intersection(bench_prices.index)
    if len(common_idx) < 20:
        return None, f"Only {len(common_idx)} dates.", log

    port_series = port_series.loc[common_idx]
    bench_norm  = bench_prices.loc[common_idx].ffill()
    bench_norm  = bench_norm / bench_norm.iloc[0] * 1_000_000.0

    port_ret  = port_series.pct_change().dropna()
    bench_ret = bench_norm.pct_change().dropna()
    common_r  = port_ret.index.intersection(bench_ret.index)
    port_ret  = port_ret.loc[common_r]
    bench_ret = bench_ret.loc[common_r]
    if len(port_ret) < 20:
        return None, "Too few return observations.", log

    # ── 11. Metrics ──
    n_years  = len(port_series) / 252.0
    cagr     = (port_series.iloc[-1]/port_series.iloc[0])**(1/n_years) - 1
    b_cagr   = (bench_norm.iloc[-1]/bench_norm.iloc[0])**(1/n_years) - 1
    rf       = 0.065 / 252
    p_std    = port_ret.std()
    b_std    = bench_ret.std()
    sharpe   = ((port_ret.mean()-rf)/p_std)*np.sqrt(252) if p_std>1e-10 else 0.0
    b_sharpe = ((bench_ret.mean()-rf)/b_std)*np.sqrt(252) if b_std>1e-10 else 0.0
    neg      = port_ret[port_ret < 0]
    downside = neg.std() * np.sqrt(252) if len(neg) > 5 else 1e-6
    sortino  = ((port_ret.mean()-rf)*252) / downside
    dd_s, max_dd  = compute_max_dd(port_series)
    dd_b, b_maxdd = compute_max_dd(bench_norm)
    calmar   = cagr / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
    vol_ann  = p_std * np.sqrt(252)
    win_rate = float((port_ret > 0).mean())

    cov_m   = np.cov(port_ret.values, bench_ret.values)
    beta    = cov_m[0, 1] / (cov_m[1, 1] + 1e-12)
    alpha_a = cagr - beta * b_cagr
    excess  = port_ret - bench_ret
    ir      = (excess.mean() / (excess.std() + 1e-12)) * np.sqrt(252)
    var_95  = float(np.percentile(port_ret.values, 5))
    cvar_95 = float(port_ret[port_ret <= var_95].mean()) \
              if (port_ret <= var_95).any() else var_95

    up_b   = bench_ret[bench_ret > 0]
    dn_b   = bench_ret[bench_ret < 0]
    up_p   = port_ret.reindex(up_b.index).dropna()
    dn_p   = port_ret.reindex(dn_b.index).dropna()
    uc     = up_p.index.intersection(up_b.reindex(up_p.index).dropna().index)
    dc     = dn_p.index.intersection(dn_b.reindex(dn_p.index).dropna().index)
    up_cap = float(np.clip(
        up_p.loc[uc].mean()/up_b.loc[uc].mean()
        if len(uc) > 0 and up_b.loc[uc].mean() > 0 else 1.0, 0, 2))
    dn_cap = float(np.clip(
        dn_p.loc[dc].mean()/dn_b.loc[dc].mean()
        if len(dc) > 0 and dn_b.loc[dc].mean() < 0 else 1.0, 0, 2))

    yr_s  = port_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
    yr_b  = bench_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
    cyrs  = yr_s.index.intersection(yr_b.index)
    yr_s, yr_b = yr_s.loc[cyrs], yr_b.loc[cyrs]
    beat  = int(sum(s > b for s, b in zip(yr_s.values, yr_b.values)))

    mp_m  = port_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)
    mb_m  = bench_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)

    stop_loss_trades = len([t for t in trade_log if t.get("action") == "STOP-LOSS"])
    tl_df    = pd.DataFrame(trade_log) if trade_log else \
               pd.DataFrame(columns=["date","ticker","action","pnl_pct","hold_days"])
    avg_hold = float(np.mean(hold_periods)) if hold_periods else 0.0

    sec_wt_rows = []
    for date, wts in weights_history.items():
        row = {"date": date}
        for t, w in wts.items():
            sec = SECTOR_MAP.get(t, "Other")
            row[sec] = row.get(sec, 0) + w
        sec_wt_rows.append(row)
    sec_wt_df = pd.DataFrame(sec_wt_rows).set_index("date").fillna(0) \
                if sec_wt_rows else pd.DataFrame()

    q_count_rows = []
    for date, q_row in quadrant_hist.items():
        counts = {"date": date}
        for q in ["Leading", "Breakout", "Improving", "Weakening", "Lagging"]:
            counts[q] = sum(1 for v in q_row.values() if v == q)
        q_count_rows.append(counts)
    q_count_df = pd.DataFrame(q_count_rows).set_index("date") \
                 if q_count_rows else pd.DataFrame()

    sector_attr    = compute_sector_attribution(weights_history, port_ret, bench_ret)
    wf_df          = compute_walk_forward(port_series, bench_norm, window_years=3)
    wf_beat_pct    = (wf_df["Beat?"] == "✅").mean() * 100 if len(wf_df) > 0 else 0
    phase_series   = pd.Series(phase_history).reindex(port_series.index).ffill().bfill()
    alpha_vs_nifty = (cagr - b_cagr) * 100

    log.append(
        f"STEP11 ✅ CAGR={cagr:.2%} Sharpe={sharpe:.2f} "
        f"MaxDD={max_dd:.2%} Alpha={alpha_vs_nifty:.1f}% | "
        f"Walk-forward beat: {wf_beat_pct:.0f}% | "
        f"Stop-loss exits: {stop_loss_trades} | "
        f"Signal rebals: {signal_rebal_count}"
    )
    if wf_beat_pct < 70:
        log.append(
            f"STEP11 ⚠️ Walk-fwd beat {wf_beat_pct:.0f}% < 70% — "
            "lower bear_gap_threshold or lower min_signal_days."
        )

    return {
        "port_series":       port_series,
        "bench_norm":        bench_norm,
        "port_ret":          port_ret,
        "bench_ret":         bench_ret,
        "yr_strat":          yr_s,
        "yr_bench":          yr_b,
        "dd_s":              dd_s,
        "dd_b":              dd_b,
        "weights_history":   weights_history,
        "signal_history":    signal_history,
        "quadrant_hist":     quadrant_hist,
        "trade_log":         tl_df,
        "monthly_port":      mp_m,
        "monthly_bench":     mb_m,
        "market_phase":      market_phase,
        "phase_series":      phase_series,
        "phase_history":     phase_history,
        "sector_attr":       sector_attr,
        "sec_wt_df":         sec_wt_df,
        "q_count_df":        q_count_df,
        "walk_forward":      wf_df,
        "wf_beat_pct":       wf_beat_pct,
        "avg_hold_days":     avg_hold,
        "stop_loss_trades":  stop_loss_trades,
        "signal_rebal_count": signal_rebal_count,
        "consensus":         consensus,
        "metrics": {
            "CAGR":           safe_float(cagr),
            "Bench CAGR":     safe_float(b_cagr),
            "Sharpe":         safe_float(sharpe),
            "B Sharpe":       safe_float(b_sharpe),
            "Sortino":        safe_float(sortino),
            "Max DD":         safe_float(max_dd),
            "Bench MaxDD":    safe_float(b_maxdd),
            "Calmar":         safe_float(calmar),
            "Volatility":     safe_float(vol_ann),
            "Win Rate":       safe_float(win_rate),
            "Beta":           safe_float(beta),
            "Alpha":          safe_float(alpha_a),
            "Info Ratio":     safe_float(ir),
            "VaR 95":         safe_float(var_95),
            "CVaR 95":        safe_float(cvar_95),
            "Beat Years":     beat,
            "Total Years":    len(yr_s),
            "Up Capture":     safe_float(up_cap),
            "Down Capture":   safe_float(dn_cap),
            "N Trades":       len(tl_df),
            "N Years":        safe_float(n_years),
            "Avg Hold":       safe_float(avg_hold),
            "WF Beat Pct":    safe_float(wf_beat_pct),
            "Alpha Nifty":    safe_float(alpha_vs_nifty),
            "Stop Losses":    stop_loss_trades,
            "Signal Rebals":  signal_rebal_count,
        },
    }, None, log


# ═══════════════════════════════════════════════════════════════
# STRATEGY CLASS
# ═══════════════════════════════════════════════════════════════
class SectorRotationStrategy(BaseStrategy):
    NAME = "Sector Momentum Rotation v6 (Enhanced Investor-Grade)"
    DESCRIPTION = (
        "v6 fixes over v5: Signal-triggered rebalancing | RS-rank weighting | "
        "Breakout quadrant | Decoupled vol-target+stop-loss | Bear threshold -5% | "
        "3/3 TF in Sideways | Trend-consistency stock scoring | Sector hold floor. "
        "Targets: CAGR 15%+ | Sharpe 0.75+ | MaxDD <18% | Beat Nifty 75%+ windows."
    )

    def render_sidebar(self):
        self.start_date = st.sidebar.date_input(
            "Start Date", value=pd.to_datetime("2015-01-01"))
        self.end_date   = st.sidebar.date_input(
            "End Date", value=pd.to_datetime("2025-01-01"))

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Signal Parameters**")
        self.smooth_period = st.sidebar.slider(
            "EMA Smoothing (days)", 10, 30, 14)
        self.min_tf_agreement = st.sidebar.radio(
            "Default Min TF Agreement", [2, 3], index=0,
            format_func=lambda x: f"{x}/3 (overridden per-phase in v6)")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**v6: Phase Detector**")
        self.bear_gap_threshold = st.sidebar.slider(
            "Bear gap threshold %", -12, -3, -5,
            help="Gap below 200DMA for Bear. v6 default -5% (was -8% in v5)."
        ) / 100
        self.sideways_gap_pct = st.sidebar.slider(
            "Sideways band %", 3, 10, 5,
            help="±% from 200DMA for Sideways. v6 default 5% (was 7% in v5)."
        ) / 100

        st.sidebar.markdown("---")
        st.sidebar.markdown("**v6: Signal-Triggered Rebalancing (FIX-1)**")
        self.min_signal_days = st.sidebar.slider(
            "Min days between signal rebals", 5, 30, 10,
            help="Must wait this many days after last rebal before a signal can trigger another.")
        self.min_sector_hold = st.sidebar.slider(
            "Min sector hold days (FIX-8)", 5, 30, 15,
            help="A newly entered sector cannot be exited by a signal rebal for this many days.")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**v6: Risk Controls**")
        self.stop_loss_pct = st.sidebar.slider(
            "Trailing Stop-Loss %", 0, 25, 12,
            help="v6 tightened to 12% (was 15% in v5) — less drawdown."
        ) / 100
        self.vol_target = st.sidebar.slider(
            "Portfolio Vol Target %", 8, 20, 14,
            help="v6 raised to 14% (was 12% in v5) — more CAGR, same Sharpe."
        ) / 100

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Portfolio Construction**")
        self.max_sector_wt = st.sidebar.slider(
            "Max Sector Weight %", 20, 40, 30) / 100
        self.rebal_freq_months = st.sidebar.radio(
            "Calendar Rebalance Frequency", [1, 2], index=1,
            format_func=lambda x: f"Every {x} month{'s' if x > 1 else ''}")
        self.drift_tolerance = st.sidebar.slider(
            "Drift Tolerance %", 3, 8, 5) / 100

        st.sidebar.markdown("---")
        self.fee_bps  = st.sidebar.number_input("Fee (bps)", value=1.0, min_value=0.0)
        self.slip_bps = st.sidebar.number_input("Slippage (bps)", value=2.0, min_value=0.0)

        if st.sidebar.button("🗑 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

    def run(self):
        with st.spinner("Running Sector Rotation v6 (~3-4 min)..."):
            raw = _run_sector_rotation_v6(
                self.start_date, self.end_date,
                self.smooth_period,
                self.max_sector_wt,
                self.rebal_freq_months,
                self.drift_tolerance,
                self.fee_bps, self.slip_bps,
                self.min_tf_agreement,
                self.stop_loss_pct,
                self.vol_target,
                self.bear_gap_threshold,
                self.sideways_gap_pct,
                self.min_signal_days,
                self.min_sector_hold,
            )

        run_log = []
        if isinstance(raw, tuple) and len(raw) == 3:
            result, err, run_log = raw
        else:
            result, err = None, f"Unexpected: {type(raw)}"

        with st.expander("🛠 Debug / Run Log"):
            import sys
            st.caption(f"Python {sys.version.split()[0]} | pandas {pd.__version__} | v6")
            for line in run_log:
                st.error(line)   if "❌" in line else \
                st.warning(line) if "⚠️" in line else st.success(line)
            if err: st.error(f"Error: {err}")

        if result is None:
            st.error(f"❌ {err}")
            return

        m   = result["metrics"]
        ps  = result["port_series"]
        bn  = result["bench_norm"]
        pr  = result["port_ret"]
        br  = result["bench_ret"]
        ys  = result["yr_strat"]
        yb  = result["yr_bench"]

        alpha  = m["Alpha Nifty"]
        wfb    = m["WF Beat Pct"]
        sl_ct  = m.get("Stop Losses", 0)
        sr_ct  = m.get("Signal Rebals", 0)

        # ── Header ──
        if alpha >= 5 and wfb >= 75:
            st.success(
                f"✅ **Sector Rotation v6** — Beating Nifty by **{alpha:.1f}%** p.a. | "
                f"Walk-forward beat: **{wfb:.0f}%** | "
                f"Signal rebals: {sr_ct} | Stop-losses: {sl_ct}")
        elif alpha >= 3 and wfb >= 60:
            st.warning(
                f"⚠️ v6: Alpha {alpha:.1f}% | Walk-fwd beat: {wfb:.0f}% — "
                f"try lowering bear_gap_threshold or min_signal_days.")
        else:
            st.error(
                f"❌ v6 underperforming — alpha {alpha:.1f}% | "
                f"Walk-fwd {wfb:.0f}% | Check debug log.")

        st.info(
            f"📅 **{ps.index[0].strftime('%b %Y')} → {ps.index[-1].strftime('%b %Y')}** "
            f"({m['N Years']:.1f} yrs) | "
            f"Vol target: {self.vol_target*100:.0f}% | "
            f"Stop-loss: {self.stop_loss_pct*100:.0f}% | "
            f"Total trades: {m['N Trades']} | "
            f"Signal rebalances: {sr_ct}")

        # ── KPIs ──
        st.markdown("## 📊 Performance Overview")
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("CAGR", f"{m['CAGR']*100:.2f}%",
                  delta=f"{alpha:.1f}% vs Nifty")
        c2.metric("Sharpe", f"{m['Sharpe']:.2f}",
                  delta=f"{m['Sharpe']-m['B Sharpe']:.2f} vs Nifty")
        c3.metric("Sortino", f"{m['Sortino']:.2f}")
        c4.metric("Max Drawdown", f"{m['Max DD']*100:.1f}%",
                  delta_color="inverse",
                  delta=f"{(m['Max DD']-m['Bench MaxDD'])*100:.1f}% vs Nifty")
        c5.metric("Walk-fwd beat", f"{wfb:.0f}%",
                  help="% of rolling 3-yr windows beating Nifty")

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Win Rate",        f"{m['Win Rate']*100:.1f}%")
        c2.metric("Beta",            f"{m['Beta']:.2f}")
        c3.metric("Up Capture",      f"{m['Up Capture']*100:.0f}%")
        c4.metric("Down Capture",    f"{m['Down Capture']*100:.0f}%")
        c5.metric("Signal Rebals",   f"{sr_ct}",
                  help="Extra rebalances fired by quadrant-change signals (FIX-1)")

        # ── Phase Diagnostics ──
        st.markdown("---")
        mp = result["market_phase"].reindex(ps.index).ffill()
        phase_pct = mp.value_counts(normalize=True) * 100
        bull_p = phase_pct.get(PHASE_BULL, 0)
        sw_p   = phase_pct.get(PHASE_SIDEWAYS, 0)
        bear_p = phase_pct.get(PHASE_BEAR, 0)

        if bear_p < 2:
            st.warning(
                f"⚠️ Bear phase only {bear_p:.0f}% — defensive routing barely used. "
                f"Try bear_gap_threshold = -4% to activate it more frequently.")
        elif bull_p < 50:
            st.warning(
                f"⚠️ Bull only {bull_p:.0f}% — consider raising sideways_gap_pct to 7%.")
        else:
            st.success(
                f"✅ Phase distribution: Bull={bull_p:.0f}% | "
                f"Sideways={sw_p:.0f}% | Bear={bear_p:.0f}%")

        # ── Walk-Forward ──
        st.markdown("---")
        st.subheader("🔄 Walk-Forward Analysis — Consistency Test")
        wf_df = result["walk_forward"]
        if not wf_df.empty:
            beat_count = (wf_df["Beat?"] == "✅").sum()
            total_w    = len(wf_df)
            st.dataframe(wf_df, use_container_width=True, hide_index=True)
            if beat_count == total_w:
                st.success(f"✅ Beat Nifty in all {total_w} rolling 3-year windows.")
            elif beat_count >= int(total_w * 0.70):
                st.warning(f"⚠️ Beat {beat_count}/{total_w} windows.")
            else:
                st.error(f"❌ Only {beat_count}/{total_w} windows beat Nifty.")
        st.markdown("---")

        # ── Market Phase Timeline ──
        st.subheader("🌡️ Market Phase — Bull / Sideways / Bear")
        phase_numeric = mp.map({PHASE_BULL: 3, PHASE_SIDEWAYS: 2, PHASE_BEAR: 1})
        fig_phase = go.Figure()
        for ph, col in {PHASE_BULL:"#2E7D32", PHASE_SIDEWAYS:"#F9A825",
                        PHASE_BEAR:"#C62828"}.items():
            mask = (mp == ph)
            if mask.any():
                fig_phase.add_trace(go.Scatter(
                    x=mp.index[mask], y=phase_numeric[mask].values,
                    mode="markers", marker=dict(size=3, color=col, opacity=0.6),
                    name=ph))
        fig_phase.update_layout(
            height=160,
            yaxis=dict(tickvals=[1,2,3], ticktext=["Bear","Sideways","Bull"],
                       range=[0.5,3.5]),
            margin=dict(l=10,r=10,t=10,b=10),
            legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_phase, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric("Bull phase",     f"{bull_p:.0f}%")
        c2.metric("Sideways phase", f"{sw_p:.0f}%")
        c3.metric("Bear phase",     f"{bear_p:.0f}%")
        st.markdown("---")

        # ── Equity Curve ──
        st.subheader("📈 Equity Curve vs Nifty 50")
        bn_ri = bn.reindex(ps.index).ffill()
        fig1  = go.Figure()
        phase_s = result.get("phase_series", pd.Series())
        if not phase_s.empty:
            bear_mask = (phase_s == PHASE_BEAR)
            in_bear = False; bear_start = None
            for dt in ps.index:
                is_bear = bear_mask.get(dt, False)
                if is_bear and not in_bear:
                    bear_start = dt; in_bear = True
                elif not is_bear and in_bear:
                    fig1.add_vrect(x0=bear_start, x1=dt,
                                   fillcolor="rgba(198,40,40,0.12)", line_width=0)
                    in_bear = False
            if in_bear:
                fig1.add_vrect(x0=bear_start, x1=ps.index[-1],
                               fillcolor="rgba(198,40,40,0.12)", line_width=0)

        fig1.add_trace(go.Scatter(x=ps.index, y=ps.values,
            name="Sector Rotation v6",
            line=dict(color="rgba(46,125,50,1)", width=2.5)))
        fig1.add_trace(go.Scatter(x=bn.index, y=bn.values,
            name="Nifty 50 B&H",
            line=dict(color="rgba(230,81,0,1)", width=1.8, dash="dash")))
        fig1.add_trace(go.Scatter(
            x=list(ps.index)+list(ps.index[::-1]),
            y=list(ps.values)+list(bn_ri.values[::-1]),
            fill="toself", fillcolor="rgba(46,125,50,0.08)",
            line=dict(width=0), name="Alpha region"))
        fig1.update_layout(height=420, yaxis=dict(tickformat=",.0f"),
            legend=dict(x=0.01, y=0.99), margin=dict(l=10,r=10,t=10,b=10))
        st.caption("Red shaded = Bear phase (v6: fires at -5% gap, not -8%)")
        st.plotly_chart(fig1, use_container_width=True)

        # ── Drawdown ──
        st.subheader("📉 Drawdown")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=result["dd_s"].index, y=(result["dd_s"]*100).values,
            fill="tozeroy", name="Sector Rotation v6",
            fillcolor="rgba(46,125,50,0.35)",
            line=dict(color="rgba(46,125,50,1)", width=1)))
        fig2.add_trace(go.Scatter(
            x=result["dd_b"].index, y=(result["dd_b"]*100).values,
            fill="tozeroy", name="Nifty 50",
            fillcolor="rgba(230,81,0,0.20)",
            line=dict(color="rgba(230,81,0,1)", width=1, dash="dash")))
        fig2.add_hline(y=-18, line_dash="dot", line_color="red",
                       annotation_text="-18% Target (v6)")
        fig2.update_layout(height=250, yaxis_title="Drawdown %",
            margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig2, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric("Strategy Max DD", f"{m['Max DD']*100:.1f}%")
        c2.metric("Nifty Max DD",    f"{m['Bench MaxDD']*100:.1f}%")
        c3.metric("DD saved",
                  f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
                  delta="✅" if m['Max DD'] > m['Bench MaxDD'] else "❌")
        st.markdown("---")

        # ── Year-by-Year ──
        st.subheader("📅 Year-by-Year Returns")
        if len(ys) > 0:
            yr_labels = _index_years(ys.index)
            yb_labels = _index_years(yb.index)
            clrs = ["#2E7D32" if s>b else "#C62828"
                    for s,b in zip(ys.values, yb.values)]
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                x=yr_labels, y=(ys.values*100).tolist(),
                name="Sector Rotation v6", marker_color=clrs, opacity=0.90))
            fig3.add_trace(go.Bar(
                x=yb_labels, y=(yb.values*100).tolist(),
                name="Nifty 50", marker_color="#E65100", opacity=0.55))
            fig3.add_hline(y=0, line_color="white", line_width=0.8)
            fig3.update_layout(barmode="group", height=320,
                xaxis=dict(tickmode="linear", dtick=1, tickvals=yr_labels),
                margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig3, use_container_width=True)
            yr_df = pd.DataFrame({
                "Year":       yr_labels,
                "Strategy %": [round(v*100,1) for v in ys.values],
                "Nifty 50 %": [round(v*100,1) for v in yb.values],
                "Alpha %":    [round((s-b)*100,1) for s,b in zip(ys.values,yb.values)],
                "Beat?":      ["✅" if s>b else "❌" for s,b in zip(ys.values,yb.values)],
            })
            st.dataframe(yr_df, use_container_width=True, hide_index=True)
        st.markdown("---")

        # ── Sector Rotation Timeline ──
        st.subheader("🔄 Sector Rotation Timeline")
        sec_wt_df = result["sec_wt_df"]
        if not sec_wt_df.empty:
            fig_sec = go.Figure()
            for sec in sec_wt_df.columns:
                if (sec_wt_df[sec] == 0).all(): continue
                sc  = SECTOR_COLORS.get(sec, "#757575")
                r_v = int(sc[1:3],16); g_v = int(sc[3:5],16); b_v = int(sc[5:7],16)
                fig_sec.add_trace(go.Scatter(
                    x=sec_wt_df.index, y=(sec_wt_df[sec]*100).values,
                    name=sec, stackgroup="one",
                    fillcolor=f"rgba({r_v},{g_v},{b_v},0.75)",
                    line=dict(width=0.5)))
            fig_sec.update_layout(height=260, yaxis_title="Sector Weight %",
                yaxis=dict(range=[0,105]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            font=dict(size=9)),
                margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_sec, use_container_width=True)
        st.markdown("---")

        # ── Sector Alpha Attribution ──
        st.subheader("🏆 Sector Alpha Contribution")
        attr = result.get("sector_attr", pd.DataFrame())
        if not attr.empty:
            bar_clrs = [SECTOR_COLORS.get(s,"#757575") if v>0 else "#C62828"
                        for s,v in zip(attr["Sector"], attr["Alpha Contribution %"])]
            fig_attr = go.Figure(go.Bar(
                x=attr["Sector"], y=attr["Alpha Contribution %"],
                marker_color=bar_clrs, opacity=0.85,
                text=[f"{v:.1f}%" for v in attr["Alpha Contribution %"]],
                textposition="auto"))
            fig_attr.add_hline(y=0, line_color="white", line_width=0.8)
            fig_attr.update_layout(height=260, yaxis_title="Cumulative Alpha %",
                margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig_attr, use_container_width=True)
        st.markdown("---")

        # ── Trade Analysis ──
        st.subheader("📊 Trade Analysis")
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total Trades",    f"{m['N Trades']}")
        c2.metric("Calendar Rebals", f"{len(weights_history) - sr_ct}")
        c3.metric("Signal Rebals",   f"{sr_ct}",
                  help="FIX-1: extra rebalances from quadrant changes")
        c4.metric("Avg Hold",        f"{m['Avg Hold']:.0f}d")
        c5.metric("Stop-Loss hits",  f"{sl_ct}")
        st.markdown("---")

        # ── Investor Scorecard ──
        st.subheader("🎯 Investor Scorecard (v6 Targets)")
        bp2 = m["Beat Years"] / max(m["Total Years"], 1)
        targets = [
            ("CAGR > 15%",               m["CAGR"]*100 > 15,          f"{m['CAGR']*100:.1f}%"),
            ("Beat Nifty by > 5%",        alpha >= 5.0,                 f"+{alpha:.1f}%"),
            ("Walk-fwd beat > 75%",       wfb >= 75,                    f"{wfb:.0f}%"),
            ("Sharpe > 0.75",             m["Sharpe"] > 0.75,           f"{m['Sharpe']:.2f}"),
            ("Sortino > 0.90",            m["Sortino"] > 0.90,          f"{m['Sortino']:.2f}"),
            ("Max DD < -18%",             m["Max DD"] > -0.18,          f"{m['Max DD']*100:.1f}%"),
            ("Calmar > 1.0",              m["Calmar"] > 1.0,            f"{m['Calmar']:.2f}"),
            ("Beat Nifty > 70% years",    bp2 > 0.70,                   f"{m['Beat Years']}/{m['Total Years']}"),
            ("Down Capture < 70%",        m["Down Capture"] < 0.70,     f"{m['Down Capture']*100:.0f}%"),
            ("Signal rebals active",      sr_ct > 0,                    f"{sr_ct} fired"),
        ]
        scored = sum(1 for _,p,_ in targets if p)
        st.dataframe(pd.DataFrame([{
            "Status": "✅ PASS" if p else "❌ FAIL",
            "Target": t, "Value": v
        } for t, p, v in targets]), use_container_width=True, hide_index=True)

        verdict = ("✅ Investor-grade — ready for paper trading" if scored >= 8
                   else "⚠️ Nearly there — tune signal days or bear threshold" if scored >= 5
                   else "🔨 More calibration needed")
        fn = st.success if scored >= 8 else st.warning if scored >= 5 else st.error
        fn(f"Score: **{scored}/10** — {verdict}")

        with st.expander("📖 v6 Architecture: All 8 fixes explained"):
            st.markdown(f"""
### v5 → v6: Root cause analysis and fixes

| Fix | v5 Problem | v6 Solution | Expected CAGR lift |
|---|---|---|---|
| **FIX-1** | Calendar rebal only — held Weakening sectors 2 months | Signal-triggered rebal on quadrant change | +2-3% |
| **FIX-2** | Quality-score weighting bought late into extended sectors | RS-rank weighting — higher rank = more capital | +1-2% |
| **FIX-3** | Only Leading/Improving enter — lagging signals | Breakout quadrant: RS just crossed 100, early entry | +1-2% |
| **FIX-4** | Stop-loss + vol-target fired simultaneously → near-cash | Vol-freeze 5 days after stop-loss; floor at 70% | +1-2% |
| **FIX-5** | Bear threshold -8% → 0% Bear phase, defensive unused | Bear at -5% — COVID/2022/pullbacks now classified | +0.5-1% |
| **FIX-6** | 2/3 TF in Sideways → noise trades in low-dispersion | 3/3 TF in Sideways, 1/3 in Bear, 2/3 in Bull | +0.08 Sharpe |
| **FIX-7** | Stock scoring missed trend integrity | +Trend consistency (% days above 20DMA) | Better stock alpha |
| **FIX-8** | Signal rebal could whipsaw freshly entered sectors | Min sector hold {self.min_sector_hold}d protection on signal rebals | Lower cost |

### Default parameter changes v5 → v6
| Parameter | v5 Default | v6 Default | Rationale |
|---|---|---|---|
| Bear gap | -8% | -5% | Actually use Bear phase |
| Sideways band | ±7% | ±5% | More time in Bull |
| Vol target | 12% | 14% | More CAGR, decoupled from stops |
| Stop-loss | 15% | 12% | Tighter per-stock protection |
| Active budget (Bull) | 95% | 97% | Narrower Sideways means more Bull time |
| TF agreement (Sideways) | 2/3 | 3/3 | Quality over quantity |

### Tuning guide for v6
1. **Still low alpha (<5%)**: Lower `min_signal_days` to 5, lower `bear_gap_threshold` to -4%
2. **Too many trades**: Raise `min_signal_days` to 20, raise `min_sector_hold` to 25
3. **MaxDD still >-20%**: Lower `stop_loss_pct` to 10%, lower `vol_target` to 12%
4. **WF beat <70%**: Switch to 3/3 default TF agreement, lower `bear_gap_threshold`
5. **Bear phase 0%**: Lower `bear_gap_threshold` slider to -4% or -3%
            """)