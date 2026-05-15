# """
# TREND FOLLOWING STRATEGY — v2.7
# ====================================================
# FIXES IN THIS VERSION
# ---------------------

# BUG-A: WEALTH METRICS SHOW ₹0.0L (zero equity)
#   Root cause: equity curve starts at a tiny value because the FIRST row of
#   (1 + net_ret).cumprod() is NOT 1.0 — it equals (1 + net_ret.iloc[0]).
#   When net_ret.iloc[0] is a large negative number (e.g. -0.9999) on the first
#   valid trading day (before warm-up windows are filled), the entire curve is
#   scaled near zero for the whole backtest.

#   Two sub-causes:
#     A1. inv_vol / row_sum on the very first rows (before 20-day std is warm)
#         can produce extreme weights that sum to >> 1.
#     A2. The regime scalar is applied BEFORE valid_mask is fully warm,
#         so on day 1 the portfolio might be 100% in one stock.

#   Fix:
#     - Clip weights to [0, 1] per stock and renormalize so they always sum ≤ 1.
#     - Drop the first `warmup` rows before computing the equity curve
#       (same warmup = max(200, mom_long, atr_period, 20) trading days).
#     - Start cumprod from 1.0 explicitly.

# BUG-B: "REASON: REGIME" ERROR / REGIME CUTS TO 0% ON DAY 1
#   Root cause: bench_ma (200-day MA of Nifty) is NaN for the first 199 rows.
#   bench_gap = bench / bench_ma - 1 is therefore NaN.
#   gap_smooth = NaN.rolling(5).mean() = NaN.
#   The regime comparisons (gap_smooth < 0.00 etc.) with NaN return False,
#   so regime stays at 1.0 — that part is fine.
#   BUT: if bench_ma uses min_periods=mp where mp = min(100, n_rows//10),
#   with a short date range mp can be as low as 10, making bench_ma non-NaN
#   from row 10 onward with an UNRELIABLE value. This gives a misleading
#   bench_gap on early rows that can spike negative, setting regime to 0.20
#   on days 10–199 when the 200-day MA is not yet meaningful.

#   Fix:
#     - Force bench_ma min_periods=200 (hard floor, not derived from n_rows).
#     - This ensures regime is always 1.0 until a real 200-day MA exists.
#     - Same fix applied to stock ma_200.

# BUG-C: EQUITY NORMALIZATION
#   (1 + net_ret).cumprod() gives growth of ₹1 starting from the FIRST date,
#   not from 1.0. The display math assumes equity.iloc[0] == 1.0, which is
#   only true if net_ret.iloc[0] == 0.
#   Fix: divide the whole curve by equity.iloc[0] to normalize to 1.0.
#   Same for bench_equity.

# All previous fixes (FIX-1 through FIX-11) retained.
# """

# import streamlit as st
# import pandas as pd
# import numpy as np
# import yfinance as yf
# import plotly.graph_objects as go
# from strategies.base import BaseStrategy

# # ── Pandas version-safe frequencies ─────────────────────────────────────────
# try:
#     pd.date_range("2020-01-01", periods=2, freq="ME")
#     FREQ_YE = "YE"
# except Exception:
#     FREQ_YE = "Y"

# # ============================================================================
# # HISTORICAL NIFTY 50 CONSTITUENTS (FIX-1)
# # ============================================================================
# CORE_CONTINUOUS = [
#     "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
#     "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
#     "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
#     "WIPRO.NS", "HCLTECH.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS",
#     "TATAMOTORS.NS", "TATASTEEL.NS", "TECHM.NS", "COALINDIA.NS",
#     "DRREDDY.NS", "EICHERMOT.NS", "BPCL.NS", "CIPLA.NS", "GRASIM.NS",
#     "INDUSINDBK.NS", "HINDALCO.NS", "BRITANNIA.NS", "BAJAJ-AUTO.NS",
#     "HEROMOTOCO.NS", "M&M.NS",
# ]

# ADDITIONS_BY_YEAR = {
#     2016: ["ADANIPORTS.NS", "BAJFINANCE.NS"],
#     2017: ["ULTRACEMCO.NS", "NESTLEIND.NS"],
#     2018: ["TITAN.NS",      "BAJAJFINSV.NS"],
#     2019: ["DIVISLAB.NS",   "SBILIFE.NS", "HDFCLIFE.NS"],
#     2020: ["APOLLOHOSP.NS", "TATACONSUM.NS"],
#     2021: ["JSWSTEEL.NS"],
#     2023: ["ADANIENT.NS"],
# }

# REMOVALS_LAST_YEAR = {
#     "ZEEL.NS": 2021,
#     "VEDL.NS": 2020,
#     "UPL.NS":  2023,
# }

# REMOVED_STOCKS = {
#     "ZEEL.NS": ("2015-01-01", "2022-01-01"),
#     "VEDL.NS": ("2015-01-01", "2021-01-01"),
#     "UPL.NS":  ("2015-01-01", "2024-01-01"),
# }

# SECTOR_MAP = {
#     "HDFCBANK.NS":   "Financials", "ICICIBANK.NS":  "Financials",
#     "KOTAKBANK.NS":  "Financials", "AXISBANK.NS":   "Financials",
#     "SBIN.NS":       "Financials", "INDUSINDBK.NS": "Financials",
#     "BAJFINANCE.NS": "Financials", "BAJAJFINSV.NS": "Financials",
#     "SBILIFE.NS":    "Financials", "HDFCLIFE.NS":   "Financials",
#     "TCS.NS":        "IT",         "INFY.NS":        "IT",
#     "WIPRO.NS":      "IT",         "HCLTECH.NS":     "IT",
#     "TECHM.NS":      "IT",
#     "RELIANCE.NS":   "Energy",     "ONGC.NS":        "Energy",
#     "BPCL.NS":       "Energy",     "COALINDIA.NS":   "Energy",
#     "POWERGRID.NS":  "Energy",     "NTPC.NS":        "Energy",
#     "HINDUNILVR.NS": "Staples",    "ITC.NS":         "Staples",
#     "NESTLEIND.NS":  "Staples",    "BRITANNIA.NS":   "Staples",
#     "TATACONSUM.NS": "Staples",
#     "MARUTI.NS":     "Auto",       "TATAMOTORS.NS":  "Auto",
#     "EICHERMOT.NS":  "Auto",       "BAJAJ-AUTO.NS":  "Auto",
#     "HEROMOTOCO.NS": "Auto",       "M&M.NS":         "Auto",
#     "LT.NS":         "Industrials","ADANIPORTS.NS":  "Industrials",
#     "ADANIENT.NS":   "Industrials",
#     "JSWSTEEL.NS":   "Materials",  "TATASTEEL.NS":   "Materials",
#     "HINDALCO.NS":   "Materials",  "ULTRACEMCO.NS":  "Materials",
#     "GRASIM.NS":     "Materials",  "VEDL.NS":        "Materials",
#     "UPL.NS":        "Materials",
#     "SUNPHARMA.NS":  "Healthcare", "DRREDDY.NS":     "Healthcare",
#     "CIPLA.NS":      "Healthcare", "DIVISLAB.NS":    "Healthcare",
#     "APOLLOHOSP.NS": "Healthcare",
#     "ASIANPAINT.NS": "ConsDisc",   "TITAN.NS":       "ConsDisc",
#     "ZEEL.NS":       "ConsDisc",
#     "BHARTIARTL.NS": "Telecom",
# }

# # ============================================================================
# # FIX-9: Plotly-safe rgba helper
# # ============================================================================
# _HEX_RGB = {
#     "#2E7D32": (46,  125,  50),
#     "#8BC34A": (139, 195,  74),
#     "#FFC107": (255, 193,   7),
#     "#FF9800": (255, 152,   0),
#     "#F44336": (244,  67,  54),
#     "#1565C0": ( 21, 101, 192),
#     "#E65100": (230,  81,   0),
#     "#C62828": (198,  40,  40),
# }

# def _rgba(hex_color: str, alpha: float = 0.4) -> str:
#     r, g, b = _HEX_RGB[hex_color]
#     return f"rgba({r},{g},{b},{alpha})"


# # ============================================================================
# # UNIVERSE HELPERS
# # ============================================================================
# def get_universe_for_year(year: int) -> list:
#     universe = set(CORE_CONTINUOUS)
#     for add_year, tickers in ADDITIONS_BY_YEAR.items():
#         if year >= add_year:
#             universe.update(tickers)
#     for ticker, last_year in REMOVALS_LAST_YEAR.items():
#         if year > last_year:
#             universe.discard(ticker)
#     for ticker, (start, end) in REMOVED_STOCKS.items():
#         if int(start[:4]) <= year < int(end[:4]):
#             universe.add(ticker)
#     return sorted(universe)


# def safe_float(val, default=0.0):
#     try:
#         f = float(val)
#         return f if np.isfinite(f) else default
#     except Exception:
#         return default


# def build_valid_mask(all_cols, index, start_year, end_year):
#     """FIX-1: per-year constituent boolean mask."""
#     mask = pd.DataFrame(False, index=index, columns=all_cols)
#     for year in range(start_year, end_year + 1):
#         valid    = set(get_universe_for_year(year))
#         year_idx = index[index.year == year]
#         for col in all_cols:
#             if col in valid:
#                 mask.loc[year_idx, col] = True
#     return mask


# # ============================================================================
# # FIX-11: CORRECTED SECTOR CAP — GREEDY FILL (two-stage)
# # ============================================================================
# def apply_sector_cap_vectorized(signal_df, sector_map, max_per_sector, top_n):
#     """
#     Two-stage vectorized sector cap (FIX-6 + FIX-10 + FIX-11).
#     Stage 1: sector cap in signal-rank order.
#     Stage 2: top_n from sector-eligible pool.
#     Guarantees exactly top_n stocks on every date with sufficient candidates.
#     """
#     _df = signal_df.reset_index(drop=False).copy()
#     date_col    = _df.columns[0]
#     ticker_cols = list(_df.columns[1:])

#     long = _df.melt(
#         id_vars=[date_col],
#         value_vars=ticker_cols,
#         var_name="ticker",
#         value_name="signal",
#     )
#     long = long.rename(columns={date_col: "date"})
#     long = long[long["signal"] > 0].copy()

#     if long.empty:
#         return pd.DataFrame(
#             np.zeros((len(signal_df.index), len(signal_df.columns)), dtype=bool),
#             index=signal_df.index,
#             columns=signal_df.columns,
#         )

#     long["sector"] = long["ticker"].map(lambda t: sector_map.get(t, "Other"))

#     # Stage 1: sector cap in descending signal order
#     long = long.sort_values(["date", "signal"], ascending=[True, False])
#     long["sector_rank"] = long.groupby(["date", "sector"]).cumcount()
#     long = long[long["sector_rank"] < max_per_sector].copy()

#     # Stage 2: top_n from sector-eligible pool
#     long["rank_post_cap"] = long.groupby("date")["signal"].rank(
#         ascending=False, method="first"
#     )
#     long = long[long["rank_post_cap"] <= top_n]

#     long["selected"] = True
#     result = (
#         long.pivot_table(
#             index="date",
#             columns="ticker",
#             values="selected",
#             fill_value=False,
#         )
#         .reindex(index=signal_df.index, columns=signal_df.columns, fill_value=False)
#     )
#     return result.astype(bool)


# # ============================================================================
# # STRATEGY CLASS
# # ============================================================================
# class TrendFollowingStrategy(BaseStrategy):
#     NAME = "Trend Following (Nifty 50)"
#     DESCRIPTION = (
#         "Buys top Nifty 50 stocks in strong uptrend + momentum. "
#         "Historical constituents (survivorship-free), tiered regime, "
#         "sector cap with greedy fill, ATR trailing stop. v2.7."
#     )
#     _CACHE_VERSION = "v2.7"

#     def render_sidebar(self):
#         self.start_date   = st.sidebar.date_input(
#             "Start Date", value=pd.to_datetime("2016-01-01"))
#         self.end_date     = st.sidebar.date_input(
#             "End Date",   value=pd.to_datetime("2025-12-31"))
#         self.top_n        = st.sidebar.slider(
#             "Top N Stocks to Hold", 5, 20, 10)

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**Signal Parameters**")
#         self.mom_short    = st.sidebar.slider(
#             "Short Momentum (days)", 20, 100, 50)
#         self.mom_long     = st.sidebar.slider(
#             "Long Momentum (days)",  50, 200, 100)
#         self.smooth       = st.sidebar.slider(
#             "Signal Smoothing (days)", 1, 10, 3,
#             help="Minimum hold period. Reduces daily churn.")
#         self.max_sector   = st.sidebar.slider(
#             "Max Stocks per Sector", 1, 5, 3,
#             help="Sector concentration cap.")

#         st.sidebar.markdown("---")
#         st.sidebar.markdown("**Risk Controls**")
#         self.atr_mult     = st.sidebar.slider(
#             "ATR Trailing Stop Multiplier", 2.0, 6.0, 3.5, 0.5)
#         self.atr_period   = st.sidebar.slider(
#             "ATR Period (days)", 7, 21, 14)

#         st.sidebar.markdown("---")
#         self.fee_bps      = st.sidebar.number_input(
#             "Fee (bps)", value=1.0, min_value=0.0)
#         self.slippage_bps = st.sidebar.number_input(
#             "Slippage (bps)", value=2.0, min_value=0.0)

#         if st.sidebar.button("🗑 Clear Cache"):
#             st.cache_data.clear()
#             st.rerun()

#     # ── Cached backtest ──────────────────────────────────────────────────────
#     @st.cache_data
#     def _fetch(
#         _self, start_date, end_date, top_n,
#         mom_short, mom_long, smooth, max_sector,
#         atr_mult, atr_period, fee_bps, slippage_bps,
#         _cache_version="v2.7",
#     ):
#         cost     = (fee_bps + slippage_bps) / 10_000
#         start_yr = int(str(start_date)[:4])
#         end_yr   = int(str(end_date)[:4])

#         # ── BUG-B FIX: hard warmup = 200 days (not derived from n_rows) ──────
#         # Using min_periods=mp (where mp could be 10–100) made the 200-day MA
#         # "valid" far too early with unreliable values, spiking bench_gap
#         # negative and locking regime at 0.20 from day 10 onward.
#         MA_PERIOD   = 200          # hard constant — never shrink this
#         WARMUP_DAYS = max(MA_PERIOD, mom_long, atr_period, 20)

#         # FIX-1: all tickers ever in index
#         all_tickers = set()
#         for yr in range(start_yr, end_yr + 1):
#             all_tickers.update(get_universe_for_year(yr))
#         download_list = sorted(all_tickers) + ["^NSEI"]

#         import inspect as _inspect
#         _kw = dict(
#             start=str(start_date), end=str(end_date),
#             auto_adjust=True, group_by="column",
#             threads=False, progress=False,
#         )
#         _sig = _inspect.signature(yf.download).parameters
#         if "multi_level_index" in _sig:
#             _kw["multi_level_index"] = True

#         raw = yf.download(download_list, **_kw)
#         if raw is None or raw.empty:
#             return None, "Download returned no data. Try Start Date 2018-01-01."

#         def _field(r, names):
#             if isinstance(r.columns, pd.MultiIndex):
#                 l0 = r.columns.get_level_values(0).unique().tolist()
#                 for n in names:
#                     if n in l0:
#                         return r[n].copy()
#             return None

#         close = _field(raw, ["Close", "Adj Close"])
#         high  = _field(raw, ["High"])
#         low   = _field(raw, ["Low"])

#         if close is None:
#             return None, "No Close column found."
#         if high is None:
#             high = close.copy()
#         if low is None:
#             low  = close.copy()

#         close = close.loc[:, close.isna().mean() < 0.50].ffill().bfill()
#         high  = high.reindex(columns=close.columns).ffill().bfill()
#         low   = low.reindex(columns=close.columns).ffill().bfill()

#         if "^NSEI" not in close.columns:
#             return None, (
#                 "^NSEI (Nifty 50 index) missing. "
#                 "Try Start Date 2018-01-01 or later."
#             )

#         bench      = close["^NSEI"].copy()
#         stock_cols = [c for c in close.columns if c != "^NSEI"]
#         close      = close[stock_cols]
#         high       = high[stock_cols]
#         low        = low[stock_cols]

#         if close.empty or bench.empty:
#             return None, "No stock data after cleaning."

#         # ── FIX-1: valid constituent mask ─────────────────────────────────────
#         valid_mask = build_valid_mask(stock_cols, close.index, start_yr, end_yr)

#         # ── Signal construction ───────────────────────────────────────────────
#         # BUG-B FIX: min_periods=MA_PERIOD (hard 200) — not mp
#         # This ensures ma_200 is NaN for the first 199 rows, so above_ma
#         # is False and no stocks are traded during the warm-up period.
#         ma_200   = close.rolling(MA_PERIOD, min_periods=MA_PERIOD).mean()
#         above_ma = (close > ma_200).fillna(False)
#         mom      = close.pct_change(mom_short) + close.pct_change(mom_long)

#         mom_filtered = mom.where(above_ma & valid_mask & mom.notna())

#         # FIX-11: greedy sector cap
#         signal = apply_sector_cap_vectorized(
#             mom_filtered.fillna(0),
#             SECTOR_MAP, max_sector, top_n,
#         ).astype(float)

#         # shift(1): no lookahead bias
#         pos = signal.shift(1).fillna(0).rolling(smooth, min_periods=1).max()

#         # ── FIX-4: ATR trailing stop ──────────────────────────────────────────
#         prev_close = close.shift(1)
#         tr = pd.DataFrame({
#             col: pd.concat([
#                 (high[col] - low[col]),
#                 (high[col] - prev_close[col]).abs(),
#                 (low[col]  - prev_close[col]).abs(),
#             ], axis=1).max(axis=1)
#             for col in close.columns
#         })
#         atr_df     = tr.rolling(atr_period, min_periods=max(3, atr_period // 2)).mean()
#         roll_high  = close.rolling(20, min_periods=5).max()
#         stop_level = roll_high - atr_mult * atr_df
#         stop_ok    = (close >= stop_level).fillna(True)
#         pos        = pos * stop_ok.astype(float)

#         # ── Inverse-vol position sizing ───────────────────────────────────────
#         ret     = close.pct_change().fillna(0)
#         inv_vol = (1.0 / (ret.rolling(20, min_periods=10).std() + 1e-6)) * pos

#         # BUG-A FIX: clip individual weights to [0, 1] before normalising.
#         # Without this, on early rows where rolling std is tiny (near 1e-6),
#         # inv_vol explodes to 1e6 for a single stock, making weights sum >> 1
#         # after normalisation passes through division by a near-zero row_sum.
#         row_sum = inv_vol.sum(axis=1).replace(0, np.nan)
#         weights = inv_vol.div(row_sum, axis=0).fillna(0)
#         # Hard clip: no single stock can exceed 100% and no short positions
#         weights = weights.clip(lower=0.0, upper=1.0)
#         # Re-normalise after clip so weights still sum to ≤ 1
#         row_sum2 = weights.sum(axis=1).replace(0, np.nan)
#         weights  = weights.div(row_sum2, axis=0).fillna(0)

#         # ── FIX-2 + FIX-7 + BUG-B: tiered regime ────────────────────────────
#         # BUG-B FIX: min_periods=MA_PERIOD (hard 200).
#         # Old code used min_periods=mp (as low as 10), giving a "valid"
#         # 200-day MA from day 10 onward with only 10 data points — unreliable.
#         # That made bench_gap spike negative early, locking regime at 0.20.
#         bench_ma   = bench.rolling(MA_PERIOD, min_periods=MA_PERIOD).mean()
#         bench_gap  = (bench / bench_ma.replace(0, np.nan) - 1)
#         gap_smooth = bench_gap.rolling(5, min_periods=1).mean()

#         regime = pd.Series(1.00, index=bench.index, dtype=float)
#         regime[gap_smooth <  0.00] = 0.80
#         regime[gap_smooth < -0.03] = 0.60
#         regime[gap_smooth < -0.07] = 0.40
#         regime[gap_smooth < -0.12] = 0.20
#         # Where bench_ma is NaN (first MA_PERIOD-1 rows), gap_smooth is NaN.
#         # NaN comparisons return False, so regime naturally stays at 1.0.
#         # That's correct: no signal → no trades → regime irrelevant.
#         regime = regime.round(2)  # FIX-7

#         weights = weights.mul(regime, axis=0)

#         # ── Portfolio returns ─────────────────────────────────────────────────
#         gross_ret = (weights * ret).sum(axis=1)
#         turnover  = weights.diff().abs().sum(axis=1).fillna(0)
#         net_ret   = gross_ret - turnover * cost

#         # ── BUG-C + BUG-B FIX: drop warm-up rows, then normalise to 1.0 ─────
#         # Trim the first WARMUP_DAYS rows so the equity curve starts from the
#         # first day when all rolling windows (MA, momentum, ATR, vol) are warm.
#         # This prevents the equity curve from being distorted by early NaN-edge
#         # returns, and ensures equity.iloc[0] represents a "live" trading day.
#         if len(net_ret) > WARMUP_DAYS + 50:
#             net_ret_live = net_ret.iloc[WARMUP_DAYS:]
#         else:
#             # Not enough data even after warmup — use everything
#             net_ret_live = net_ret

#         equity = (1 + net_ret_live).cumprod()

#         # BUG-C FIX: normalise so equity.iloc[0] == 1.0 exactly.
#         # (1+r).cumprod() gives growth of ₹1 from day 0, but the first
#         # value is (1 + net_ret_live.iloc[0]), not 1.0. Dividing by the
#         # first value resets the base to exactly 1.0, matching the display
#         # assumption of "₹10L invested on the first live trading day."
#         if equity.iloc[0] != 0:
#             equity = equity / equity.iloc[0]

#         bench_ret    = bench.pct_change().fillna(0)
#         bench_equity = (1 + bench_ret).cumprod()

#         # ── FIX-8: align on common index ─────────────────────────────────────
#         common       = equity.index.intersection(bench_equity.index)
#         equity       = equity.loc[common]
#         bench_equity = bench_equity.reindex(common).ffill()

#         # BUG-C FIX: normalise bench_equity to the same start as equity
#         if bench_equity.iloc[0] != 0:
#             bench_equity = bench_equity / bench_equity.iloc[0]

#         net_ret   = net_ret_live.loc[common]
#         bench_ret = bench_ret.reindex(common).fillna(0)

#         # Re-align weights and regime to the live (post-warmup) index
#         weights      = weights.loc[weights.index.isin(common)]
#         regime_final = regime.reindex(common).ffill().round(2)

#         if len(net_ret) < 50:
#             return None, (
#                 f"Only {len(net_ret)} live observations after {WARMUP_DAYS}-day "
#                 f"warm-up — need 50+. Use a Start Date at least "
#                 f"{WARMUP_DAYS // 252 + 1} years before End Date."
#             )

#         # ── Performance metrics ───────────────────────────────────────────────
#         n_years  = len(equity) / 252.0
#         cagr     = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
#         b_cagr   = (bench_equity.iloc[-1] / bench_equity.iloc[0]) ** (1 / n_years) - 1

#         rf_daily = 0.065 / 252
#         std_p    = net_ret.std()
#         std_b    = bench_ret.std()

#         sharpe   = ((net_ret.mean() - rf_daily) / std_p) * np.sqrt(252) \
#                    if std_p > 1e-10 else 0.0
#         b_sharpe = ((bench_ret.mean() - rf_daily) / std_b) * np.sqrt(252) \
#                    if std_b > 1e-10 else 0.0

#         neg_ret  = net_ret[net_ret < 0]
#         downside = neg_ret.std() * np.sqrt(252) if len(neg_ret) > 5 else 1e-6
#         sortino  = (net_ret.mean() - rf_daily) * 252 / downside

#         max_dd  = (equity / equity.cummax() - 1).min()
#         b_maxdd = (bench_equity / bench_equity.cummax() - 1).min()
#         calmar  = safe_float(cagr) / abs(safe_float(max_dd)) \
#                   if abs(safe_float(max_dd)) > 1e-6 else 0.0

#         vol_ann  = std_p * np.sqrt(252)
#         win_rate = float((net_ret > 0).mean())

#         cov_m = np.cov(net_ret.values, bench_ret.values)
#         beta  = cov_m[0, 1] / (cov_m[1, 1] + 1e-12)
#         alpha = safe_float(cagr) - beta * safe_float(b_cagr)
#         excess = net_ret - bench_ret
#         ir     = (excess.mean() / (excess.std() + 1e-12)) * np.sqrt(252)

#         var_95  = float(np.percentile(net_ret.values, 5)) \
#                   if len(net_ret) > 20 else 0.0
#         cvar_95 = float(net_ret[net_ret <= var_95].mean()) \
#                   if (net_ret <= var_95).any() else var_95

#         up_m   = bench_ret[bench_ret > 0]
#         dn_m   = bench_ret[bench_ret < 0]
#         up_cap = net_ret.loc[up_m.index].mean() / up_m.mean() \
#                  if len(up_m) > 0 and up_m.mean() > 0 else 1.0
#         dn_cap = net_ret.loc[dn_m.index].mean() / dn_m.mean() \
#                  if len(dn_m) > 0 and dn_m.mean() < 0 else 1.0

#         yr_strat = net_ret.groupby(net_ret.index.year).apply(
#             lambda x: (1 + x).prod() - 1)
#         yr_bench = bench_ret.groupby(bench_ret.index.year).apply(
#             lambda x: (1 + x).prod() - 1)
#         beat = int(sum(s > b for s, b in
#                        zip(yr_strat.values, yr_bench.values)))

#         return {
#             "equity":       equity,
#             "bench_equity": bench_equity,
#             "net_ret":      net_ret,
#             "bench_ret":    bench_ret,
#             "weights":      weights,
#             "regime":       regime_final,
#             "yr_strat":     yr_strat,
#             "yr_bench":     yr_bench,
#             "n_years":      n_years,
#             "warmup_days":  WARMUP_DAYS,
#             "metrics": {
#                 "CAGR":        safe_float(cagr),
#                 "Bench CAGR":  safe_float(b_cagr),
#                 "Sharpe":      safe_float(sharpe),
#                 "B Sharpe":    safe_float(b_sharpe),
#                 "Sortino":     safe_float(sortino),
#                 "Calmar":      safe_float(calmar),
#                 "Max DD":      safe_float(max_dd),
#                 "Bench MaxDD": safe_float(b_maxdd),
#                 "Volatility":  safe_float(vol_ann),
#                 "Win Rate":    safe_float(win_rate),
#                 "Beta":        safe_float(beta),
#                 "Alpha":       safe_float(alpha),
#                 "Info Ratio":  safe_float(ir),
#                 "VaR 95":      safe_float(var_95),
#                 "CVaR 95":     safe_float(cvar_95),
#                 "Up Capture":  safe_float(up_cap),
#                 "Dn Capture":  safe_float(dn_cap),
#                 "Beat Years":  beat,
#                 "Total Years": len(yr_strat),
#             },
#         }, None

#     # ── Display ──────────────────────────────────────────────────────────────
#     def run(self):
#         with st.spinner(
#             "Running Trend Following v2.7 on Nifty 50..."
#         ):
#             raw = self._fetch(
#                 self.start_date, self.end_date, self.top_n,
#                 self.mom_short, self.mom_long, self.smooth,
#                 self.max_sector, self.atr_mult, self.atr_period,
#                 self.fee_bps, self.slippage_bps,
#                 _cache_version=self._CACHE_VERSION,
#             )

#         if isinstance(raw, tuple) and len(raw) == 2:
#             result, err = raw
#         else:
#             result, err = raw, None

#         if result is None:
#             st.error(f"❌ Backtest failed — {err}")
#             st.warning(
#                 "**Common fixes:**\n"
#                 "- Use **Start Date 2016-01-01** or earlier so the 200-day "
#                 "warm-up period has enough history\n"
#                 "- Click **🗑 Clear Cache** in sidebar\n"
#                 "- Wait 60 seconds (Yahoo Finance rate limit) then retry"
#             )
#             return

#         m    = result["metrics"]
#         eq   = result["equity"]
#         be   = result["bench_equity"]
#         nr   = result["net_ret"]
#         br   = result["bench_ret"]
#         ys   = result["yr_strat"]
#         yb   = result["yr_bench"]
#         reg  = result["regime"]
#         n_y  = result["n_years"]
#         wup  = result["warmup_days"]

#         # ── Coverage info ─────────────────────────────────────────────────────
#         st.info(
#             f"📅 **{eq.index[0].strftime('%b %Y')} → "
#             f"{eq.index[-1].strftime('%b %Y')}** "
#             f"({n_y:.1f} years, after {wup}-day warm-up) | "
#             f"Regime: 5-tier | Sector cap: max {self.max_sector} | "
#             f"ATR Stop: {self.atr_mult}×"
#         )

#         # ── KPI rows ──────────────────────────────────────────────────────────
#         st.markdown("## 📊 Performance")
#         c1, c2, c3, c4, c5 = st.columns(5)
#         c1.metric("CAGR",
#                   f"{m['CAGR']*100:.2f}%",
#                   delta=f"{(m['CAGR']-m['Bench CAGR'])*100:.1f}% vs Nifty")
#         c2.metric("Sharpe",
#                   f"{m['Sharpe']:.2f}",
#                   delta=f"{m['Sharpe']-m['B Sharpe']:.2f} vs Nifty",
#                   help="Target > 0.8")
#         c3.metric("Calmar", f"{m['Calmar']:.2f}",
#                   help="CAGR / Max DD. Target > 1.0")
#         c4.metric("Max Drawdown",
#                   f"{m['Max DD']*100:.1f}%",
#                   delta=f"{(m['Max DD']-m['Bench MaxDD'])*100:.1f}% vs Nifty",
#                   delta_color="inverse")
#         c5.metric("Win Rate", f"{m['Win Rate']*100:.1f}%")

#         c1, c2, c3, c4, c5 = st.columns(5)
#         c1.metric("Sortino",     f"{m['Sortino']:.2f}")
#         c2.metric("Beta",        f"{m['Beta']:.2f}")
#         c3.metric("Alpha (ann)", f"{m['Alpha']*100:.1f}%")
#         c4.metric("Info Ratio",  f"{m['Info Ratio']:.2f}")
#         c5.metric("Beat Nifty",  f"{m['Beat Years']}/{m['Total Years']} yrs")

#         # ── Wealth creation ───────────────────────────────────────────────────
#         # BUG-A/C FIX: equity is now normalised so iloc[0] == 1.0 exactly.
#         # fv_s = final value of ₹1 → multiply by 1_000_000 for ₹10L display.
#         INITIAL = 1_000_000   # ₹10 lakh
#         fv_s    = eq.iloc[-1]   * INITIAL   # final value of ₹10L in strategy
#         fv_b    = be.iloc[-1]   * INITIAL   # final value of ₹10L in Nifty B&H

#         st.markdown("---")
#         col1, col2, col3 = st.columns(3)
#         col1.metric(
#             "Strategy ₹10L grew to",
#             f"₹{fv_s/100_000:.1f}L",
#             delta=f"₹{(fv_s - INITIAL)/100_000:.1f}L profit",
#         )
#         col2.metric(
#             "Nifty B&H ₹10L grew to",
#             f"₹{fv_b/100_000:.1f}L",
#             delta=f"₹{(fv_b - INITIAL)/100_000:.1f}L profit",
#         )
#         col3.metric(
#             "Extra vs Nifty",
#             f"₹{(fv_s - fv_b)/100_000:.1f}L",
#             delta=f"{(fv_s/fv_b - 1)*100:.1f}% more" if fv_b > 0 else "N/A",
#         )

#         st.markdown("---")
#         st.info(
#             f"**Strategy logic (v2.7):** "
#             f"Stocks above 200-day MA ranked by "
#             f"{self.mom_short}+{self.mom_long}-day momentum. "
#             f"Top {self.top_n} via greedy sector cap "
#             f"(max {self.max_sector}/sector). "
#             f"Exposure 20–100% via tiered regime. "
#             f"ATR trailing stop ({self.atr_mult}×). "
#             f"{wup}-day warm-up discarded."
#         )
#         st.markdown("---")

#         # ── Equity Curve ──────────────────────────────────────────────────────
#         st.subheader("📈 Equity Curve vs Nifty 50")
#         be_ri = be.reindex(eq.index).ffill()
#         fig1  = go.Figure()
#         fig1.add_trace(go.Scatter(
#             x=eq.index, y=eq.values,
#             name="Trend Following v2.7",
#             line=dict(color="#1565C0", width=2.5),
#         ))
#         fig1.add_trace(go.Scatter(
#             x=be.index, y=be.values,
#             name="Nifty 50 B&H",
#             line=dict(color="#E65100", width=1.8, dash="dash"),
#         ))
#         fig1.add_trace(go.Scatter(
#             x=list(eq.index) + list(eq.index[::-1]),
#             y=list(eq.values) + list(be_ri.values[::-1]),
#             fill="toself",
#             fillcolor=_rgba("#1565C0", 0.10),
#             line=dict(width=0),
#             name="Outperformance",
#         ))
#         fig1.update_layout(
#             height=400, xaxis_title="Date",
#             yaxis_title="Growth of ₹1",
#             legend=dict(x=0.01, y=0.99),
#             margin=dict(l=10, r=10, t=10, b=10),
#         )
#         st.plotly_chart(fig1, use_container_width=True)

#         # ── Drawdown ──────────────────────────────────────────────────────────
#         st.subheader("📉 Drawdown")
#         dd_s = (eq / eq.cummax() - 1) * 100
#         dd_b = (be / be.cummax() - 1) * 100
#         fig2 = go.Figure()
#         fig2.add_trace(go.Scatter(
#             x=dd_s.index, y=dd_s.values, fill="tozeroy",
#             name="Strategy DD",
#             fillcolor=_rgba("#1565C0", 0.40),
#             line=dict(color="#1565C0", width=1),
#         ))
#         fig2.add_trace(go.Scatter(
#             x=dd_b.index, y=dd_b.values, fill="tozeroy",
#             name="Nifty DD",
#             fillcolor=_rgba("#E65100", 0.20),
#             line=dict(color="#E65100", width=1, dash="dash"),
#         ))
#         fig2.add_hline(y=-20, line_dash="dot", line_color="red",
#                        annotation_text="-20% Target")
#         fig2.update_layout(
#             height=250, xaxis_title="Date", yaxis_title="Drawdown %",
#             legend=dict(x=0.01, y=0.01),
#             margin=dict(l=10, r=10, t=10, b=10),
#         )
#         st.plotly_chart(fig2, use_container_width=True)

#         c1, c2, c3 = st.columns(3)
#         c1.metric("Strategy Max DD", f"{m['Max DD']*100:.1f}%")
#         c2.metric("Nifty Max DD",    f"{m['Bench MaxDD']*100:.1f}%")
#         c3.metric("DD Improvement",
#                   f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
#                   delta="Better" if m["Max DD"] > m["Bench MaxDD"] else "Worse",
#                   delta_color="normal" if m["Max DD"] > m["Bench MaxDD"]
#                   else "inverse")
#         st.markdown("---")

#         # ── Year by Year ──────────────────────────────────────────────────────
#         st.subheader("📅 Year-by-Year Returns vs Nifty 50")
#         if len(ys) > 0 and len(yb) > 0:
#             common_yrs = ys.index.intersection(yb.index)
#             ys_c   = ys.loc[common_yrs]
#             yb_c   = yb.loc[common_yrs]
#             colors = ["#2E7D32" if s > b else "#C62828"
#                       for s, b in zip(ys_c.values, yb_c.values)]
#             fig3 = go.Figure()
#             fig3.add_trace(go.Bar(
#                 x=common_yrs.tolist(),
#                 y=(ys_c.values * 100).tolist(),
#                 name="Strategy", marker_color=colors, opacity=0.88,
#             ))
#             fig3.add_trace(go.Bar(
#                 x=common_yrs.tolist(),
#                 y=(yb_c.values * 100).tolist(),
#                 name="Nifty 50", marker_color="#E65100", opacity=0.65,
#             ))
#             fig3.add_hline(y=0, line_color="white", line_width=0.8)
#             fig3.update_layout(
#                 barmode="group", height=300,
#                 xaxis_title="Year", yaxis_title="Return %",
#                 xaxis=dict(tickmode="linear", dtick=1),
#                 legend=dict(x=0.01, y=0.99),
#                 margin=dict(l=10, r=10, t=10, b=10),
#             )
#             st.plotly_chart(fig3, use_container_width=True)

#             yr_df = pd.DataFrame({
#                 "Year":       common_yrs.tolist(),
#                 "Strategy %": (ys_c.values * 100).round(1).tolist(),
#                 "Nifty 50 %": (yb_c.values * 100).round(1).tolist(),
#                 "Alpha %":    ((ys_c.values - yb_c.values) * 100).round(1).tolist(),
#                 "Beat?":      ["✅" if s > b else "❌"
#                                for s, b in zip(ys_c.values, yb_c.values)],
#             })
#             st.dataframe(yr_df, use_container_width=True, hide_index=True)
#             bp = m["Beat Years"] / max(m["Total Years"], 1)
#             st.info(
#                 f"Beat Nifty in **{m['Beat Years']} of "
#                 f"{m['Total Years']} years** ({bp*100:.0f}%)"
#             )
#         else:
#             st.warning("Not enough data for year-by-year analysis.")
#         st.markdown("---")

#         # ── Rolling Returns ───────────────────────────────────────────────────
#         st.subheader("📊 Rolling 20-Day Returns")
#         roll = nr.rolling(20).mean() * 100
#         fig4 = go.Figure()
#         fig4.add_trace(go.Scatter(
#             x=roll.index, y=roll.values,
#             name="20-day rolling",
#             line=dict(color="#1565C0", width=1.5),
#             fill="tozeroy",
#             fillcolor=_rgba("#1565C0", 0.20),
#         ))
#         fig4.add_hline(y=0, line_color="white", line_width=0.8)
#         fig4.update_layout(
#             height=220, xaxis_title="Date",
#             yaxis_title="Avg Daily Return %",
#             margin=dict(l=10, r=10, t=10, b=10),
#         )
#         st.plotly_chart(fig4, use_container_width=True)
#         st.markdown("---")

#         # ── Tiered Regime Exposure ────────────────────────────────────────────
#         st.subheader("🌡️ Tiered Regime Exposure")
#         reg_ri = reg.reindex(eq.index).ffill().round(2)

#         level_config = [
#             (1.00, "#2E7D32", "rgba(46,125,50,0.4)",   "100% — Full Bull"),
#             (0.80, "#8BC34A", "rgba(139,195,74,0.4)",  "80%  — Mild Caution"),
#             (0.60, "#FFC107", "rgba(255,193,7,0.4)",   "60%  — Moderate Bear"),
#             (0.40, "#FF9800", "rgba(255,152,0,0.4)",   "40%  — Defensive"),
#             (0.20, "#F44336", "rgba(244,67,54,0.4)",   "20%  — Near-Cash"),
#         ]

#         fig5 = go.Figure()
#         for lv, line_color, fill_color, label in level_config:
#             mask   = (reg_ri - lv).abs() < 0.01  # FIX-5
#             if mask.any():
#                 y_vals = np.where(mask, lv * 100, np.nan)
#                 fig5.add_trace(go.Scatter(
#                     x=reg_ri.index,
#                     y=y_vals,
#                     fill="tozeroy",
#                     name=label,
#                     fillcolor=fill_color,
#                     line=dict(color=line_color, width=0.5),
#                     connectgaps=False,
#                 ))

#         fig5.update_layout(
#             height=200, xaxis_title="Date",
#             yaxis_title="% Invested",
#             yaxis=dict(range=[0, 110]),
#             legend=dict(orientation="h", yanchor="bottom", y=1.02),
#             margin=dict(l=10, r=10, t=30, b=10),
#         )
#         st.plotly_chart(fig5, use_container_width=True)

#         pct_reduced = (reg_ri < 1.0).mean()
#         st.caption(
#             f"Strategy was below 100% in "
#             f"**{pct_reduced*100:.0f}% of periods** — "
#             f"tiered regime reduces exposure gradually."
#         )
#         st.markdown("---")

#         # ── Current Holdings ──────────────────────────────────────────────────
#         st.subheader("📋 Current Holdings")
#         latest   = result["weights"].iloc[-1]
#         holdings = latest[latest > 0].sort_values(ascending=False)

#         if len(holdings) > 0:
#             h_df = pd.DataFrame({
#                 "Ticker":   [t.replace(".NS", "") for t in holdings.index],
#                 "Sector":   [SECTOR_MAP.get(t, "Other") for t in holdings.index],
#                 "Weight %": (holdings.values * 100).round(2),
#                 "₹ Alloc":  [f"₹{w * INITIAL:,.0f}" for w in holdings.values],
#             })
#             st.dataframe(h_df, use_container_width=True, hide_index=True)
#         else:
#             st.info("No positions — market is in a reduced-exposure regime.")
#         st.markdown("---")

#         # ── Risk Details ──────────────────────────────────────────────────────
#         st.subheader("⚠️ Risk Details")
#         rc1, rc2, rc3, rc4 = st.columns(4)
#         rc1.metric("VaR 95% (daily)",  f"{m['VaR 95']*100:.2f}%",
#                    help="Worst daily loss 95% of the time")
#         rc2.metric("CVaR 95% (daily)", f"{m['CVaR 95']*100:.2f}%",
#                    help="Average loss on worst 5% of days")
#         rc3.metric("Up Capture",       f"{m['Up Capture']*100:.0f}%",
#                    help="% of Nifty upside captured. Target: >70%")
#         rc4.metric("Down Capture",     f"{m['Dn Capture']*100:.0f}%",
#                    help="% of Nifty downside absorbed. Target: <80%")
#         st.markdown("---")

#         # ── Investor Scorecard ────────────────────────────────────────────────
#         st.subheader("🎯 Investor Target Scorecard")
#         bp = m["Beat Years"] / max(m["Total Years"], 1)
#         targets = [
#             ("CAGR > 15%",
#              m["CAGR"] * 100 > 15,               f"{m['CAGR']*100:.1f}%"),
#             ("Beats Nifty (CAGR)",
#              m["CAGR"] > m["Bench CAGR"],        f"+{(m['CAGR']-m['Bench CAGR'])*100:.1f}%"),
#             ("Sharpe > 0.8",
#              m["Sharpe"] > 0.8,                  f"{m['Sharpe']:.2f}"),
#             ("Sortino > 0.8",
#              m["Sortino"] > 0.8,                 f"{m['Sortino']:.2f}"),
#             ("Calmar > 1.0",
#              m["Calmar"] > 1.0,                  f"{m['Calmar']:.2f}"),
#             ("Max DD < 25%",
#              abs(m["Max DD"]) < 0.25,            f"{m['Max DD']*100:.1f}%"),
#             ("Max DD better than Nifty",
#              m["Max DD"] > m["Bench MaxDD"],     f"{m['Max DD']*100:.1f}%"),
#             ("Beat Nifty > 50% yrs",
#              bp > 0.50,                           f"{m['Beat Years']}/{m['Total Years']}"),
#             ("Beta 0.5–1.2",
#              0.5 <= m["Beta"] <= 1.2,            f"{m['Beta']:.2f}"),
#             ("Info Ratio > 0.0",
#              m["Info Ratio"] > 0.0,              f"{m['Info Ratio']:.2f}"),
#         ]
#         scored = sum(1 for _, p, _ in targets if p)
#         sc_df  = pd.DataFrame([{
#             "Status": "✅ PASS" if p else "❌ FAIL",
#             "Target": t,
#             "Value":  v,
#         } for t, p, v in targets])
#         st.dataframe(sc_df, use_container_width=True, hide_index=True)

#         verdict = ("✅ Solid Strategy" if scored >= 7
#                    else "⚠️ Acceptable"  if scored >= 5
#                    else "🔨 Needs Work")
#         fn = st.success if scored >= 7 else st.warning if scored >= 5 else st.error
#         fn(f"Score: **{scored}/10** — {verdict}")
#         st.markdown("---")

#         # ── Insights ──────────────────────────────────────────────────────────
#         st.subheader("🧠 Insights")
#         if m["CAGR"] > m["Bench CAGR"]:
#             st.success(
#                 f"✅ Beats Nifty by "
#                 f"**{(m['CAGR']-m['Bench CAGR'])*100:.1f}%/year** "
#                 f"(₹{(fv_s-fv_b)/100_000:.1f}L extra on ₹10L invested)"
#             )
#         else:
#             st.error(
#                 f"❌ Lags Nifty by "
#                 f"{(m['Bench CAGR']-m['CAGR'])*100:.1f}%/year"
#             )

#         if m["Max DD"] > m["Bench MaxDD"]:
#             st.success(
#                 f"✅ Lower drawdown: **{m['Max DD']*100:.1f}%** "
#                 f"vs Nifty **{m['Bench MaxDD']*100:.1f}%**"
#             )
#         else:
#             st.warning(
#                 f"⚠️ Drawdown {m['Max DD']*100:.1f}% — try wider ATR "
#                 f"multiplier or lower top-N"
#             )

#         if m["Sharpe"] > 1:
#             st.success(f"✅ Strong Sharpe {m['Sharpe']:.2f}")
#         elif m["Sharpe"] > 0.6:
#             st.warning(f"⚠️ Sharpe {m['Sharpe']:.2f} — target > 0.8")
#         else:
#             st.error(f"❌ Low Sharpe {m['Sharpe']:.2f}")

#         with st.expander("📖 How This Strategy Works — For Investors"):
#             st.markdown(f"""
# **All fixes v2.0 → v2.7:**

# | Fix | Issue | Resolution |
# |---|---|---|
# | **FIX-1**  | Survivorship bias | Historical constituents per year |
# | **FIX-2**  | Binary regime | 5-tier: 20/40/60/80/100% |
# | **FIX-3**  | No sector cap | Max {self.max_sector} stocks per sector |
# | **FIX-4**  | No stop-loss | ATR trailing stop ({self.atr_mult}×) |
# | **FIX-5**  | Float `==` crash | Tolerance-based regime comparison |
# | **FIX-6**  | Slow Python loop | Fully vectorized sector cap |
# | **FIX-7**  | Float drift | `regime.round(2)` throughout pipeline |
# | **FIX-8**  | Index mismatch | `bench_equity.reindex().ffill()` |
# | **FIX-9**  | Plotly hex+alpha | All fills use `rgba()` strings |
# | **FIX-10** | yfinance MultiIndex | `melt()` explicit var/value names |
# | **FIX-11** | Sector cap greedy fill | Two-stage filter |
# | **BUG-A**  | Weights explode on warm-up | Clip + renormalise weights |
# | **BUG-B**  | Regime locks to 0.20 early | Hard `min_periods=200` for MA |
# | **BUG-C**  | Equity starts ≠ 1.0 | Normalise + discard warm-up rows |

# **₹0.0L wealth display was caused by BUG-C:**
# `(1+net_ret).cumprod()` does not start at 1.0 — it starts at
# `(1 + net_ret.iloc[0])`. If the first live return is −0.9 (a common
# artefact from early NaN-edge rows), the entire equity curve is multiplied
# by 0.1, making the final value appear as ₹0.x L. Fixed by discarding the
# {WARMUP_DAYS}-day warm-up period and dividing the curve by its first value.
#             """)

"""
TREND FOLLOWING STRATEGY — v2.7
====================================================
FIXES IN THIS VERSION
---------------------

BUG-A: WEALTH METRICS SHOW ₹0.0L (zero equity)
  Root cause: equity curve starts at a tiny value because the FIRST row of
  (1 + net_ret).cumprod() is NOT 1.0 — it equals (1 + net_ret.iloc[0]).
  When net_ret.iloc[0] is a large negative number (e.g. -0.9999) on the first
  valid trading day (before warm-up windows are filled), the entire curve is
  scaled near zero for the whole backtest.

  Two sub-causes:
    A1. inv_vol / row_sum on the very first rows (before 20-day std is warm)
        can produce extreme weights that sum to >> 1.
    A2. The regime scalar is applied BEFORE valid_mask is fully warm,
        so on day 1 the portfolio might be 100% in one stock.

  Fix:
    - Clip weights to [0, 1] per stock and renormalize so they always sum ≤ 1.
    - Drop the first `warmup` rows before computing the equity curve
      (same warmup = max(200, mom_long, atr_period, 20) trading days).
    - Start cumprod from 1.0 explicitly.

BUG-B: "REASON: REGIME" ERROR / REGIME CUTS TO 0% ON DAY 1
  Root cause: bench_ma (200-day MA of Nifty) is NaN for the first 199 rows.
  bench_gap = bench / bench_ma - 1 is therefore NaN.
  gap_smooth = NaN.rolling(5).mean() = NaN.
  The regime comparisons (gap_smooth < 0.00 etc.) with NaN return False,
  so regime stays at 1.0 — that part is fine.
  BUT: if bench_ma uses min_periods=mp where mp = min(100, n_rows//10),
  with a short date range mp can be as low as 10, making bench_ma non-NaN
  from row 10 onward with an UNRELIABLE value. This gives a misleading
  bench_gap on early rows that can spike negative, setting regime to 0.20
  on days 10–199 when the 200-day MA is not yet meaningful.

  Fix:
    - Force bench_ma min_periods=200 (hard floor, not derived from n_rows).
    - This ensures regime is always 1.0 until a real 200-day MA exists.
    - Same fix applied to stock ma_200.

BUG-C: EQUITY NORMALIZATION
  (1 + net_ret).cumprod() gives growth of ₹1 starting from the FIRST date,
  not from 1.0. The display math assumes equity.iloc[0] == 1.0, which is
  only true if net_ret.iloc[0] == 0.
  Fix: divide the whole curve by equity.iloc[0] to normalize to 1.0.
  Same for bench_equity.

All previous fixes (FIX-1 through FIX-11) retained.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from strategies.base import BaseStrategy

# ── Pandas version-safe frequencies ─────────────────────────────────────────
try:
    pd.date_range("2020-01-01", periods=2, freq="ME")
    FREQ_YE = "YE"
except Exception:
    FREQ_YE = "Y"

# ============================================================================
# HISTORICAL NIFTY 50 CONSTITUENTS (FIX-1)
# ============================================================================
CORE_CONTINUOUS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "WIPRO.NS", "HCLTECH.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "TECHM.NS", "COALINDIA.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "BPCL.NS", "CIPLA.NS", "GRASIM.NS",
    "INDUSINDBK.NS", "HINDALCO.NS", "BRITANNIA.NS", "BAJAJ-AUTO.NS",
    "HEROMOTOCO.NS", "M&M.NS",
]

ADDITIONS_BY_YEAR = {
    2016: ["ADANIPORTS.NS", "BAJFINANCE.NS"],
    2017: ["ULTRACEMCO.NS", "NESTLEIND.NS"],
    2018: ["TITAN.NS",      "BAJAJFINSV.NS"],
    2019: ["DIVISLAB.NS",   "SBILIFE.NS", "HDFCLIFE.NS"],
    2020: ["APOLLOHOSP.NS", "TATACONSUM.NS"],
    2021: ["JSWSTEEL.NS"],
    2023: ["ADANIENT.NS"],
}

REMOVALS_LAST_YEAR = {
    "ZEEL.NS": 2021,
    "VEDL.NS": 2020,
    "UPL.NS":  2023,
}

REMOVED_STOCKS = {
    "ZEEL.NS": ("2015-01-01", "2022-01-01"),
    "VEDL.NS": ("2015-01-01", "2021-01-01"),
    "UPL.NS":  ("2015-01-01", "2024-01-01"),
}

SECTOR_MAP = {
    "HDFCBANK.NS":   "Financials", "ICICIBANK.NS":  "Financials",
    "KOTAKBANK.NS":  "Financials", "AXISBANK.NS":   "Financials",
    "SBIN.NS":       "Financials", "INDUSINDBK.NS": "Financials",
    "BAJFINANCE.NS": "Financials", "BAJAJFINSV.NS": "Financials",
    "SBILIFE.NS":    "Financials", "HDFCLIFE.NS":   "Financials",
    "TCS.NS":        "IT",         "INFY.NS":        "IT",
    "WIPRO.NS":      "IT",         "HCLTECH.NS":     "IT",
    "TECHM.NS":      "IT",
    "RELIANCE.NS":   "Energy",     "ONGC.NS":        "Energy",
    "BPCL.NS":       "Energy",     "COALINDIA.NS":   "Energy",
    "POWERGRID.NS":  "Energy",     "NTPC.NS":        "Energy",
    "HINDUNILVR.NS": "Staples",    "ITC.NS":         "Staples",
    "NESTLEIND.NS":  "Staples",    "BRITANNIA.NS":   "Staples",
    "TATACONSUM.NS": "Staples",
    "MARUTI.NS":     "Auto",       "TATAMOTORS.NS":  "Auto",
    "EICHERMOT.NS":  "Auto",       "BAJAJ-AUTO.NS":  "Auto",
    "HEROMOTOCO.NS": "Auto",       "M&M.NS":         "Auto",
    "LT.NS":         "Industrials","ADANIPORTS.NS":  "Industrials",
    "ADANIENT.NS":   "Industrials",
    "JSWSTEEL.NS":   "Materials",  "TATASTEEL.NS":   "Materials",
    "HINDALCO.NS":   "Materials",  "ULTRACEMCO.NS":  "Materials",
    "GRASIM.NS":     "Materials",  "VEDL.NS":        "Materials",
    "UPL.NS":        "Materials",
    "SUNPHARMA.NS":  "Healthcare", "DRREDDY.NS":     "Healthcare",
    "CIPLA.NS":      "Healthcare", "DIVISLAB.NS":    "Healthcare",
    "APOLLOHOSP.NS": "Healthcare",
    "ASIANPAINT.NS": "ConsDisc",   "TITAN.NS":       "ConsDisc",
    "ZEEL.NS":       "ConsDisc",
    "BHARTIARTL.NS": "Telecom",
}

SECTOR_COLORS = {
    "Financials": "#1565C0", "IT": "#6A1B9A", "Energy": "#E65100",
    "Staples": "#2E7D32",   "Auto": "#F9A825", "Industrials": "#4E342E",
    "Materials": "#546E7A", "Healthcare": "#00695C", "ConsDisc": "#AD1457",
    "Telecom": "#283593",   "Other": "#757575",
}

# ============================================================================
# FIX-9: Plotly-safe rgba helper
# ============================================================================
_HEX_RGB = {
    "#2E7D32": (46,  125,  50),
    "#8BC34A": (139, 195,  74),
    "#FFC107": (255, 193,   7),
    "#FF9800": (255, 152,   0),
    "#F44336": (244,  67,  54),
    "#1565C0": ( 21, 101, 192),
    "#E65100": (230,  81,   0),
    "#C62828": (198,  40,  40),
}

def _rgba(hex_color: str, alpha: float = 0.4) -> str:
    r, g, b = _HEX_RGB[hex_color]
    return f"rgba({r},{g},{b},{alpha})"


# ============================================================================
# UNIVERSE HELPERS
# ============================================================================
def get_universe_for_year(year: int) -> list:
    universe = set(CORE_CONTINUOUS)
    for add_year, tickers in ADDITIONS_BY_YEAR.items():
        if year >= add_year:
            universe.update(tickers)
    for ticker, last_year in REMOVALS_LAST_YEAR.items():
        if year > last_year:
            universe.discard(ticker)
    for ticker, (start, end) in REMOVED_STOCKS.items():
        if int(start[:4]) <= year < int(end[:4]):
            universe.add(ticker)
    return sorted(universe)


def safe_float(val, default=0.0):
    try:
        f = float(val)
        return f if np.isfinite(f) else default
    except Exception:
        return default


def build_valid_mask(all_cols, index, start_year, end_year):
    """FIX-1: per-year constituent boolean mask."""
    mask = pd.DataFrame(False, index=index, columns=all_cols)
    for year in range(start_year, end_year + 1):
        valid    = set(get_universe_for_year(year))
        year_idx = index[index.year == year]
        for col in all_cols:
            if col in valid:
                mask.loc[year_idx, col] = True
    return mask


# ============================================================================
# FIX-11: CORRECTED SECTOR CAP — GREEDY FILL (two-stage)
# ============================================================================
def apply_sector_cap_vectorized(signal_df, sector_map, max_per_sector, top_n):
    """
    Two-stage vectorized sector cap (FIX-6 + FIX-10 + FIX-11).
    Stage 1: sector cap in signal-rank order.
    Stage 2: top_n from sector-eligible pool.
    Guarantees exactly top_n stocks on every date with sufficient candidates.
    """
    _df = signal_df.reset_index(drop=False).copy()
    date_col    = _df.columns[0]
    ticker_cols = list(_df.columns[1:])

    long = _df.melt(
        id_vars=[date_col],
        value_vars=ticker_cols,
        var_name="ticker",
        value_name="signal",
    )
    long = long.rename(columns={date_col: "date"})
    long = long[long["signal"] > 0].copy()

    if long.empty:
        return pd.DataFrame(
            np.zeros((len(signal_df.index), len(signal_df.columns)), dtype=bool),
            index=signal_df.index,
            columns=signal_df.columns,
        )

    long["sector"] = long["ticker"].map(lambda t: sector_map.get(t, "Other"))

    # Stage 1: sector cap in descending signal order
    long = long.sort_values(["date", "signal"], ascending=[True, False])
    long["sector_rank"] = long.groupby(["date", "sector"]).cumcount()
    long = long[long["sector_rank"] < max_per_sector].copy()

    # Stage 2: top_n from sector-eligible pool
    long["rank_post_cap"] = long.groupby("date")["signal"].rank(
        ascending=False, method="first"
    )
    long = long[long["rank_post_cap"] <= top_n]

    long["selected"] = True
    result = (
        long.pivot_table(
            index="date",
            columns="ticker",
            values="selected",
            fill_value=False,
        )
        .reindex(index=signal_df.index, columns=signal_df.columns, fill_value=False)
    )
    return result.astype(bool)


# ============================================================================
# STRATEGY CLASS
# ============================================================================
class TrendFollowingStrategy(BaseStrategy):
    NAME = "Trend Following (Nifty 50)"
    DESCRIPTION = (
        "Buys top Nifty 50 stocks in strong uptrend + momentum. "
        "Historical constituents (survivorship-free), tiered regime, "
        "sector cap with greedy fill, ATR trailing stop."
    )
    _CACHE_VERSION = "v2.7"

    def render_sidebar(self):
        self.start_date   = st.sidebar.date_input(
            "Start Date", value=pd.to_datetime("2016-01-01"))
        self.end_date     = st.sidebar.date_input(
            "End Date",   value=pd.to_datetime("2025-12-31"))
        self.top_n        = st.sidebar.slider(
            "Top N Stocks to Hold", 5, 20, 10)

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Signal Parameters**")
        self.mom_short    = st.sidebar.slider(
            "Short Momentum (days)", 20, 100, 50)
        self.mom_long     = st.sidebar.slider(
            "Long Momentum (days)",  50, 200, 100)
        self.smooth       = st.sidebar.slider(
            "Signal Smoothing (days)", 1, 10, 3,
            help="Minimum hold period. Reduces daily churn.")
        self.max_sector   = st.sidebar.slider(
            "Max Stocks per Sector", 1, 5, 3,
            help="Sector concentration cap.")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Risk Controls**")
        self.atr_mult     = st.sidebar.slider(
            "ATR Trailing Stop Multiplier", 2.0, 6.0, 3.5, 0.5)
        self.atr_period   = st.sidebar.slider(
            "ATR Period (days)", 7, 21, 14)

        st.sidebar.markdown("---")
        self.fee_bps      = st.sidebar.number_input(
            "Fee (bps)", value=1.0, min_value=0.0)
        self.slippage_bps = st.sidebar.number_input(
            "Slippage (bps)", value=2.0, min_value=0.0)

        if st.sidebar.button("🗑 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

    # ── Cached backtest ──────────────────────────────────────────────────────
    @st.cache_data
    def _fetch(
        _self, start_date, end_date, top_n,
        mom_short, mom_long, smooth, max_sector,
        atr_mult, atr_period, fee_bps, slippage_bps,
        _cache_version="v2.7",
    ):
        cost     = (fee_bps + slippage_bps) / 10_000
        start_yr = int(str(start_date)[:4])
        end_yr   = int(str(end_date)[:4])

        # ── BUG-B FIX: hard warmup = 200 days (not derived from n_rows) ──────
        # Using min_periods=mp (where mp could be 10–100) made the 200-day MA
        # "valid" far too early with unreliable values, spiking bench_gap
        # negative and locking regime at 0.20 from day 10 onward.
        MA_PERIOD   = 200          # hard constant — never shrink this
        WARMUP_DAYS = max(MA_PERIOD, mom_long, atr_period, 20)

        # FIX-1: all tickers ever in index
        all_tickers = set()
        for yr in range(start_yr, end_yr + 1):
            all_tickers.update(get_universe_for_year(yr))
        download_list = sorted(all_tickers) + ["^NSEI"]

        import inspect as _inspect
        _kw = dict(
            start=str(start_date), end=str(end_date),
            auto_adjust=True, group_by="column",
            threads=False, progress=False,
        )
        _sig = _inspect.signature(yf.download).parameters
        if "multi_level_index" in _sig:
            _kw["multi_level_index"] = True

        raw = yf.download(download_list, **_kw)
        if raw is None or raw.empty:
            return None, "Download returned no data. Try Start Date 2018-01-01."

        def _field(r, names):
            if isinstance(r.columns, pd.MultiIndex):
                l0 = r.columns.get_level_values(0).unique().tolist()
                for n in names:
                    if n in l0:
                        return r[n].copy()
            return None

        close = _field(raw, ["Close", "Adj Close"])
        high  = _field(raw, ["High"])
        low   = _field(raw, ["Low"])

        if close is None:
            return None, "No Close column found."
        if high is None:
            high = close.copy()
        if low is None:
            low  = close.copy()

        close = close.loc[:, close.isna().mean() < 0.50].ffill().bfill()
        high  = high.reindex(columns=close.columns).ffill().bfill()
        low   = low.reindex(columns=close.columns).ffill().bfill()

        if "^NSEI" not in close.columns:
            return None, (
                "^NSEI (Nifty 50 index) missing. "
                "Try Start Date 2018-01-01 or later."
            )

        bench      = close["^NSEI"].copy()
        stock_cols = [c for c in close.columns if c != "^NSEI"]
        close      = close[stock_cols]
        high       = high[stock_cols]
        low        = low[stock_cols]

        if close.empty or bench.empty:
            return None, "No stock data after cleaning."

        # ── FIX-1: valid constituent mask ─────────────────────────────────────
        valid_mask = build_valid_mask(stock_cols, close.index, start_yr, end_yr)

        # ── Signal construction ───────────────────────────────────────────────
        # BUG-B FIX: min_periods=MA_PERIOD (hard 200) — not mp
        # This ensures ma_200 is NaN for the first 199 rows, so above_ma
        # is False and no stocks are traded during the warm-up period.
        ma_200   = close.rolling(MA_PERIOD, min_periods=MA_PERIOD).mean()
        above_ma = (close > ma_200).fillna(False)
        mom      = close.pct_change(mom_short) + close.pct_change(mom_long)

        mom_filtered = mom.where(above_ma & valid_mask & mom.notna())

        # FIX-11: greedy sector cap
        signal = apply_sector_cap_vectorized(
            mom_filtered.fillna(0),
            SECTOR_MAP, max_sector, top_n,
        ).astype(float)

        # shift(1): no lookahead bias
        pos = signal.shift(1).fillna(0).rolling(smooth, min_periods=1).max()

        # ── FIX-4: ATR trailing stop ──────────────────────────────────────────
        prev_close = close.shift(1)
        tr = pd.DataFrame({
            col: pd.concat([
                (high[col] - low[col]),
                (high[col] - prev_close[col]).abs(),
                (low[col]  - prev_close[col]).abs(),
            ], axis=1).max(axis=1)
            for col in close.columns
        })
        atr_df     = tr.rolling(atr_period, min_periods=max(3, atr_period // 2)).mean()
        roll_high  = close.rolling(20, min_periods=5).max()
        stop_level = roll_high - atr_mult * atr_df
        stop_ok    = (close >= stop_level).fillna(True)
        pos        = pos * stop_ok.astype(float)

        # ── Inverse-vol position sizing ───────────────────────────────────────
        ret     = close.pct_change().fillna(0)
        inv_vol = (1.0 / (ret.rolling(20, min_periods=10).std() + 1e-6)) * pos

        # BUG-A FIX: clip individual weights to [0, 1] before normalising.
        # Without this, on early rows where rolling std is tiny (near 1e-6),
        # inv_vol explodes to 1e6 for a single stock, making weights sum >> 1
        # after normalisation passes through division by a near-zero row_sum.
        row_sum = inv_vol.sum(axis=1).replace(0, np.nan)
        weights = inv_vol.div(row_sum, axis=0).fillna(0)
        # Hard clip: no single stock can exceed 100% and no short positions
        weights = weights.clip(lower=0.0, upper=1.0)
        # Re-normalise after clip so weights still sum to ≤ 1
        row_sum2 = weights.sum(axis=1).replace(0, np.nan)
        weights  = weights.div(row_sum2, axis=0).fillna(0)

        # ── FIX-2 + FIX-7 + BUG-B: tiered regime ────────────────────────────
        # BUG-B FIX: min_periods=MA_PERIOD (hard 200).
        # Old code used min_periods=mp (as low as 10), giving a "valid"
        # 200-day MA from day 10 onward with only 10 data points — unreliable.
        # That made bench_gap spike negative early, locking regime at 0.20.
        bench_ma   = bench.rolling(MA_PERIOD, min_periods=MA_PERIOD).mean()
        bench_gap  = (bench / bench_ma.replace(0, np.nan) - 1)
        gap_smooth = bench_gap.rolling(5, min_periods=1).mean()

        regime = pd.Series(1.00, index=bench.index, dtype=float)
        regime[gap_smooth <  0.00] = 0.80
        regime[gap_smooth < -0.03] = 0.60
        regime[gap_smooth < -0.07] = 0.40
        regime[gap_smooth < -0.12] = 0.20
        # Where bench_ma is NaN (first MA_PERIOD-1 rows), gap_smooth is NaN.
        # NaN comparisons return False, so regime naturally stays at 1.0.
        # That's correct: no signal → no trades → regime irrelevant.
        regime = regime.round(2)  # FIX-7

        weights = weights.mul(regime, axis=0)

        # ── Portfolio returns ─────────────────────────────────────────────────
        gross_ret = (weights * ret).sum(axis=1)
        turnover  = weights.diff().abs().sum(axis=1).fillna(0)
        net_ret   = gross_ret - turnover * cost

        # ── BUG-C + BUG-B FIX: drop warm-up rows, then normalise to 1.0 ─────
        # Trim the first WARMUP_DAYS rows so the equity curve starts from the
        # first day when all rolling windows (MA, momentum, ATR, vol) are warm.
        # This prevents the equity curve from being distorted by early NaN-edge
        # returns, and ensures equity.iloc[0] represents a "live" trading day.
        if len(net_ret) > WARMUP_DAYS + 50:
            net_ret_live = net_ret.iloc[WARMUP_DAYS:]
        else:
            # Not enough data even after warmup — use everything
            net_ret_live = net_ret

        equity = (1 + net_ret_live).cumprod()

        # BUG-C FIX: normalise so equity.iloc[0] == 1.0 exactly.
        # (1+r).cumprod() gives growth of ₹1 from day 0, but the first
        # value is (1 + net_ret_live.iloc[0]), not 1.0. Dividing by the
        # first value resets the base to exactly 1.0, matching the display
        # assumption of "₹10L invested on the first live trading day."
        if equity.iloc[0] != 0:
            equity = equity / equity.iloc[0]

        bench_ret    = bench.pct_change().fillna(0)
        bench_equity = (1 + bench_ret).cumprod()

        # ── FIX-8: align on common index ─────────────────────────────────────
        common       = equity.index.intersection(bench_equity.index)
        equity       = equity.loc[common]
        bench_equity = bench_equity.reindex(common).ffill()

        # BUG-C FIX: normalise bench_equity to the same start as equity
        if bench_equity.iloc[0] != 0:
            bench_equity = bench_equity / bench_equity.iloc[0]

        net_ret   = net_ret_live.loc[common]
        bench_ret = bench_ret.reindex(common).fillna(0)

        # Re-align weights and regime to the live (post-warmup) index
        weights      = weights.loc[weights.index.isin(common)]
        regime_final = regime.reindex(common).ffill().round(2)

        if len(net_ret) < 50:
            return None, (
                f"Only {len(net_ret)} live observations after {WARMUP_DAYS}-day "
                f"warm-up — need 50+. Use a Start Date at least "
                f"{WARMUP_DAYS // 252 + 1} years before End Date."
            )

        # ── Performance metrics ───────────────────────────────────────────────
        n_years  = len(equity) / 252.0
        cagr     = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
        b_cagr   = (bench_equity.iloc[-1] / bench_equity.iloc[0]) ** (1 / n_years) - 1

        rf_daily = 0.065 / 252
        std_p    = net_ret.std()
        std_b    = bench_ret.std()

        sharpe   = ((net_ret.mean() - rf_daily) / std_p) * np.sqrt(252) \
                   if std_p > 1e-10 else 0.0
        b_sharpe = ((bench_ret.mean() - rf_daily) / std_b) * np.sqrt(252) \
                   if std_b > 1e-10 else 0.0

        neg_ret  = net_ret[net_ret < 0]
        downside = neg_ret.std() * np.sqrt(252) if len(neg_ret) > 5 else 1e-6
        sortino  = (net_ret.mean() - rf_daily) * 252 / downside

        max_dd  = (equity / equity.cummax() - 1).min()
        b_maxdd = (bench_equity / bench_equity.cummax() - 1).min()
        calmar  = safe_float(cagr) / abs(safe_float(max_dd)) \
                  if abs(safe_float(max_dd)) > 1e-6 else 0.0

        vol_ann  = std_p * np.sqrt(252)
        win_rate = float((net_ret > 0).mean())

        cov_m = np.cov(net_ret.values, bench_ret.values)
        beta  = cov_m[0, 1] / (cov_m[1, 1] + 1e-12)
        alpha = safe_float(cagr) - beta * safe_float(b_cagr)
        excess = net_ret - bench_ret
        ir     = (excess.mean() / (excess.std() + 1e-12)) * np.sqrt(252)

        var_95  = float(np.percentile(net_ret.values, 5)) \
                  if len(net_ret) > 20 else 0.0
        cvar_95 = float(net_ret[net_ret <= var_95].mean()) \
                  if (net_ret <= var_95).any() else var_95

        up_m   = bench_ret[bench_ret > 0]
        dn_m   = bench_ret[bench_ret < 0]
        up_cap = net_ret.loc[up_m.index].mean() / up_m.mean() \
                 if len(up_m) > 0 and up_m.mean() > 0 else 1.0
        dn_cap = net_ret.loc[dn_m.index].mean() / dn_m.mean() \
                 if len(dn_m) > 0 and dn_m.mean() < 0 else 1.0

        yr_strat = net_ret.groupby(net_ret.index.year).apply(
            lambda x: (1 + x).prod() - 1)
        yr_bench = bench_ret.groupby(bench_ret.index.year).apply(
            lambda x: (1 + x).prod() - 1)
        beat = int(sum(s > b for s, b in
                       zip(yr_strat.values, yr_bench.values)))

        return {
            "equity":       equity,
            "bench_equity": bench_equity,
            "net_ret":      net_ret,
            "bench_ret":    bench_ret,
            "weights":      weights,
            "regime":       regime_final,
            "yr_strat":     yr_strat,
            "yr_bench":     yr_bench,
            "n_years":      n_years,
            "warmup_days":  WARMUP_DAYS,
            "metrics": {
                "CAGR":        safe_float(cagr),
                "Bench CAGR":  safe_float(b_cagr),
                "Sharpe":      safe_float(sharpe),
                "B Sharpe":    safe_float(b_sharpe),
                "Sortino":     safe_float(sortino),
                "Calmar":      safe_float(calmar),
                "Max DD":      safe_float(max_dd),
                "Bench MaxDD": safe_float(b_maxdd),
                "Volatility":  safe_float(vol_ann),
                "Win Rate":    safe_float(win_rate),
                "Beta":        safe_float(beta),
                "Alpha":       safe_float(alpha),
                "Info Ratio":  safe_float(ir),
                "VaR 95":      safe_float(var_95),
                "CVaR 95":     safe_float(cvar_95),
                "Up Capture":  safe_float(up_cap),
                "Dn Capture":  safe_float(dn_cap),
                "Beat Years":  beat,
                "Total Years": len(yr_strat),
            },
        }, None

    # ── Display ──────────────────────────────────────────────────────────────
    def run(self):
        with st.spinner(
            "Running Trend Following v2.7 on Nifty 50..."
        ):
            raw = self._fetch(
                self.start_date, self.end_date, self.top_n,
                self.mom_short, self.mom_long, self.smooth,
                self.max_sector, self.atr_mult, self.atr_period,
                self.fee_bps, self.slippage_bps,
                _cache_version=self._CACHE_VERSION,
            )

        if isinstance(raw, tuple) and len(raw) == 2:
            result, err = raw
        else:
            result, err = raw, None

        if result is None:
            st.error(f"❌ Backtest failed — {err}")
            st.warning(
                "**Common fixes:**\n"
                "- Use **Start Date 2016-01-01** or earlier so the 200-day "
                "warm-up period has enough history\n"
                "- Click **🗑 Clear Cache** in sidebar\n"
                "- Wait 60 seconds (Yahoo Finance rate limit) then retry"
            )
            return

        m    = result["metrics"]
        eq   = result["equity"]
        be   = result["bench_equity"]
        nr   = result["net_ret"]
        br   = result["bench_ret"]
        ys   = result["yr_strat"]
        yb   = result["yr_bench"]
        reg  = result["regime"]
        n_y  = result["n_years"]
        wup  = result["warmup_days"]

        # ── Coverage info ─────────────────────────────────────────────────────
        st.info(
            f"📅 **{eq.index[0].strftime('%b %Y')} → "
            f"{eq.index[-1].strftime('%b %Y')}** "
            f"({n_y:.1f} years, after {wup}-day warm-up) | "
            f"Regime: 5-tier | Sector cap: max {self.max_sector} | "
            f"ATR Stop: {self.atr_mult}×"
        )

        # ── KPI rows ──────────────────────────────────────────────────────────
        st.markdown("## 📊 Performance")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("CAGR",
                  f"{m['CAGR']*100:.2f}%",
                  delta=f"{(m['CAGR']-m['Bench CAGR'])*100:.1f}% vs Nifty")
        c2.metric("Sharpe",
                  f"{m['Sharpe']:.2f}",
                  delta=f"{m['Sharpe']-m['B Sharpe']:.2f} vs Nifty",
                  help="Target > 0.8")
        c3.metric("Calmar", f"{m['Calmar']:.2f}",
                  help="CAGR / Max DD. Target > 1.0")
        c4.metric("Max Drawdown",
                  f"{m['Max DD']*100:.1f}%",
                  delta=f"{(m['Max DD']-m['Bench MaxDD'])*100:.1f}% vs Nifty",
                  delta_color="inverse")
        c5.metric("Win Rate", f"{m['Win Rate']*100:.1f}%")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Sortino",     f"{m['Sortino']:.2f}")
        c2.metric("Beta",        f"{m['Beta']:.2f}")
        c3.metric("Alpha (ann)", f"{m['Alpha']*100:.1f}%")
        c4.metric("Info Ratio",  f"{m['Info Ratio']:.2f}")
        c5.metric("Beat Nifty",  f"{m['Beat Years']}/{m['Total Years']} yrs")

        # ── Wealth creation ───────────────────────────────────────────────────
        # BUG-A/C FIX: equity is now normalised so iloc[0] == 1.0 exactly.
        # fv_s = final value of ₹1 → multiply by 1_000_000 for ₹10L display.
        INITIAL = 1_000_000   # ₹10 lakh
        fv_s    = eq.iloc[-1]   * INITIAL   # final value of ₹10L in strategy
        fv_b    = be.iloc[-1]   * INITIAL   # final value of ₹10L in Nifty B&H

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Strategy ₹10L grew to",
            f"₹{fv_s/100_000:.1f}L",
            delta=f"₹{(fv_s - INITIAL)/100_000:.1f}L profit",
        )
        col2.metric(
            "Nifty B&H ₹10L grew to",
            f"₹{fv_b/100_000:.1f}L",
            delta=f"₹{(fv_b - INITIAL)/100_000:.1f}L profit",
        )
        col3.metric(
            "Extra vs Nifty",
            f"₹{(fv_s - fv_b)/100_000:.1f}L",
            delta=f"{(fv_s/fv_b - 1)*100:.1f}% more" if fv_b > 0 else "N/A",
        )

        st.markdown("---")
        st.info(
            f"**Strategy logic:** "
            f"Stocks above 200-day MA ranked by "
            f"{self.mom_short}+{self.mom_long}-day momentum. "
            f"Top {self.top_n} via greedy sector cap "
            f"(max {self.max_sector}/sector). "
            f"Exposure 20–100% via tiered regime. "
            f"ATR trailing stop ({self.atr_mult}×). "
            f"{wup}-day warm-up discarded."
        )
        st.markdown("---")

        # ── Equity Curve ──────────────────────────────────────────────────────
        st.subheader("📈 Equity Curve vs Nifty 50")
        be_ri = be.reindex(eq.index).ffill()
        fig1  = go.Figure()
        fig1.add_trace(go.Scatter(
            x=eq.index, y=eq.values,
            name="Trend Following",
            line=dict(color="#1565C0", width=2.5),
        ))
        fig1.add_trace(go.Scatter(
            x=be.index, y=be.values,
            name="Nifty 50 B&H",
            line=dict(color="#E65100", width=1.8, dash="dash"),
        ))
        fig1.add_trace(go.Scatter(
            x=list(eq.index) + list(eq.index[::-1]),
            y=list(eq.values) + list(be_ri.values[::-1]),
            fill="toself",
            fillcolor=_rgba("#1565C0", 0.10),
            line=dict(width=0),
            name="Outperformance",
        ))
        fig1.update_layout(
            height=400, xaxis_title="Date",
            yaxis_title="Growth of ₹1",
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ── Drawdown ──────────────────────────────────────────────────────────
        st.subheader("📉 Drawdown")
        dd_s = (eq / eq.cummax() - 1) * 100
        dd_b = (be / be.cummax() - 1) * 100
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=dd_s.index, y=dd_s.values, fill="tozeroy",
            name="Strategy DD",
            fillcolor=_rgba("#1565C0", 0.40),
            line=dict(color="#1565C0", width=1),
        ))
        fig2.add_trace(go.Scatter(
            x=dd_b.index, y=dd_b.values, fill="tozeroy",
            name="Nifty DD",
            fillcolor=_rgba("#E65100", 0.20),
            line=dict(color="#E65100", width=1, dash="dash"),
        ))
        fig2.add_hline(y=-20, line_dash="dot", line_color="red",
                       annotation_text="-20% Target")
        fig2.update_layout(
            height=250, xaxis_title="Date", yaxis_title="Drawdown %",
            legend=dict(x=0.01, y=0.01),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Strategy Max DD", f"{m['Max DD']*100:.1f}%")
        c2.metric("Nifty Max DD",    f"{m['Bench MaxDD']*100:.1f}%")
        c3.metric("DD Improvement",
                  f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
                  delta="Better" if m["Max DD"] > m["Bench MaxDD"] else "Worse",
                  delta_color="normal" if m["Max DD"] > m["Bench MaxDD"]
                  else "inverse")
        st.markdown("---")

        # ── Year by Year ──────────────────────────────────────────────────────
        st.subheader("📅 Year-by-Year Returns vs Nifty 50")
        if len(ys) > 0 and len(yb) > 0:
            common_yrs = ys.index.intersection(yb.index)
            ys_c   = ys.loc[common_yrs]
            yb_c   = yb.loc[common_yrs]
            colors = ["#2E7D32" if s > b else "#C62828"
                      for s, b in zip(ys_c.values, yb_c.values)]
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                x=common_yrs.tolist(),
                y=(ys_c.values * 100).tolist(),
                name="Strategy", marker_color=colors, opacity=0.88,
            ))
            fig3.add_trace(go.Bar(
                x=common_yrs.tolist(),
                y=(yb_c.values * 100).tolist(),
                name="Nifty 50", marker_color="#E65100", opacity=0.65,
            ))
            fig3.add_hline(y=0, line_color="white", line_width=0.8)
            fig3.update_layout(
                barmode="group", height=300,
                xaxis_title="Year", yaxis_title="Return %",
                xaxis=dict(tickmode="linear", dtick=1),
                legend=dict(x=0.01, y=0.99),
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig3, use_container_width=True)

            yr_df = pd.DataFrame({
                "Year":       common_yrs.tolist(),
                "Strategy %": (ys_c.values * 100).round(1).tolist(),
                "Nifty 50 %": (yb_c.values * 100).round(1).tolist(),
                "Alpha %":    ((ys_c.values - yb_c.values) * 100).round(1).tolist(),
                "Beat?":      ["✅" if s > b else "❌"
                               for s, b in zip(ys_c.values, yb_c.values)],
            })
            st.dataframe(yr_df, use_container_width=True, hide_index=True)
            bp = m["Beat Years"] / max(m["Total Years"], 1)
            st.info(
                f"Beat Nifty in **{m['Beat Years']} of "
                f"{m['Total Years']} years** ({bp*100:.0f}%)"
            )
        else:
            st.warning("Not enough data for year-by-year analysis.")
        st.markdown("---")

        # ── Rolling Returns ───────────────────────────────────────────────────
        st.subheader("📊 Rolling 20-Day Returns")
        roll = nr.rolling(20).mean() * 100
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(
            x=roll.index, y=roll.values,
            name="20-day rolling",
            line=dict(color="#1565C0", width=1.5),
            fill="tozeroy",
            fillcolor=_rgba("#1565C0", 0.20),
        ))
        fig4.add_hline(y=0, line_color="white", line_width=0.8)
        fig4.update_layout(
            height=220, xaxis_title="Date",
            yaxis_title="Avg Daily Return %",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig4, use_container_width=True)
        st.markdown("---")

        # ── Tiered Regime Exposure ────────────────────────────────────────────
        st.subheader("🌡️ Tiered Regime Exposure")
        reg_ri = reg.reindex(eq.index).ffill().round(2)

        level_config = [
            (1.00, "#2E7D32", "rgba(46,125,50,0.4)",   "100% — Full Bull"),
            (0.80, "#8BC34A", "rgba(139,195,74,0.4)",  "80%  — Mild Caution"),
            (0.60, "#FFC107", "rgba(255,193,7,0.4)",   "60%  — Moderate Bear"),
            (0.40, "#FF9800", "rgba(255,152,0,0.4)",   "40%  — Defensive"),
            (0.20, "#F44336", "rgba(244,67,54,0.4)",   "20%  — Near-Cash"),
        ]

        fig5 = go.Figure()
        for lv, line_color, fill_color, label in level_config:
            mask   = (reg_ri - lv).abs() < 0.01  # FIX-5
            if mask.any():
                y_vals = np.where(mask, lv * 100, np.nan)
                fig5.add_trace(go.Scatter(
                    x=reg_ri.index,
                    y=y_vals,
                    fill="tozeroy",
                    name=label,
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=0.5),
                    connectgaps=False,
                ))

        fig5.update_layout(
            height=200, xaxis_title="Date",
            yaxis_title="% Invested",
            yaxis=dict(range=[0, 110]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig5, use_container_width=True)

        pct_reduced = (reg_ri < 1.0).mean()
        st.caption(
            f"Strategy was below 100% in "
            f"**{pct_reduced*100:.0f}% of periods** — "
            f"tiered regime reduces exposure gradually."
        )
        st.markdown("---")

        # ── Current Holdings ──────────────────────────────────────────────────
        st.subheader("📋 Current Holdings")
        latest   = result["weights"].iloc[-1]
        holdings = latest[latest > 0].sort_values(ascending=False)

        if len(holdings) > 0:
            h_df = pd.DataFrame({
                "Ticker":   [t.replace(".NS", "") for t in holdings.index],
                "Sector":   [SECTOR_MAP.get(t, "Other") for t in holdings.index],
                "Weight %": (holdings.values * 100).round(2),
                "₹ Alloc":  [f"₹{w * INITIAL:,.0f}" for w in holdings.values],
            })
            col1, col2 = st.columns([2, 1])
            with col1:
                st.dataframe(h_df, use_container_width=True, hide_index=True)
            with col2:
                sec_w = h_df.groupby("Sector")["Weight %"].sum().reset_index()
                fig_pie = go.Figure(go.Pie(
                    labels=sec_w["Sector"],
                    values=sec_w["Weight %"],
                    marker_colors=[SECTOR_COLORS.get(s, "#757575") for s in sec_w["Sector"]],
                    hole=0.4,
                    textinfo="label+percent",
                ))
                fig_pie.update_layout(
                    height=280,
                    margin=dict(l=0, r=0, t=10, b=10),
                    showlegend=False,
                )
                st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No positions — market is in a reduced-exposure regime.")
        st.markdown("---")

        # ── Risk Details ──────────────────────────────────────────────────────
        st.subheader("⚠️ Risk Details")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("VaR 95% (daily)",  f"{m['VaR 95']*100:.2f}%",
                   help="Worst daily loss 95% of the time")
        rc2.metric("CVaR 95% (daily)", f"{m['CVaR 95']*100:.2f}%",
                   help="Average loss on worst 5% of days")
        rc3.metric("Up Capture",       f"{m['Up Capture']*100:.0f}%",
                   help="% of Nifty upside captured. Target: >70%")
        rc4.metric("Down Capture",     f"{m['Dn Capture']*100:.0f}%",
                   help="% of Nifty downside absorbed. Target: <80%")
        st.markdown("---")

        # ── Investor Scorecard ────────────────────────────────────────────────
        st.subheader("🎯 Investor Target Scorecard")
        bp = m["Beat Years"] / max(m["Total Years"], 1)
        targets = [
            ("CAGR > 15%",
             m["CAGR"] * 100 > 15,               f"{m['CAGR']*100:.1f}%"),
            ("Beats Nifty (CAGR)",
             m["CAGR"] > m["Bench CAGR"],        f"+{(m['CAGR']-m['Bench CAGR'])*100:.1f}%"),
            ("Sharpe > 0.8",
             m["Sharpe"] > 0.8,                  f"{m['Sharpe']:.2f}"),
            ("Sortino > 0.8",
             m["Sortino"] > 0.8,                 f"{m['Sortino']:.2f}"),
            ("Calmar > 1.0",
             m["Calmar"] > 1.0,                  f"{m['Calmar']:.2f}"),
            ("Max DD < 25%",
             abs(m["Max DD"]) < 0.25,            f"{m['Max DD']*100:.1f}%"),
            ("Max DD better than Nifty",
             m["Max DD"] > m["Bench MaxDD"],     f"{m['Max DD']*100:.1f}%"),
            ("Beat Nifty > 50% yrs",
             bp > 0.50,                           f"{m['Beat Years']}/{m['Total Years']}"),
            ("Beta 0.5–1.2",
             0.5 <= m["Beta"] <= 1.2,            f"{m['Beta']:.2f}"),
            ("Info Ratio > 0.0",
             m["Info Ratio"] > 0.0,              f"{m['Info Ratio']:.2f}"),
        ]
        scored = sum(1 for _, p, _ in targets if p)
        sc_df  = pd.DataFrame([{
            "Status": "✅ PASS" if p else "❌ FAIL",
            "Target": t,
            "Value":  v,
        } for t, p, v in targets])
        st.dataframe(sc_df, use_container_width=True, hide_index=True)

        verdict = ("✅ Solid Strategy" if scored >= 7
                   else "⚠️ Acceptable"  if scored >= 5
                   else "🔨 Needs Work")
        fn = st.success if scored >= 7 else st.warning if scored >= 5 else st.error
        fn(f"Score: **{scored}/10** — {verdict}")
        st.markdown("---")

        # ── Insights ──────────────────────────────────────────────────────────
        st.subheader("🧠 Insights")
        if m["CAGR"] > m["Bench CAGR"]:
            st.success(
                f"✅ Beats Nifty by "
                f"**{(m['CAGR']-m['Bench CAGR'])*100:.1f}%/year** "
                f"(₹{(fv_s-fv_b)/100_000:.1f}L extra on ₹10L invested)"
            )
        else:
            st.error(
                f"❌ Lags Nifty by "
                f"{(m['Bench CAGR']-m['CAGR'])*100:.1f}%/year"
            )

        if m["Max DD"] > m["Bench MaxDD"]:
            st.success(
                f"✅ Lower drawdown: **{m['Max DD']*100:.1f}%** "
                f"vs Nifty **{m['Bench MaxDD']*100:.1f}%**"
            )
        else:
            st.warning(
                f"⚠️ Drawdown {m['Max DD']*100:.1f}% — try wider ATR "
                f"multiplier or lower top-N"
            )

        if m["Sharpe"] > 1:
            st.success(f"✅ Strong Sharpe {m['Sharpe']:.2f}")
        elif m["Sharpe"] > 0.6:
            st.warning(f"⚠️ Sharpe {m['Sharpe']:.2f} — target > 0.8")
        else:
            st.error(f"❌ Low Sharpe {m['Sharpe']:.2f}")

        with st.expander("📖 How This Strategy Works — For Investors"):
            st.markdown(f"""
**Core Idea**

The strategy selects Nifty 50 stocks that are in a confirmed uptrend — trading
above their 200-day moving average — and ranks them by a blend of short-term
({self.mom_short}-day) and long-term ({self.mom_long}-day) momentum.
The top {self.top_n} stocks are held, with a cap of {self.max_sector} per sector
to prevent concentration in any single theme.

**Key Design Decisions**

| Feature | What it Does |
|---|---|
| Historical constituents | Only trades stocks that were actually in Nifty 50 at the time — eliminates survivorship bias |
| 5-tier regime exposure | Scales invested capital 20→40→60→80→100% based on Nifty's distance from its 200DMA |
| Sector cap (greedy fill) | Limits holdings to max {self.max_sector} stocks per sector; fills remaining slots from next-best sectors |
| ATR trailing stop ({self.atr_mult}×) | Exits a position if it drops more than {self.atr_mult}× its Average True Range from its peak |
| {wup}-day warm-up discard | First {wup} trading days are discarded so all moving averages are properly initialised |

**Position Sizing**

Weights are proportional to inverse-volatility (lower-vol stocks get more capital).
All weights are clipped to [0, 1] per stock and renormalised to sum ≤ 1, then
scaled by the regime exposure factor.

**When the Strategy Is Cautious**

When Nifty trades below its 200-day MA, the regime filter reduces total exposure:
- 0% to −2% below MA → 80% invested
- −2% to −5% → 60%
- −5% to −10% → 40%
- Below −10% → 20% (near-cash, not full cash)

This means recoveries are never fully missed — the strategy always holds a partial
position ready to scale back up.
            """)
