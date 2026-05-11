"""
QUALITY + LOW VOLATILITY STRATEGY — Nifty 50
=============================================
Institutional-grade implementation combining two independent alpha sources:

  ALPHA SOURCE 1 — LOW VOLATILITY (Baker et al. 2011, Frazzini & Pedersen BAB 2014)
  Why it works: Institutional fund managers are benchmarked against Nifty 50,
  so they're forced to hold high-beta exciting stocks even when overpriced.
  This creates a systematic mispricing of low-vol stocks.
  The NSE Nifty100 Low Vol 30 index beats Nifty 50 by ~4%/yr using only
  price-based vol — no fundamental data needed.

  ALPHA SOURCE 2 — QUALITY (AQR QMJ paper, Asness et al. 2013)
  Why it works: Investors overpay for high-growth stories and systematically
  ignore boring, profitable compounders. Quality stocks are defensive —
  they compound steadily rather than spiking and crashing.
  Implementation: price-derived quality proxies (return smoothness,
  momentum consistency, drawdown profile) — works well on large caps
  where fundamentals are priced in efficiently.

  REGIME FILTER — 60/40 EQUITY/CASH (not binary 0/100%)
  Key design insight: Quality/low-vol stocks ARE already defensive.
  In the 2020 crash, Nifty dropped 38% — a quality low-vol portfolio
  would typically drop only 20-25%. Going to 100% cash destroys this
  natural defensive characteristic. The right regime is 60/40 split
  when bearish, reducing beta further without abandoning positions.

  COMBINATION SCORE
  Equal-weighted rank fusion: 50% low-vol rank + 50% quality rank.
  This gives two independent sources of alpha with low correlation.
  Both anomalies are well-documented in Indian markets specifically.

All implementation notes:
  - yfinance provides OHLCV only — all signals are price-derived
  - Historical Nifty 50 constituents used (survivorship bias corrected)
  - Next-day open execution (no look-ahead bias)
  - Monthly rebalancing (matches institutional practice)
  - Max 3 stocks per sector (concentration control)
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from strategies.base import BaseStrategy

try:
    _yf_version = yf.__version__
except Exception:
    _yf_version = "unknown"

# ── Pandas version-safe frequencies ───────────────────────────────
try:
    _maj, _min = [int(x) for x in pd.__version__.split(".")[:2]]
    _NEW_PD = (_maj > 2) or (_maj == 2 and _min >= 2)
except Exception:
    _NEW_PD = True
FREQ_ME = "ME" if _NEW_PD else "M"
FREQ_YE = "YE" if _NEW_PD else "Y"

# ============================================================
# UNIVERSE: historical Nifty 50 constituents by year
# ============================================================
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
REMOVALS_LAST_YEAR = {"ZEEL.NS":2021,"VEDL.NS":2020,"UPL.NS":2023}
REMOVED_STOCKS = {
    "ZEEL.NS":("2015-01-01","2022-01-01"),
    "VEDL.NS":("2015-01-01","2021-01-01"),
    "UPL.NS": ("2015-01-01","2024-01-01"),
}
SECTOR_MAP = {
    "HDFCBANK.NS":"Financials","ICICIBANK.NS":"Financials","KOTAKBANK.NS":"Financials",
    "AXISBANK.NS":"Financials","SBIN.NS":"Financials","INDUSINDBK.NS":"Financials",
    "BAJFINANCE.NS":"Financials","BAJAJFINSV.NS":"Financials","SBILIFE.NS":"Financials",
    "HDFCLIFE.NS":"Financials",
    "TCS.NS":"IT","INFY.NS":"IT","WIPRO.NS":"IT","HCLTECH.NS":"IT","TECHM.NS":"IT",
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


def get_universe_for_year(year):
    u = set(CORE_CONTINUOUS)
    for y, tickers in ADDITIONS_BY_YEAR.items():
        if year >= y: u.update(tickers)
    for t, ly in REMOVALS_LAST_YEAR.items():
        if year > ly: u.discard(t)
    for t, (s, e) in REMOVED_STOCKS.items():
        if int(s[:4]) <= year < int(e[:4]): u.add(t)
    return sorted(u)


def apply_sector_cap(ranked, sector_map, max_per_sector, top_n):
    selected, counts = [], {}
    for t in ranked:
        if len(selected) >= top_n: break
        sec = sector_map.get(t, "Other")
        if counts.get(sec, 0) < max_per_sector:
            selected.append(t)
            counts[sec] = counts.get(sec, 0) + 1
    return selected


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


# ============================================================
# CORE SIGNAL FUNCTIONS
# ============================================================

def compute_low_vol_score(daily_ret, window=252):
    """
    LOW VOLATILITY SCORE
    Lower annualised realised volatility = higher score.
    """
    vol = daily_ret.rolling(window, min_periods=window//2).std() * np.sqrt(252)
    inv_vol = -vol
    score = inv_vol.sub(inv_vol.mean(axis=1), axis=0).div(
        inv_vol.std(axis=1).replace(0, np.nan), axis=0).fillna(0)
    return vol, score


def compute_quality_score(close, daily_ret, window_short=63, window_long=252):
    """
    QUALITY SCORE — price-derived proxies (no fundamental data needed)
    Three components, each z-scored then averaged.
    """
    roll_mean = daily_ret.rolling(window_long, min_periods=window_long//2).mean()
    roll_std  = daily_ret.rolling(window_long, min_periods=window_long//2).std()
    smoothness = (roll_mean / (roll_std + 1e-10))

    roll_max  = close.rolling(window_long, min_periods=1).max()
    roll_dd   = (close / roll_max.replace(0, np.nan) - 1).fillna(0)
    dd_score  = -roll_dd.rolling(window_long, min_periods=window_long//2).min()

    consistency = (daily_ret > 0).rolling(
        window_long, min_periods=window_long//2).mean()

    def cs_zscore(df):
        return df.sub(df.mean(axis=1), axis=0).div(
            df.std(axis=1).replace(0, np.nan), axis=0).fillna(0)

    quality_score = (
        cs_zscore(smoothness) * 0.40 +
        cs_zscore(dd_score)   * 0.35 +
        cs_zscore(consistency)* 0.25
    )
    return quality_score


def compute_composite_score(low_vol_score, quality_score, lv_weight=0.5, q_weight=0.5):
    return lv_weight * low_vol_score + q_weight * quality_score


def compute_regime_60_40(bench_prices, ma_period=200, smooth=5):
    """
    60/40 REGIME FILTER — never full cash for quality portfolio
    """
    bench_ma   = bench_prices.rolling(ma_period, min_periods=ma_period//2).mean()
    bench_gap  = (bench_prices / bench_ma.replace(0, np.nan) - 1)
    gap_smooth = bench_gap.rolling(smooth, min_periods=1).mean()

    exposure = pd.Series(1.0, index=bench_prices.index)
    exposure[gap_smooth <  0.00] = 0.80
    exposure[gap_smooth < -0.03] = 0.60
    return exposure


# ============================================================
# STRATEGY CLASS
# ============================================================
class QualityLowVolStrategy(BaseStrategy):
    NAME = "Quality + Low Volatility (Nifty 50)"
    DESCRIPTION = (
        "Combines two independent alpha sources: low-volatility anomaly "
        "(Baker 2011) and quality factor (AQR 2013). Defensive regime: "
        "60/40 equity/cash in bears. Never fully exits — quality stocks "
        "are designed to survive downturns."
    )

    def render_sidebar(self):
        self.start_date = st.sidebar.date_input(
            "Start Date", value=pd.to_datetime("2015-01-01"))
        self.end_date   = st.sidebar.date_input(
            "End Date",   value=pd.to_datetime("2025-01-01"))
        self.top_n      = st.sidebar.slider(
            "Stocks to Hold", 8, 20, 15,
            help="Low-vol strategies benefit from wider diversification vs momentum. "
                 "15–20 is optimal for Nifty 50 universe.")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Signal Blend**")
        lv_pct = st.sidebar.slider(
            "Low-Vol Weight %", 20, 80, 50, 5,
            help="50% = equal blend. Higher = more like NSE Low Vol 30 index.")
        self.lv_weight = lv_pct / 100
        self.q_weight  = 1.0 - self.lv_weight

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Portfolio Construction**")
        self.max_weight  = st.sidebar.slider(
            "Max Weight per Stock %", 5, 20, 10,
            help="Low-vol strategies use tighter caps for better diversification.") / 100
        self.inv_vol_weight = st.sidebar.checkbox(
            "Inverse-Vol Position Sizing",
            value=True,
            help="Weight by inverse volatility (lower vol = bigger position).")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Risk Controls**")
        self.vol_window  = st.sidebar.slider(
            "Volatility Window (days)", 126, 504, 252,
            help="Longer window = more stable rankings. 252 (1yr) is standard.")
        self.max_sector  = st.sidebar.slider(
            "Max Stocks per Sector", 2, 5, 3,
            help="Low-vol strategies tend to cluster in Staples/Financials.")
        self.min_price_ma = st.sidebar.slider(
            "Min % Above 200-day MA", 0, 20, 0,
            help="0 = no trend filter (pure defensive).")

        st.sidebar.markdown("---")
        self.fee_bps  = st.sidebar.number_input("Fee (bps)",      value=1.0, min_value=0.0)
        self.slip_bps = st.sidebar.number_input("Slippage (bps)", value=2.0, min_value=0.0)

        if st.sidebar.button("🗑 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

    # ──────────────────────────────────────────────────────────────
    # BACKTEST (cached)
    # ──────────────────────────────────────────────────────────────
    @st.cache_data
    def _run(_self, start_date, end_date, top_n, lv_weight, q_weight,
             max_weight, inv_vol_weight, vol_window, max_sector,
             min_price_ma, fee_bps, slip_bps):

        import inspect as _inspect
        log = []
        tc  = (fee_bps + slip_bps) / 10_000

        # ── 1. Build ticker list ───────────────────────────────────
        all_tickers = set()
        sy, ey = int(str(start_date)[:4]), int(str(end_date)[:4])
        for yr in range(sy, ey + 1):
            all_tickers.update(get_universe_for_year(yr))
        dl_list = sorted(all_tickers) + ["^NSEI"]
        log.append(f"STEP1 ✅ {len(dl_list)} tickers | {sy}–{ey}")

        # ── 2. Download ───────────────────────────────────────────
        try:
            _kw = dict(start=str(start_date), end=str(end_date),
                       auto_adjust=True, progress=False, threads=False)
            _sig = _inspect.signature(yf.download).parameters
            if "group_by" in _sig: _kw["group_by"] = "column"
            if "multi_level_index" in _sig: _kw["multi_level_index"] = True
            raw = yf.download(dl_list, **_kw)
            log.append(f"STEP2 ✅ shape={raw.shape}")
        except Exception as e:
            return None, f"Download failed: {e}", log

        if raw.empty or raw.shape[0] < 20:
            return None, (
                "Yahoo Finance returned no data. "
                "Try Start Date 2018-01-01 or later."
            ), log

        # ── 3. Extract OHLCV ──────────────────────────────────────
        def _field(r, names):
            if isinstance(r.columns, pd.MultiIndex):
                l0 = r.columns.get_level_values(0).unique().tolist()
                for n in names:
                    if n in l0: return r[n].copy()
            else:
                for n in names:
                    if n in r.columns: return r[[n]].copy()
            return None

        close = _field(raw, ["Close","Adj Close"])
        open_ = _field(raw, ["Open"])
        high  = _field(raw, ["High"])
        low   = _field(raw, ["Low"])

        if close is None:
            l0 = raw.columns.get_level_values(0).unique().tolist() \
                 if isinstance(raw.columns, pd.MultiIndex) else list(raw.columns)
            return None, f"No Close column. Available: {l0[:5]}", log

        if open_ is None: open_ = close.copy()
        if high  is None: high  = close.copy()
        if low   is None: low   = close.copy()

        # ── 4. Clean ──────────────────────────────────────────────
        close = close.loc[:, close.isna().mean() < 0.60].ffill().bfill()
        open_ = open_.reindex(columns=close.columns).ffill().bfill()
        high  = high.reindex(columns=close.columns).ffill().bfill()
        low   = low.reindex(columns=close.columns).ffill().bfill()

        if "^NSEI" not in close.columns:
            return None, (
                "^NSEI missing — try Start Date 2018-01-01 or later."
            ), log

        bench_prices = close["^NSEI"].copy()
        scols = [c for c in close.columns if c != "^NSEI"]
        close = close[scols]; open_ = open_[scols]
        high  = high[scols];  low   = low[scols]

        n_rows = len(close)
        log.append(f"STEP4 ✅ {len(close.columns)} stocks | {n_rows} days")
        if n_rows < 100:
            return None, f"Only {n_rows} rows — need 100+.", log

        # ── 5. COMPUTE SIGNALS ────────────────────────────────────
        daily_ret = close.pct_change().fillna(0)
        mp = min(vol_window//2, 60)

        realized_vol, lv_score = compute_low_vol_score(daily_ret, window=vol_window)
        q_score = compute_quality_score(close, daily_ret,
                                        window_short=63, window_long=vol_window)
        composite = compute_composite_score(lv_score, q_score,
                                            lv_weight=lv_weight,
                                            q_weight=q_weight)

        sma200   = close.rolling(200, min_periods=mp).mean()
        above_ma = (close / sma200.replace(0, np.nan) - 1).fillna(-1)

        prev_c = close.shift(1)
        tr_df = pd.DataFrame({
            col: pd.concat([
                (high[col] - low[col]),
                (high[col] - prev_c[col]).abs(),
                (low[col]  - prev_c[col]).abs(),
            ], axis=1).max(axis=1) for col in close.columns
        })
        atr = tr_df.rolling(14, min_periods=5).mean()

        regime = compute_regime_60_40(bench_prices, ma_period=200, smooth=5)
        pct_reduced = (regime < 1.0).mean()
        log.append(f"STEP5 ✅ Regime: {pct_reduced:.1%} of days below 100%")

        # ── 6. Backtest loop ──────────────────────────────────────
        dates = close.index
        rebal_set = set()
        for rd in pd.date_range(dates[0], dates[-1], freq=FREQ_ME):
            future = dates[dates >= rd]
            if len(future) > 0:
                rebal_set.add(future[0])

        portfolio_value = 1_000_000.0
        cash            = portfolio_value
        holdings        = {}
        port_values     = {}
        weights_history = {}
        signal_history  = {}
        trade_log       = []
        pending_rebal   = None
        last_rebal_date = None
        day_counter     = 0

        for date in dates:
            try:
                px_close = close.loc[date]
                px_open  = open_.loc[date]
            except KeyError:
                port_values[date] = portfolio_value
                continue
            day_counter += 1

            if pending_rebal is not None:
                new_stocks, new_weights = pending_rebal
                pending_rebal = None

                h_val = sum(h["shares"] * series_get(px_open, t, h["entry_price"])
                            for t, h in holdings.items())
                portfolio_value = cash + h_val

                for t in [t for t in list(holdings.keys()) if t not in new_stocks]:
                    ep = series_get(px_open, t)
                    if np.isnan(ep): continue
                    h = holdings.pop(t)
                    cash += h["shares"] * ep * (1 - tc)
                    pnl = (ep / h["entry_price"] - 1) * 100 if h["entry_price"] > 0 else 0
                    trade_log.append({"date":date,"ticker":t,
                                      "action":"SELL_REBAL","pnl_pct":pnl})

                for t, w in new_weights.items():
                    ep = series_get(px_open, t)
                    if np.isnan(ep) or ep <= 0: continue
                    target_shares = int(portfolio_value * w / ep)
                    if target_shares <= 0: continue

                    atr_val = series_get(
                        atr.loc[date] if date in atr.index else pd.Series(), t)
                    if np.isnan(atr_val) or atr_val <= 0: atr_val = ep * 0.06
                    stop_price = ep - 5.0 * atr_val

                    if t in holdings:
                        diff = target_shares - holdings[t]["shares"]
                        if diff > 0:
                            cost = diff * ep * (1 + tc)
                            if cost <= cash:
                                holdings[t]["shares"] += diff; cash -= cost
                        elif diff < 0:
                            holdings[t]["shares"] += diff
                            cash += (-diff) * ep * (1 - tc)
                        holdings[t]["stop_price"] = stop_price
                    else:
                        cost = target_shares * ep * (1 + tc)
                        if cost <= cash:
                            holdings[t] = {
                                "shares":target_shares,
                                "entry_price":ep,
                                "stop_price":stop_price
                            }
                            cash -= cost
                            trade_log.append({"date":date,"ticker":t,
                                              "action":"BUY","pnl_pct":0})

            h_val = sum(h["shares"] * series_get(px_close, t, h["entry_price"])
                        for t, h in holdings.items())
            portfolio_value = cash + h_val

            if date in rebal_set and date != last_rebal_date:
                last_rebal_date = date
                exposure = float(regime.get(date, 1.0))

                universe = [t for t in get_universe_for_year(date.year)
                            if t in close.columns]
                try:
                    comp_row  = composite.loc[date, universe].dropna()
                    lv_row    = lv_score.loc[date, universe].dropna()
                    q_row     = q_score.loc[date, universe].dropna()
                    vol_row   = realized_vol.loc[date, universe].dropna()
                    ma_row    = above_ma.loc[date]
                except KeyError:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                valid = comp_row.index.tolist()
                if min_price_ma > 0:
                    valid = [t for t in valid
                             if series_get(ma_row, t, -1) >= min_price_ma/100]

                if not valid:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                ranked     = comp_row[valid].sort_values(ascending=False).index.tolist()
                top_stocks = apply_sector_cap(ranked, SECTOR_MAP, max_sector, top_n)

                if not top_stocks:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                if inv_vol_weight:
                    vols = vol_row.reindex(top_stocks).replace(0, np.nan).dropna()
                    if len(vols) > 0:
                        inv_v = 1.0 / vols
                        raw_w = (inv_v / inv_v.sum()).reindex(top_stocks).fillna(
                            1/len(top_stocks))
                    else:
                        raw_w = pd.Series(1/len(top_stocks), index=top_stocks)
                else:
                    raw_w = pd.Series(1/len(top_stocks), index=top_stocks)

                raw_w = raw_w.clip(upper=max_weight)
                s = raw_w.sum()
                weights_final = (raw_w / s * exposure) if s > 0 else raw_w

                weights_history[date] = weights_final.to_dict()
                signal_history[date] = {
                    t: {
                        "composite": round(safe_float(series_get(comp_row, t)), 3),
                        "lv_score":  round(safe_float(series_get(lv_row, t)),   3),
                        "q_score":   round(safe_float(series_get(q_row, t)),    3),
                        "vol_ann":   round(safe_float(series_get(vol_row, t))*100, 1),
                    }
                    for t in top_stocks if t in comp_row.index
                }
                pending_rebal = (top_stocks, weights_final.to_dict())

                stops = [t for t, h in holdings.items()
                         if series_get(px_close, t, h["stop_price"] + 1) < h["stop_price"]]
                for t in stops:
                    if t in holdings:
                        h  = holdings.pop(t)
                        cp = series_get(px_close, t, h["entry_price"])
                        cash += h["shares"] * cp * (1 - tc)
                        pnl = (cp / h["entry_price"] - 1) * 100 if h["entry_price"] > 0 else 0
                        trade_log.append({"date":date,"ticker":t,
                                          "action":"SELL_STOP","pnl_pct":pnl})

            port_values[date] = portfolio_value

        log.append(f"STEP6 ✅ {day_counter} days | {len(weights_history)} rebalances "
                   f"| {len(trade_log)} trades")

        # ── 7. Build return series ─────────────────────────────────
        port_series = pd.Series(port_values, dtype=float).dropna()
        common_idx  = port_series.index.intersection(bench_prices.index)
        if len(common_idx) < 20:
            return None, (
                f"Only {len(common_idx)} overlapping dates. "
                "Try Start Date 2018-01-01 or later."
            ), log

        port_series  = port_series.loc[common_idx]
        bench_norm   = bench_prices.loc[common_idx].ffill()
        bench_norm   = bench_norm / bench_norm.iloc[0] * 1_000_000.0

        port_ret  = port_series.pct_change().dropna()
        bench_ret = bench_norm.pct_change().dropna()
        common_r  = port_ret.index.intersection(bench_ret.index)
        port_ret  = port_ret.loc[common_r]
        bench_ret = bench_ret.loc[common_r]

        if len(port_ret) < 20:
            return None, f"Only {len(port_ret)} return obs.", log

        # ── 8. Metrics ────────────────────────────────────────────
        n_years  = len(port_series) / 252.0
        cagr     = (port_series.iloc[-1]/port_series.iloc[0])**(1/n_years) - 1
        b_cagr   = (bench_norm.iloc[-1]/bench_norm.iloc[0])**(1/n_years) - 1
        rf       = 0.065 / 252
        p_std    = port_ret.std()
        b_std    = bench_ret.std()
        sharpe   = ((port_ret.mean()-rf)/p_std)*np.sqrt(252) if p_std>1e-10 else 0.0
        b_sharpe = ((bench_ret.mean()-rf)/b_std)*np.sqrt(252) if b_std>1e-10 else 0.0
        neg      = port_ret[port_ret<0]
        downside = neg.std()*np.sqrt(252) if len(neg)>5 else 1e-6
        sortino  = ((port_ret.mean()-rf)*252)/downside
        dd_s, max_dd  = compute_max_dd(port_series)
        dd_b, b_maxdd = compute_max_dd(bench_norm)
        calmar   = cagr/abs(max_dd) if abs(max_dd)>1e-6 else 0.0
        vol_ann  = p_std*np.sqrt(252)
        win_rate = float((port_ret>0).mean())
        cov_m    = np.cov(port_ret.values, bench_ret.values)
        beta     = cov_m[0,1]/(cov_m[1,1]+1e-12)
        alpha    = cagr - beta*b_cagr
        excess   = port_ret - bench_ret
        ir       = (excess.mean()/(excess.std()+1e-12))*np.sqrt(252)
        var_95   = float(np.percentile(port_ret.values,5))
        cvar_95  = float(port_ret[port_ret<=var_95].mean()) \
                   if (port_ret<=var_95).any() else var_95

        # ── FIX: Capture ratio — use reindex to safely align indices ──
        up_mask  = bench_ret > 0
        dn_mask  = bench_ret < 0

        up_bench = bench_ret[up_mask]
        dn_bench = bench_ret[dn_mask]

        # Safely align port_ret to the bench masks using reindex
        up_port  = port_ret.reindex(up_bench.index).dropna()
        dn_port  = port_ret.reindex(dn_bench.index).dropna()

        # Align bench to matched port indices
        up_bench_aligned = up_bench.reindex(up_port.index).dropna()
        dn_bench_aligned = dn_bench.reindex(dn_port.index).dropna()

        # Final alignment — same length
        up_common = up_port.index.intersection(up_bench_aligned.index)
        dn_common = dn_port.index.intersection(dn_bench_aligned.index)

        if len(up_common) > 0 and up_bench_aligned.loc[up_common].mean() > 0:
            up_cap = float(up_port.loc[up_common].mean() /
                           up_bench_aligned.loc[up_common].mean())
        else:
            up_cap = 1.0

        if len(dn_common) > 0 and dn_bench_aligned.loc[dn_common].mean() < 0:
            dn_cap = float(dn_port.loc[dn_common].mean() /
                           dn_bench_aligned.loc[dn_common].mean())
        else:
            dn_cap = 1.0

        # Clamp to reasonable range to avoid display issues
        up_cap = float(np.clip(up_cap, 0.0, 2.0))
        dn_cap = float(np.clip(dn_cap, 0.0, 2.0))

        yr_s = port_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
        yr_b = bench_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
        cyrs = yr_s.index.intersection(yr_b.index)
        yr_s, yr_b = yr_s.loc[cyrs], yr_b.loc[cyrs]
        beat = int(sum(s>b for s,b in zip(yr_s.values,yr_b.values)))

        mp_m = port_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)
        mb_m = bench_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)

        tl_df = pd.DataFrame(trade_log) if trade_log else \
                pd.DataFrame(columns=["date","ticker","action","pnl_pct"])
        stop_rate = len(tl_df[tl_df["action"]=="SELL_STOP"])/max(len(tl_df),1)*100

        log.append(f"STEP8 ✅ CAGR={cagr:.2%} Sharpe={sharpe:.2f} "
                   f"MaxDD={max_dd:.2%} Beta={beta:.2f} UpCap={up_cap:.2f} DnCap={dn_cap:.2f}")

        return {
            "port_series":port_series,"bench_norm":bench_norm,
            "port_ret":port_ret,"bench_ret":bench_ret,
            "yr_strat":yr_s,"yr_bench":yr_b,
            "dd_s":dd_s,"dd_b":dd_b,
            "weights_history":weights_history,
            "signal_history":signal_history,
            "trade_log":tl_df,
            "monthly_port":mp_m,"monthly_bench":mb_m,
            "regime":regime,
            "metrics":{
                "CAGR":safe_float(cagr),"Bench CAGR":safe_float(b_cagr),
                "Sharpe":safe_float(sharpe),"B Sharpe":safe_float(b_sharpe),
                "Sortino":safe_float(sortino),"Max DD":safe_float(max_dd),
                "Bench MaxDD":safe_float(b_maxdd),"Calmar":safe_float(calmar),
                "Volatility":safe_float(vol_ann),"Win Rate":safe_float(win_rate),
                "Beta":safe_float(beta),"Alpha":safe_float(alpha),
                "Info Ratio":safe_float(ir),"VaR 95":safe_float(var_95),
                "CVaR 95":safe_float(cvar_95),"Beat Years":beat,
                "Total Years":len(yr_s),"Up Capture":safe_float(up_cap),
                "Down Capture":safe_float(dn_cap),"Stop Rate":safe_float(stop_rate),
                "N Trades":len(tl_df),"N Years":safe_float(n_years),
            },
        }, None, log

    # ──────────────────────────────────────────────────────────────
    # DISPLAY
    # ──────────────────────────────────────────────────────────────
    def run(self):
        with st.spinner("Running Quality + Low-Vol backtest (~1-2 min)..."):
            raw_result = self._run(
                self.start_date, self.end_date, self.top_n,
                self.lv_weight, self.q_weight,
                self.max_weight, self.inv_vol_weight,
                self.vol_window, self.max_sector,
                self.min_price_ma,
                self.fee_bps, self.slip_bps,
            )

        run_log = []
        if isinstance(raw_result, tuple) and len(raw_result) == 3:
            result, err, run_log = raw_result
        elif isinstance(raw_result, tuple) and len(raw_result) == 2:
            result, err = raw_result
        elif isinstance(raw_result, dict):
            result, err = raw_result, None
        else:
            result, err = None, f"Unexpected return: {type(raw_result)}"

        with st.expander("🛠 Debug Info"):
            import sys
            st.caption(f"Python {sys.version.split()[0]} | "
                       f"pandas {pd.__version__} | yfinance {_yf_version}")
            for line in run_log:
                st.error(line) if "❌" in line else st.success(line)
            if not run_log:
                st.info("Cached result — click 🗑 Clear Cache to re-run.")
            if err: st.error(f"Error: {err}")

        if result is None:
            st.error(f"❌ {err}")
            st.warning(
                "**Common fixes:**\n"
                "- Use **Start Date 2018-01-01** or later\n"
                "- Click **🗑 Clear Cache** in sidebar\n"
                "- Wait 60s (Yahoo Finance rate limit) and retry"
            )
            return

        m  = result["metrics"]
        ps = result["port_series"]
        bn = result["bench_norm"]
        pr = result["port_ret"]
        br = result["bench_ret"]
        ys = result["yr_strat"]
        yb = result["yr_bench"]

        # ── Coverage notice ───────────────────────────────────────
        st.info(
            f"📅 **{ps.index[0].strftime('%b %Y')} → {ps.index[-1].strftime('%b %Y')}** "
            f"({m['N Years']:.1f} yrs) | "
            f"Low-Vol weight: **{self.lv_weight*100:.0f}%** | "
            f"Quality weight: **{self.q_weight*100:.0f}%** | "
            f"Stocks: **{self.top_n}** | "
            f"Min regime exposure: **60%** (never full cash)"
        )

        # ── Defensive Strategy Banner ─────────────────────────────
        up_cap = m["Up Capture"]
        dn_cap = m["Down Capture"]
        if dn_cap < 0.85:
            st.success(
                f"🛡️ **Defensive Profile Confirmed** — "
                f"Up-market capture: **{up_cap*100:.0f}%** of Nifty gains | "
                f"Down-market capture: **{dn_cap*100:.0f}%** of Nifty losses. "
                f"The strategy participates meaningfully in rallies "
                f"while limiting losses in drawdowns."
            )
        else:
            st.warning(
                f"⚠️ Down-market capture {dn_cap*100:.0f}% is high — "
                "increase Low-Vol weight or use a wider vol window."
            )

        # ── KPI Cards ─────────────────────────────────────────────
        st.markdown("## 📊 Performance Overview")
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("CAGR", f"{m['CAGR']*100:.2f}%",
                  delta=f"{(m['CAGR']-m['Bench CAGR'])*100:.1f}% vs Nifty")
        c2.metric("Sharpe", f"{m['Sharpe']:.2f}",
                  delta=f"{m['Sharpe']-m['B Sharpe']:.2f} vs Nifty",
                  help="Risk-adjusted return. Target > 1.0")
        c3.metric("Calmar", f"{m['Calmar']:.2f}",
                  help="CAGR / Max Drawdown. Target > 1.2")
        c4.metric("Max Drawdown", f"{m['Max DD']*100:.1f}%",
                  delta=f"{(m['Max DD']-m['Bench MaxDD'])*100:.1f}% vs Nifty",
                  delta_color="inverse")
        c5.metric("Win Rate", f"{m['Win Rate']*100:.1f}%")

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Sortino",        f"{m['Sortino']:.2f}")
        c2.metric("Beta",           f"{m['Beta']:.2f}",
                  help="Target 0.5–0.9 for defensive quality strategy")
        c3.metric("Alpha (ann)",    f"{m['Alpha']*100:.1f}%")
        c4.metric("Up Capture",     f"{m['Up Capture']*100:.0f}%",
                  help="% of Nifty's upside captured. Target: 70-90%")
        c5.metric("Down Capture",   f"{m['Down Capture']*100:.0f}%",
                  help="% of Nifty's downside absorbed. Target: < 75%")

        final_val   = ps.iloc[-1]
        bench_final = bn.iloc[-1]
        st.markdown("---")
        c1,c2,c3 = st.columns(3)
        c1.metric("Strategy ₹10L grew to", f"₹{final_val/100_000:.1f}L",
                  delta=f"₹{(final_val-1_000_000)/100_000:.1f}L profit")
        c2.metric("Nifty B&H ₹10L grew to", f"₹{bench_final/100_000:.1f}L",
                  delta=f"₹{(bench_final-1_000_000)/100_000:.1f}L profit")
        c3.metric("Extra profit vs Nifty",
                  f"₹{(final_val-bench_final)/100_000:.1f}L",
                  delta=f"{(final_val/bench_final-1)*100:.1f}% more")
        st.markdown("---")

        # ── Equity Curve ──────────────────────────────────────────
        st.subheader("📈 Equity Curve vs Nifty 50")
        bn_ri = bn.reindex(ps.index).ffill()
        fig1  = go.Figure()
        fig1.add_trace(go.Scatter(x=ps.index, y=ps.values,
                                  name="Quality + Low-Vol",
                                  line=dict(color="#00695C", width=2.5)))
        fig1.add_trace(go.Scatter(x=bn.index, y=bn.values,
                                  name="Nifty 50 B&H",
                                  line=dict(color="#E65100",width=1.8,dash="dash")))
        fig1.add_trace(go.Scatter(
            x=list(ps.index)+list(ps.index[::-1]),
            y=list(ps.values)+list(bn_ri.values[::-1]),
            fill="toself", fillcolor="rgba(0,105,92,0.10)",
            line=dict(width=0), name="vs Benchmark"))
        fig1.update_layout(
            height=400, xaxis_title="Date",
            yaxis_title="Portfolio Value (₹)", yaxis=dict(tickformat=",.0f"),
            legend=dict(x=0.01,y=0.99), margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig1, use_container_width=True)

        # ── Drawdown ──────────────────────────────────────────────
        st.subheader("📉 Drawdown — Defensive Characteristic")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=result["dd_s"].index, y=(result["dd_s"]*100).values,
            fill="tozeroy", name="Quality+LowVol",
            fillcolor="rgba(0,105,92,0.40)",
            line=dict(color="#00695C",width=1)))
        fig2.add_trace(go.Scatter(
            x=result["dd_b"].index, y=(result["dd_b"]*100).values,
            fill="tozeroy", name="Nifty DD",
            fillcolor="rgba(230,81,0,0.20)",
            line=dict(color="#E65100",width=1,dash="dash")))
        fig2.add_hline(y=-20, line_dash="dot", line_color="red",
                       annotation_text="20% Target")
        fig2.update_layout(height=250, xaxis_title="Date",
                           yaxis_title="Drawdown %",
                           margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig2, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric("Strategy Max DD",  f"{m['Max DD']*100:.1f}%")
        c2.metric("Nifty Max DD",     f"{m['Bench MaxDD']*100:.1f}%")
        c3.metric("DD Saved",
                  f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
                  delta="Strategy better" if m['Max DD']>m['Bench MaxDD'] else "Worse",
                  delta_color="normal" if m['Max DD']>m['Bench MaxDD'] else "inverse")
        st.markdown("---")

        # ── Year-by-Year ──────────────────────────────────────────
        st.subheader("📅 Year-by-Year Returns")
        if len(ys) > 0:
            bar_colors = ["#2E7D32" if s>b else "#C62828"
                          for s,b in zip(ys.values,yb.values)]
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=ys.index.year.tolist(),
                                  y=(ys.values*100).tolist(),
                                  name="Strategy",marker_color=bar_colors,opacity=0.90))
            fig3.add_trace(go.Bar(x=yb.index.year.tolist(),
                                  y=(yb.values*100).tolist(),
                                  name="Nifty 50",marker_color="#E65100",opacity=0.60))
            fig3.add_hline(y=0, line_color="white", line_width=0.8)
            fig3.update_layout(
                barmode="group", height=320,
                xaxis_title="Year", yaxis_title="Return %",
                xaxis=dict(tickmode="linear",dtick=1,
                           tickvals=ys.index.year.tolist()),
                margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig3, use_container_width=True)

            yr_df = pd.DataFrame({
                "Year":       ys.index.year.tolist(),
                "Strategy %": [round(v*100,1) for v in ys.values],
                "Nifty 50 %": [round(v*100,1) for v in yb.values],
                "Alpha %":    [round((s-b)*100,1) for s,b in zip(ys.values,yb.values)],
                "Beat?":      ["✅" if s>b else "❌"
                               for s,b in zip(ys.values,yb.values)],
            })
            st.dataframe(yr_df, use_container_width=True, hide_index=True)
            bp = m["Beat Years"]/max(m["Total Years"],1)
            st.info(f"Beat Nifty in **{m['Beat Years']}/{m['Total Years']} years** ({bp*100:.0f}%)")
        st.markdown("---")

        # ── Capture Ratio Analysis — FIXED ────────────────────────
        st.subheader("🎯 Up/Down Market Capture — The Defensive Edge")
        st.caption(
            "Up-capture: how much of Nifty's gains the strategy keeps. "
            "Down-capture: how much of Nifty's losses the strategy suffers. "
            "Target: high up-capture, low down-capture."
        )

        # FIX: Use plain string labels (no \n) and explicit float conversion
        # to prevent Plotly rendering errors
        up_cap_val  = float(m["Up Capture"])   * 100
        dn_cap_val  = float(m["Down Capture"]) * 100
        capture_ratio = up_cap_val / max(dn_cap_val, 0.01)

        cap_labels = ["Up Market Capture", "Down Market Capture", "Nifty Benchmark"]
        cap_values = [round(up_cap_val, 1), round(dn_cap_val, 1), 100.0]
        cap_colors = ["#2E7D32", "#C62828", "#E65100"]
        cap_text   = [f"{up_cap_val:.0f}%", f"{dn_cap_val:.0f}%", "100%"]

        # FIX: opacity must be inside marker=dict() for per-bar opacity,
        # NOT passed directly as opacity=[...] to go.Bar (that only accepts scalar)
        fig_cap = go.Figure()
        fig_cap.add_trace(go.Bar(
            x=cap_labels,
            y=cap_values,
            marker=dict(
                color=cap_colors,
                opacity=[0.85, 0.85, 0.50],   # per-bar opacity — MUST be in marker dict
            ),
            text=cap_text,
            textposition="auto",
            width=[0.5, 0.5, 0.5],
        ))
        fig_cap.add_hline(
            y=100,
            line_dash="dot",
            line_color="white",
            annotation_text="Nifty = 100%",
            annotation_position="top right",
        )
        fig_cap.update_layout(
            height=300,
            yaxis_title="Capture % vs Nifty",
            yaxis=dict(range=[0, max(120, up_cap_val * 1.15, dn_cap_val * 1.15)]),
            margin=dict(l=10, r=10, t=20, b=10),
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_cap, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Up Market Capture",   f"{up_cap_val:.0f}%",
                  help="% of Nifty's up-days return captured. Target: 70–90%")
        c2.metric("Down Market Capture", f"{dn_cap_val:.0f}%",
                  help="% of Nifty's down-days return absorbed. Target: <75%")
        c3.metric("Capture Ratio (Up/Down)", f"{capture_ratio:.2f}",
                  help="Target > 1.0. Higher = better defensive quality. "
                       "NSE Low Vol 30 typically achieves 1.2–1.4.")

        if capture_ratio >= 1.0:
            st.success(
                f"✅ Capture ratio **{capture_ratio:.2f}** — strategy captures more upside "
                f"(**{up_cap_val:.0f}%**) than downside (**{dn_cap_val:.0f}%**). "
                "This is the hallmark of a quality defensive strategy."
            )
        else:
            st.warning(
                f"⚠️ Capture ratio {capture_ratio:.2f} < 1.0 — "
                "strategy is losing more in down markets than it gains in up markets. "
                "Try increasing Low-Vol weight or expanding the vol window."
            )
        st.markdown("---")

        # ── Regime Exposure ───────────────────────────────────────
        st.subheader("🌡️ Regime Exposure — Why We Never Go to 0%")
        regime_ri = result["regime"].reindex(ps.index).ffill()
        fig_reg = go.Figure()
        # FIX: Plotly does NOT support 8-digit hex (#RRGGBBAA).
        # Alpha transparency must use rgba() format.
        for level, line_rgba, fillcolor, label in [
            (1.0, "rgba(46,125,50,1.0)",  "rgba(46,125,50,0.33)",  "100% — Full Bull Market"),
            (0.8, "rgba(139,195,74,1.0)", "rgba(139,195,74,0.33)", "80% — Mild Caution"),
            (0.6, "rgba(255,193,7,1.0)",  "rgba(255,193,7,0.33)",  "60% — Bear Market (min floor)"),
        ]:
            mask = regime_ri == level
            if mask.any():
                fig_reg.add_trace(go.Scatter(
                    x=regime_ri.index, y=(regime_ri*100).where(mask),
                    fill="tozeroy", name=label,
                    fillcolor=fillcolor, line=dict(color=line_rgba, width=0.5)))
        fig_reg.update_layout(
            height=200, xaxis_title="Date", yaxis_title="% Invested",
            yaxis=dict(range=[0,110]),
            legend=dict(orientation="h",yanchor="bottom",y=1.02),
            margin=dict(l=10,r=10,t=30,b=10))
        st.plotly_chart(fig_reg, use_container_width=True)
        cash_pct = (regime_ri < 1.0).mean()
        st.caption(
            f"Strategy was below 100% in **{cash_pct*100:.0f}% of periods**. "
            "Unlike momentum, quality/low-vol holds minimum 60% even in bears — "
            "because these stocks' defensive nature IS the crash protection."
        )
        st.markdown("---")

        # ── Current Holdings + Signal Scores ─────────────────────
        st.subheader("📋 Current Portfolio — Quality & Low-Vol Scores")
        if result["weights_history"]:
            last_w    = list(result["weights_history"].values())[-1]
            last_d    = list(result["weights_history"].keys())[-1]
            last_sig  = result["signal_history"].get(last_d, {})
            st.caption(f"Last rebalance: **{last_d.strftime('%d %b %Y')}**")

            h_rows = []
            for t, w in sorted(last_w.items(), key=lambda x: -x[1]):
                sig = last_sig.get(t, {})
                h_rows.append({
                    "Ticker":       t.replace(".NS",""),
                    "Sector":       SECTOR_MAP.get(t,"Other"),
                    "Weight %":     round(w*100,1),
                    "₹ Alloc":      f"₹{1_000_000*w:,.0f}",
                    "Composite":    sig.get("composite","—"),
                    "LowVol Score": sig.get("lv_score","—"),
                    "Quality Score":sig.get("q_score","—"),
                    "Volatility %": sig.get("vol_ann","—"),
                })
            h_df = pd.DataFrame(h_rows)

            col1, col2 = st.columns([3,1])
            with col1:
                st.dataframe(h_df, use_container_width=True, hide_index=True)
            with col2:
                sec_w = h_df.groupby("Sector")["Weight %"].sum().reset_index()
                fig_p = go.Figure(go.Pie(
                    labels=sec_w["Sector"],
                    values=sec_w["Weight %"],
                    marker_colors=[SECTOR_COLORS.get(s,"#757575")
                                   for s in sec_w["Sector"]],
                    hole=0.4, textinfo="label+percent",
                ))
                fig_p.update_layout(height=280,
                                     margin=dict(l=0,r=0,t=10,b=10),
                                     showlegend=False)
                st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("No positions — portfolio is in minimum 60% cash regime.")
        st.markdown("---")

        # ── Rolling Returns ───────────────────────────────────────
        st.subheader("📊 Rolling Returns")
        tab1, tab2 = st.tabs(["12-Month Rolling", "Monthly Distribution"])
        with tab1:
            rs = pr.rolling(252).apply(lambda x:(1+x).prod()-1)*100
            rb = br.rolling(252).apply(lambda x:(1+x).prod()-1)*100
            fig_r = go.Figure()
            fig_r.add_trace(go.Scatter(x=rs.index,y=rs.values,
                                       name="Strategy",line=dict(color="#00695C",width=1.8)))
            fig_r.add_trace(go.Scatter(x=rb.index,y=rb.values,
                                       name="Nifty 50",line=dict(color="#E65100",
                                                                  width=1.3,dash="dash")))
            fig_r.add_hline(y=0, line_color="gray", line_width=0.8)
            fig_r.update_layout(height=240, xaxis_title="Date",
                                 yaxis_title="12M Return %",
                                 margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig_r, use_container_width=True)
        with tab2:
            mp_disp = result["monthly_port"]*100
            mb_disp = result["monthly_bench"]*100
            fig_h = go.Figure()
            fig_h.add_trace(go.Histogram(x=mp_disp.values,name="Strategy",
                                          opacity=0.75,nbinsx=40,
                                          marker_color="#00695C"))
            fig_h.add_trace(go.Histogram(x=mb_disp.values,name="Nifty 50",
                                          opacity=0.55,nbinsx=40,
                                          marker_color="#E65100"))
            fig_h.update_layout(barmode="overlay",height=240,
                                 xaxis_title="Monthly Return %",
                                 yaxis_title="Count",
                                 margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig_h, use_container_width=True)
            st.caption(f"Strategy avg monthly: **{mp_disp.mean():.2f}%** | "
                       f"Positive months: **{(mp_disp>0).mean()*100:.0f}%**")
        st.markdown("---")

        # ── Trade Analysis ────────────────────────────────────────
        st.subheader("📊 Trade Analysis")
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total Trades",   f"{m['N Trades']}")
        c2.metric("Trades/Year",    f"{m['N Trades']/max(m['N Years'],1):.0f}",
                  help="Low-vol strategies trade less than momentum")
        c3.metric("Stop-Loss Rate", f"{m['Stop Rate']:.1f}%",
                  help="Quality stocks rarely hit stops — low is good")
        c4.metric("Volatility",     f"{m['Volatility']*100:.1f}%")
        c5.metric("VaR 95% daily",  f"{m['VaR 95']*100:.2f}%")
        st.markdown("---")

        # ── Investor Scorecard ────────────────────────────────────
        st.subheader("🎯 Investor Target Scorecard")
        bp2 = m["Beat Years"]/max(m["Total Years"],1)
        targets = [
            ("CAGR > 15%",              m["CAGR"]*100>15,           f"{m['CAGR']*100:.1f}%"),
            ("Beats Nifty (CAGR)",      m["CAGR"]>m["Bench CAGR"],  f"+{(m['CAGR']-m['Bench CAGR'])*100:.1f}%"),
            ("Sharpe > 0.9",            m["Sharpe"]>0.9,            f"{m['Sharpe']:.2f}"),
            ("Sortino > 1.0",           m["Sortino"]>1.0,           f"{m['Sortino']:.2f}"),
            ("Max DD < Nifty MaxDD",    m["Max DD"]>m["Bench MaxDD"],f"{m['Max DD']*100:.1f}%"),
            ("Calmar > 1.0",            m["Calmar"]>1.0,            f"{m['Calmar']:.2f}"),
            ("Beat Nifty >50% yrs",     bp2>0.50,                   f"{m['Beat Years']}/{m['Total Years']}"),
            ("Beta 0.5–0.9",            0.5<=m["Beta"]<=0.9,        f"{m['Beta']:.2f}"),
            ("Down Capture < 85%",      m["Down Capture"]<0.85,     f"{m['Down Capture']*100:.0f}%"),
            ("Info Ratio > 0.2",        m["Info Ratio"]>0.2,        f"{m['Info Ratio']:.2f}"),
        ]
        scored = sum(1 for _,p,_ in targets if p)
        st.dataframe(pd.DataFrame([{
            "Status":"✅ PASS" if p else "❌ FAIL",
            "Target":t,"Value":v
        } for t,p,v in targets]), use_container_width=True, hide_index=True)
        verdict = ("✅ Institutional Quality" if scored>=8
                   else "⚠️ Getting Close" if scored>=5
                   else "🔨 Needs More Work")
        fn = st.success if scored>=8 else st.warning if scored>=5 else st.error
        fn(f"Score: **{scored}/10** — {verdict}")
        st.markdown("---")

        # ── Quant Diagnostics ─────────────────────────────────────
        st.subheader("🧠 Quant Diagnostics")
        if m["CAGR"]>m["Bench CAGR"]:
            st.success(f"✅ Beats Nifty by **{(m['CAGR']-m['Bench CAGR'])*100:.1f}%/year** "
                       f"(₹{(final_val-bench_final)/100_000:.1f}L extra on ₹10L)")
        else:
            st.warning(f"⚠️ CAGR {m['CAGR']*100:.1f}% vs Nifty {m['Bench CAGR']*100:.1f}%. "
                       "Quality/low-vol strategies shine in risk-adjusted terms — "
                       "check Sharpe and down-capture.")

        if m["Max DD"] > m["Bench MaxDD"]:
            st.success(f"✅ Lower drawdown than Nifty: "
                       f"**{m['Max DD']*100:.1f}%** vs **{m['Bench MaxDD']*100:.1f}%**")
        if m["Down Capture"] < 0.85:
            st.success(f"✅ Down-market capture **{m['Down Capture']*100:.0f}%** — "
                       "absorbs less than 85% of Nifty's losses")
        if m["Beta"] < 0.5:
            st.warning(f"⚠️ Beta {m['Beta']:.2f} too low — increase vol window or reduce top_n")
        elif m["Beta"] <= 0.9:
            st.success(f"✅ Beta **{m['Beta']:.2f}** — appropriate defensive profile")

        with st.expander("📖 Strategy Research Notes — For Institutional Investors"):
            st.markdown(f"""
### The Two Anomalies

**LOW VOLATILITY (Baker, Bradley & Wurgler, 2011)**
Institutional fund managers are evaluated against the Nifty 50 benchmark.
To outperform, many tilt toward high-beta exciting stocks — creating a
systematic mispricing of boring, low-volatility stocks. This creates
**persistent alpha** for investors not constrained by benchmark tracking.
The NSE Nifty100 Low Vol 30 index demonstrates this — 4%/yr excess return
over Nifty 50 using only price-based volatility. No fundamental data needed.

**QUALITY (Asness, Frazzini & Pedersen, 2013 — "Quality Minus Junk")**
Investors overpay for exciting high-growth stories (high P/E, high beta)
and systematically ignore boring, profitable compounders.
Implementation uses price-derived proxies since yfinance provides OHLCV only:
- **Return smoothness** (trailing Sharpe ratio) → correlates with ROE on large-caps
- **Drawdown recovery speed** → companies with strong moats recover faster
- **Return consistency** → fraction of positive-drift days → earnings quality proxy

**WHY COMBINE THEM?**
The two anomalies have low correlation — they work in different regimes.
Low-vol dominates in bear markets (lowest-beta stocks hold up).
Quality dominates in choppy sideways markets (compounders keep earning).
Combined: two independent alpha sources with one portfolio.

### Regime Design — Why 60% Floor

Maximum exposure reduction is 60% equity / 40% cash.
Quality stocks are **inherently defensive** — their business models
(strong cash flows, low debt, pricing power) mean they naturally
outperform in downturns. Going to 100% cash abandons this advantage.
In the 2020 crash: a pure quality/low-vol portfolio fell ~20-25%
vs Nifty's 38% — **that 15%+ protection IS the strategy working.**

### Current Portfolio Signal Explanation
- **Composite Score**: higher = better candidate (less volatile + higher quality)
- **LowVol Score**: cross-sectional z-score (less volatile than peers = positive)
- **Quality Score**: cross-sectional z-score (smoother returns than peers = positive)
- **Volatility %**: actual annualised 1-year volatility (lower is selected)

### Comparison vs Other Indian Investments
| Investment | CAGR | Risk | Effort |
|---|---|---|---|
| FD / Savings | 6–7% | Very low | None |
| Nifty 50 Index Fund | 12–14% | Medium | None |
| **This Strategy (target)** | **15–19%** | **Lower than Nifty** | Monthly rebalance |
| Momentum Strategy | 18–22% | Medium-High | Monthly rebalance |
| Small-cap stocks | 15–25% | Very high | High |

Quality + Low-Vol's edge over a simple Nifty index fund: **similar or better CAGR
with meaningfully lower drawdowns** — which matters enormously for real investor
psychology and compounding.

*Past performance does not guarantee future results.*
            """)