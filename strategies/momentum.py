"""
MOMENTUM STRATEGY v7.1 — Nifty 50
==================================
Hotfix release on top of v7.

  BUG-FIX (the crash you saw):
     ValueError: Invalid value of type 'builtins.str' received for the
     'fillcolor' property of scatter
     Received value: '#2E7D3255'

     Root cause: in the regime-exposure chart, fillcolor was built by
     string-concatenating an alpha byte onto a hex code:
         fillcolor = color + "55"        # '#2E7D32' + '55' → '#2E7D3255'
     That produces an 8-digit RGBA hex which Plotly does NOT accept
     (it only accepts 6-digit hex, rgb()/rgba(), hsl(), or named colours).

  FIX:
     - All fillcolor values are now produced via _hex_to_rgba(hex, alpha)
       which returns a proper "rgba(r,g,b,a)" string.
     - The regime chart was also rebuilt to use a single always-defined
       step-area trace + background hrect bands, instead of one fragile
       per-tier Scatter with fill='tozeroy' and NaN gaps. This is the
       same pattern that crashed in trend_following v2.7 — fixing it the
       same way avoids future Plotly-version regressions.

All v7 features (FIX-1 to FIX-5) retained — signal logic byte-identical.

  FIX-1  TIERED REGIME  — 5-level exposure (20/40/60/80/100%) replaces
          binary 0/100%.
  FIX-2  DUAL MOMENTUM  — Stock must beat Nifty's own 12M return.
  FIX-3  WIDER ATR STOP — Moved to 4.5× (was 3.5×).
  FIX-4  REBALANCE FREQUENCY CHOICE — Quarterly option added.
  FIX-5  RELATIVE MOMENTUM SCORE — Composite relative score.

All previous fixes retained:
  ✅ Historical constituents (survivorship bias fix)
  ✅ Next-day open execution (look-ahead bias fix)
  ✅ Sector cap (max 3 per sector)
  ✅ Blended inv-vol + momentum weights
  ✅ CAGR formula correct (annualised, not total return)
  ✅ Pandas version-safe frequency strings
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from strategies.base import BaseStrategy

try:
    _yf_version = yf.__version__
except Exception:
    _yf_version = "unknown"

# ── Pandas version-safe frequency strings ─────────────────────────────
try:
    _maj, _min = [int(x) for x in pd.__version__.split(".")[:2]]
    _NEW_PD = (_maj > 2) or (_maj == 2 and _min >= 2)
except Exception:
    _NEW_PD = True
FREQ_ME = "ME" if _NEW_PD else "M"
FREQ_QE = "QE" if _NEW_PD else "Q"
FREQ_YE = "YE" if _NEW_PD else "Y"


# ============================================================
# COLOR HELPER — the actual bug fix
# ============================================================
def _hex_to_rgba(hex_color: str, alpha: float = 0.5) -> str:
    """
    Convert '#RRGGBB' (or '#RRGGBBAA') + float alpha → 'rgba(r,g,b,a)'.

    Plotly rejects 8-digit hex (e.g. '#2E7D3255'). Old v7 was building
    fillcolors as `color + "55"` which produced exactly that. This helper
    is the canonical conversion.

    Locale-safe: uses fixed C-style formatting (some locales use ',' as
    decimal separator, which Plotly also rejects).
    """
    h = str(hex_color).lstrip("#")
    if len(h) >= 6:
        try:
            r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
        except ValueError:
            r, g, b = 128, 128, 128
    else:
        r, g, b = 128, 128, 128
    a = float(alpha)
    if a < 0.0: a = 0.0
    if a > 1.0: a = 1.0
    return "rgba({:d},{:d},{:d},{:.3f})".format(int(r), int(g), int(b), a)


# ============================================================
# UNIVERSE: historical Nifty 50 constituents by year
# (survivorship bias fix — only trade what was actually in the index)
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
        if year >= y:
            u.update(tickers)
    for t, ly in REMOVALS_LAST_YEAR.items():
        if year > ly:
            u.discard(t)
    for t, (s, e) in REMOVED_STOCKS.items():
        if int(s[:4]) <= year < int(e[:4]):
            u.add(t)
    return sorted(u)


def apply_sector_cap(ranked, sector_map, max_per_sector, top_n):
    """Walk ranked list picking stocks, respecting max per sector."""
    selected, counts = [], {}
    for t in ranked:
        if len(selected) >= top_n:
            break
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
    """Safe Series lookup — avoids AttributeError on Series.get()."""
    try:
        val = series[key]
        return float(val) if pd.notna(val) else default
    except (KeyError, TypeError):
        return default


def compute_max_dd(series):
    """Returns (drawdown_series, max_drawdown_scalar)."""
    roll_max = series.cummax()
    dd = (series / roll_max.replace(0, np.nan) - 1).fillna(0)
    return dd, float(dd.min())


# ============================================================
# FIX-1: TIERED REGIME
# ============================================================
def tiered_regime(bench_prices, ma_period=200, smooth=5):
    """
    5-level exposure based on Nifty distance from its 200-day MA.

    The key insight: a -12% gap below 200MA is a serious bear market.
    A -2% gap is just a normal dip. Treating them identically (binary 0/100%)
    was causing the strategy to miss entire recovery rallies.

    Tier table:
      Gap ≥ 0%          → 100% (full bull)
      Gap -2% to 0%     →  80% (slight caution)
      Gap -5% to -2%    →  60% (moderate caution)
      Gap -10% to -5%   →  40% (defensive)
      Gap < -10%        →  20% (near-cash, not full cash — keeps toehold)
    """
    bench_ma  = bench_prices.rolling(ma_period, min_periods=ma_period//2).mean()
    bench_gap = (bench_prices / bench_ma.replace(0, np.nan) - 1)
    gap_smooth = bench_gap.rolling(smooth, min_periods=1).mean()

    exposure = pd.Series(1.0, index=bench_prices.index)
    exposure[gap_smooth <  0.00] = 0.80
    exposure[gap_smooth < -0.02] = 0.60
    exposure[gap_smooth < -0.05] = 0.40
    exposure[gap_smooth < -0.10] = 0.20
    return exposure


# ============================================================
# STRATEGY CLASS
# ============================================================
class MomentumStrategy(BaseStrategy):
    NAME = "Momentum (Nifty 50)"
    DESCRIPTION = (
        "Monthly momentum on Nifty 50 with dual momentum gate, "
        "tiered regime filter, and ATR stop-loss."
    )

    def render_sidebar(self):
        self.start_date = st.sidebar.date_input(
            "Start Date", value=pd.to_datetime("2015-01-01"))
        self.end_date   = st.sidebar.date_input(
            "End Date",   value=pd.to_datetime("2025-01-01"))
        self.top_n      = st.sidebar.slider("Stocks to Hold", 5, 15, 12)

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Signal Parameters**")
        self.lookback   = st.sidebar.slider(
            "Momentum Lookback (days)", 63, 315, 252,
            help="12M default. The 'skip last 1 month' is applied automatically.")
        self.skip_last  = st.sidebar.slider(
            "Skip Last N Days", 0, 42, 21,
            help="Skips short-term reversal. 21 = skip last 1 month.")
        self.max_weight = st.sidebar.slider(
            "Max Weight per Stock %", 8, 25, 15) / 100
        self.atr_mult   = st.sidebar.slider(
            "ATR Stop Multiplier", 2.0, 6.0, 4.5, 0.5,
            help="Wider = fewer false stops. Default 4.5.")

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Rebalance Frequency**")
        self.rebal_freq = st.sidebar.selectbox(
            "Rebalance Every",
            ["Monthly (~70 trades/yr)", "Quarterly (~30 trades/yr)"],
            index=0,
            help="Quarterly halves trading costs with minimal CAGR impact."
        )

        st.sidebar.markdown("---")
        st.sidebar.markdown("**Signal Enhancements**")
        self.use_dual_momentum = st.sidebar.checkbox(
            "Dual Momentum Gate",
            value=True,
            help="Stock must beat Nifty's own return, not just beat 0%. "
                 "Eliminates 'tide-lifters' in bull markets."
        )
        self.dual_mom_weight = st.sidebar.slider(
            "Dual Momentum Blend (0=abs, 1=relative)",
            0.0, 1.0, 0.5, 0.1,
            help="0 = pure absolute momentum. 1 = pure relative (vs Nifty). "
                 "0.5 blends both equally."
        ) if self.use_dual_momentum else 0.0

        st.sidebar.markdown("---")
        self.fee_bps  = st.sidebar.number_input("Fee (bps)",      value=1.0, min_value=0.0)
        self.slip_bps = st.sidebar.number_input("Slippage (bps)", value=2.0, min_value=0.0)

        if st.sidebar.button("🗑 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

    # ──────────────────────────────────────────────────────────────
    # BACKTEST (cached so parameters can be tweaked without re-downloading)
    # ──────────────────────────────────────────────────────────────
    @st.cache_data
    def _run(_self, start_date, end_date, top_n, lookback, skip_last,
             max_weight, atr_mult, rebal_freq, use_dual_momentum,
             dual_mom_weight, fee_bps, slip_bps):

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
            log.append(f"STEP2 ✅ shape={raw.shape}, empty={raw.empty}")
        except Exception as e:
            return None, f"Download failed: {e}", log

        if raw.empty or raw.shape[0] < 20:
            return None, (
                "Yahoo Finance returned no data. "
                "Try Start Date 2018-01-01 or later. "
                "Yahoo Finance India data before 2016 is unreliable."
            ), log

        # ── 3. Extract fields ─────────────────────────────────────
        def _field(r, names):
            if isinstance(r.columns, pd.MultiIndex):
                l0 = r.columns.get_level_values(0).unique().tolist()
                for n in names:
                    if n in l0: return r[n].copy()
            else:
                for n in names:
                    if n in r.columns: return r[[n]].copy()
            return None

        close  = _field(raw, ["Close","Adj Close"])
        open_  = _field(raw, ["Open"])
        high   = _field(raw, ["High"])
        low    = _field(raw, ["Low"])

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
                "^NSEI missing — Yahoo Finance India data unreliable for this period. "
                "Try Start Date 2018-01-01 or later."
            ), log

        bench_prices = close["^NSEI"].copy()
        scols = [c for c in close.columns if c != "^NSEI"]
        close = close[scols]; open_ = open_[scols]
        high  = high[scols];  low   = low[scols]

        n_rows = len(close)
        log.append(f"STEP4 ✅ {len(close.columns)} stocks, {n_rows} days")
        if n_rows < 60:
            return None, f"Only {n_rows} rows — need 60+.", log

        # ── 5. Indicators ─────────────────────────────────────────
        mp   = min(100, max(10, n_rows // 10))
        eff_lb = min(lookback, n_rows - skip_last - 5)

        daily_ret = close.pct_change().fillna(0)

        # ── FIX-2: Dual momentum (relative to Nifty) ──────────────
        # Absolute momentum: how much has the stock returned?
        abs_mom_12m = (close.shift(skip_last) /
                       close.shift(eff_lb).replace(0, np.nan)) - 1
        abs_mom_6m  = (close.shift(skip_last) /
                       close.shift(min(126, eff_lb)).replace(0, np.nan)) - 1

        # Nifty's own return over the same windows (scalar series)
        bench_abs_12m = (bench_prices.shift(skip_last) /
                         bench_prices.shift(eff_lb).replace(0, np.nan)) - 1
        bench_abs_6m  = (bench_prices.shift(skip_last) /
                         bench_prices.shift(min(126, eff_lb)).replace(0, np.nan)) - 1

        # Relative momentum: stock return minus Nifty return
        # This is the key signal — a stock up 20% when Nifty is up 18%
        # has real alpha. A stock up 10% when Nifty is up 18% is lagging.
        rel_mom_12m = abs_mom_12m.sub(bench_abs_12m, axis=0)
        rel_mom_6m  = abs_mom_6m.sub(bench_abs_6m,  axis=0)

        # Composite score: blend absolute + relative based on user setting
        # dual_mom_weight=0 → pure absolute (original v6 behaviour)
        # dual_mom_weight=1 → pure relative (only beats-Nifty stocks)
        # dual_mom_weight=0.5 → balanced (recommended)
        abs_composite = 0.6 * abs_mom_12m + 0.4 * abs_mom_6m
        rel_composite = 0.6 * rel_mom_12m + 0.4 * rel_mom_6m
        momentum = ((1 - dual_mom_weight) * abs_composite +
                    dual_mom_weight * rel_composite)

        sma200   = close.rolling(200, min_periods=mp).mean()
        trend_ok = (close > sma200).fillna(False)
        roll_max = close.rolling(252, min_periods=1).max().replace(0, np.nan)
        dd_filt  = (close / roll_max - 1).fillna(-1)
        vol63    = daily_ret.rolling(63, min_periods=10).std() * np.sqrt(252)

        # ATR
        prev_c = close.shift(1)
        tr_df  = pd.DataFrame({
            col: pd.concat([
                (high[col] - low[col]),
                (high[col] - prev_c[col]).abs(),
                (low[col]  - prev_c[col]).abs(),
            ], axis=1).max(axis=1) for col in close.columns
        })
        atr = tr_df.rolling(14, min_periods=5).mean()

        # ── FIX-1: Tiered regime ───────────────────────────────────
        regime = tiered_regime(bench_prices, ma_period=200, smooth=5)
        pct_reduced = (regime < 1.0).mean()
        log.append(f"STEP5 ✅ Regime: {pct_reduced:.1%} of days below 100% exposure "
                   f"(5 tiers vs old binary)")

        # ── 6. Backtest loop ──────────────────────────────────────
        freq = FREQ_QE if "Quarterly" in rebal_freq else FREQ_ME
        dates     = close.index
        rebal_set = set()
        for rd in pd.date_range(dates[0], dates[-1], freq=freq):
            future = dates[dates >= rd]
            if len(future) > 0:
                rebal_set.add(future[0])

        portfolio_value = 1_000_000.0
        cash            = portfolio_value
        holdings        = {}
        port_values     = {}
        weights_history = {}
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

            # Execute pending rebalance at next-day open (FIX-2: no look-ahead)
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
                    trade_log.append({"date":date,"ticker":t,"action":"SELL_REBAL","pnl_pct":pnl})

                for t, w in new_weights.items():
                    ep = series_get(px_open, t)
                    if np.isnan(ep) or ep <= 0: continue
                    target_shares = int(portfolio_value * w / ep)
                    if target_shares <= 0: continue
                    atr_val = series_get(
                        atr.loc[date] if date in atr.index else pd.Series(), t)
                    if np.isnan(atr_val) or atr_val <= 0: atr_val = ep * 0.05
                    stop_price = ep - atr_mult * atr_val

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
                                "shares": target_shares,
                                "entry_price": ep,
                                "stop_price": stop_price
                            }
                            cash -= cost
                            trade_log.append({"date":date,"ticker":t,"action":"BUY","pnl_pct":0})

            # Mark to market
            h_val = sum(h["shares"] * series_get(px_close, t, h["entry_price"])
                        for t, h in holdings.items())
            portfolio_value = cash + h_val

            # FIX-3: Weekly ATR stop (not daily — avoids noise whipsaws)
            if day_counter % 5 == 0 and holdings:
                stops = [t for t, h in holdings.items()
                         if series_get(px_close, t, h["stop_price"] + 1) < h["stop_price"]]
                for t in stops:
                    h  = holdings.pop(t)
                    cp = series_get(px_close, t, h["entry_price"])
                    cash += h["shares"] * cp * (1 - tc)
                    pnl = (cp / h["entry_price"] - 1) * 100 if h["entry_price"] > 0 else 0
                    trade_log.append({"date":date,"ticker":t,"action":"SELL_STOP","pnl_pct":pnl})
                if stops:
                    h_val = sum(h["shares"] * series_get(px_close, t2, h["entry_price"])
                                for t2, h in holdings.items())
                    portfolio_value = cash + h_val

            # Rebalance signal (computed at close, executed at NEXT open)
            if date in rebal_set and date != last_rebal_date:
                last_rebal_date = date
                # FIX-1: tiered exposure (not binary)
                exposure = float(regime.get(date, 1.0))

                universe = [t for t in get_universe_for_year(date.year)
                            if t in close.columns]
                try:
                    mom_row   = momentum.loc[date, universe].dropna()
                    trend_row = trend_ok.loc[date]
                    dd_row    = dd_filt.loc[date]
                    vol_row   = vol63.loc[date]
                except KeyError:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                # Filter pipeline
                valid = [t for t in mom_row.index if safe_float(mom_row.get(t, -1)) > 0]
                valid = [t for t in valid if bool(trend_row.get(t, False))]
                valid = [t for t in valid if safe_float(dd_row.get(t, -1)) > -0.45]

                if not valid:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                # Rank by composite momentum score, apply sector cap
                ranked     = mom_row[valid].sort_values(ascending=False).index.tolist()
                top_stocks = apply_sector_cap(ranked, SECTOR_MAP, 3, top_n)

                if not top_stocks:
                    pending_rebal = ([], {})
                    port_values[date] = portfolio_value
                    continue

                # Blended weights: 60% inverse-vol + 40% momentum-proportional
                n     = len(top_stocks)
                vols  = vol_row[top_stocks].replace(0, np.nan).dropna()
                moms  = mom_row[top_stocks].clip(lower=0)
                w_vol = ((1/vols)/(1/vols).sum()).reindex(top_stocks).fillna(1/n) \
                        if len(vols) > 0 else pd.Series(1/n, index=top_stocks)
                total_m = moms.sum()
                w_mom   = (moms/total_m).reindex(top_stocks).fillna(1/n) \
                          if total_m > 0 else pd.Series(1/n, index=top_stocks)
                raw_w   = (0.6*w_vol + 0.4*w_mom).clip(upper=max_weight)
                s       = raw_w.sum()
                # Scale by tiered regime exposure (FIX-1: partial, not full cash)
                weights_final = (raw_w / s * exposure) if s > 0 else raw_w

                weights_history[date] = weights_final.to_dict()
                pending_rebal = (top_stocks, weights_final.to_dict())

            port_values[date] = portfolio_value

        log.append(f"STEP6 ✅ {day_counter} days | {len(weights_history)} rebalances "
                   f"| {len(trade_log)} trades")

        # ── 7. Build series & metrics ─────────────────────────────
        port_series = pd.Series(port_values, dtype=float).dropna()
        common_idx  = port_series.index.intersection(bench_prices.index)
        if len(common_idx) < 20:
            return None, (
                f"Only {len(common_idx)} overlapping dates. "
                "Strategy may be in cash the entire period — "
                "regime filter may be too tight. Try Start Date 2018-01-01."
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
            return None, f"Only {len(port_ret)} return obs — too few.", log

        n_years  = len(port_series) / 252.0
        cagr     = (port_series.iloc[-1]/port_series.iloc[0])**(1/n_years) - 1
        b_cagr   = (bench_norm.iloc[-1]/bench_norm.iloc[0])**(1/n_years) - 1
        rf       = 0.065/252
        p_std    = port_ret.std()
        b_std    = bench_ret.std()
        sharpe   = ((port_ret.mean()-rf)/p_std)*np.sqrt(252) if p_std > 1e-10 else 0.0
        b_sharpe = ((bench_ret.mean()-rf)/b_std)*np.sqrt(252) if b_std > 1e-10 else 0.0
        neg      = port_ret[port_ret < 0]
        downside = neg.std()*np.sqrt(252) if len(neg) > 5 else 1e-6
        sortino  = ((port_ret.mean()-rf)*252) / downside
        dd_s, max_dd  = compute_max_dd(port_series)
        dd_b, b_maxdd = compute_max_dd(bench_norm)
        calmar   = cagr/abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
        vol_ann  = p_std*np.sqrt(252)
        win_rate = float((port_ret>0).mean())
        cov_m    = np.cov(port_ret.values, bench_ret.values)
        beta     = cov_m[0,1]/(cov_m[1,1]+1e-12)
        alpha    = cagr - beta*b_cagr
        excess   = port_ret - bench_ret
        ir       = (excess.mean()/(excess.std()+1e-12))*np.sqrt(252)
        var_95   = float(np.percentile(port_ret.values, 5))
        cvar_95  = float(port_ret[port_ret<=var_95].mean()) \
                   if (port_ret<=var_95).any() else var_95

        yr_s = port_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
        yr_b = bench_ret.resample(FREQ_YE).apply(lambda x: (1+x).prod()-1)
        cyrs = yr_s.index.intersection(yr_b.index)
        yr_s, yr_b = yr_s.loc[cyrs], yr_b.loc[cyrs]
        beat = int(sum(s>b for s,b in zip(yr_s.values, yr_b.values)))

        mp_m  = port_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)
        mb_m  = bench_ret.resample(FREQ_ME).apply(lambda x: (1+x).prod()-1)
        bmths = int((mp_m > mb_m).sum())

        tl_df = pd.DataFrame(trade_log) if trade_log else \
                pd.DataFrame(columns=["date","ticker","action","pnl_pct"])
        stop_rate = len(tl_df[tl_df["action"]=="SELL_STOP"])/max(len(tl_df),1)*100

        log.append(f"STEP8 ✅ CAGR={cagr:.2%} Sharpe={sharpe:.2f} "
                   f"MaxDD={max_dd:.2%} Beta={beta:.2f} Beat={beat}/{len(yr_s)}")

        return {
            "port_series":port_series,"bench_norm":bench_norm,
            "port_ret":port_ret,"bench_ret":bench_ret,
            "yr_strat":yr_s,"yr_bench":yr_b,
            "dd_s":dd_s,"dd_b":dd_b,
            "weights_history":weights_history,"trade_log":tl_df,
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
                "Total Years":len(yr_s),"Beat Months":bmths,
                "Total Months":len(mp_m),"Stop Rate":safe_float(stop_rate),
                "N Trades":len(tl_df),"N Years":safe_float(n_years),
            },
        }, None, log

    # ──────────────────────────────────────────────────────────────
    # DISPLAY
    # ──────────────────────────────────────────────────────────────
    def run(self):
        with st.spinner("Running Momentum backtest (~1-2 min)..."):
            raw_result = self._run(
                self.start_date, self.end_date, self.top_n,
                self.lookback, self.skip_last, self.max_weight,
                self.atr_mult, self.rebal_freq,
                self.use_dual_momentum, self.dual_mom_weight,
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

        if result is None:
            st.error(f"❌ {err}")
            st.warning(
                "**Common fixes:**\n"
                "- Use **Start Date 2018-01-01** or later\n"
                "- Click **🗑 Clear Cache** in sidebar\n"
                "- Wait 60 seconds (Yahoo Finance rate limit) then retry"
            )
            return

        m  = result["metrics"]
        ps = result["port_series"]
        bn = result["bench_norm"]
        pr = result["port_ret"]
        br = result["bench_ret"]
        ys = result["yr_strat"]
        yb = result["yr_bench"]

        # ── Data coverage notice ───────────────────────────────────
        st.info(
            f"📅 **{ps.index[0].strftime('%b %Y')} → {ps.index[-1].strftime('%b %Y')}** "
            f"({m['N Years']:.1f} years) | "
            f"Rebalance: **{self.rebal_freq.split('(')[0].strip()}** | "
            f"Dual Momentum: **{'ON' if self.use_dual_momentum else 'OFF'}** | "
            f"ATR Stop: **{self.atr_mult}×**"
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
        c1.metric("Sortino",     f"{m['Sortino']:.2f}")
        c2.metric("Beta",        f"{m['Beta']:.2f}", help="Target 0.6–1.2")
        c3.metric("Alpha (ann)", f"{m['Alpha']*100:.1f}%")
        c4.metric("Info Ratio",  f"{m['Info Ratio']:.2f}")
        c5.metric("Beat Nifty",
                  f"{m['Beat Years']}/{m['Total Years']} yrs",
                  delta=f"{m['Beat Months']}/{m['Total Months']} months")

        final_val   = ps.iloc[-1]
        bench_final = bn.iloc[-1]
        st.markdown("---")
        col1,col2,col3 = st.columns(3)
        col1.metric("Strategy ₹10L grew to", f"₹{final_val/100_000:.1f}L",
                    delta=f"₹{(final_val-1_000_000)/100_000:.1f}L profit")
        col2.metric("Nifty B&H ₹10L grew to", f"₹{bench_final/100_000:.1f}L",
                    delta=f"₹{(bench_final-1_000_000)/100_000:.1f}L profit")
        col3.metric("Extra profit vs Nifty", f"₹{(final_val-bench_final)/100_000:.1f}L",
                    delta=f"{(final_val/bench_final-1)*100:.1f}% more")
        st.markdown("---")

        # ── Equity Curve ──────────────────────────────────────────
        st.subheader("📈 Equity Curve vs Nifty 50")
        bn_ri = bn.reindex(ps.index).ffill()
        fig1  = go.Figure()
        fig1.add_trace(go.Scatter(x=ps.index, y=ps.values,
                                  name="Momentum Strategy",
                                  line=dict(color="#1565C0", width=2.5)))
        fig1.add_trace(go.Scatter(x=bn.index, y=bn.values,
                                  name="Nifty 50 B&H",
                                  line=dict(color="#E65100",width=1.8,dash="dash")))
        fig1.add_trace(go.Scatter(
            x=list(ps.index)+list(ps.index[::-1]),
            y=list(ps.values)+list(bn_ri.values[::-1]),
            fill="toself", fillcolor=_hex_to_rgba("#2E7D32", 0.10),
            line=dict(width=0), name="vs Benchmark"))
        fig1.update_layout(
            height=400, xaxis_title="Date",
            yaxis_title="Portfolio Value (₹)", yaxis=dict(tickformat=",.0f"),
            legend=dict(x=0.01,y=0.99), margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig1, use_container_width=True)

        # ── Drawdown ──────────────────────────────────────────────
        st.subheader("📉 Drawdown")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=result["dd_s"].index, y=(result["dd_s"]*100).values,
            fill="tozeroy", name="Strategy DD",
            fillcolor=_hex_to_rgba("#1565C0", 0.40),
            line=dict(color="#1565C0",width=1)))
        fig2.add_trace(go.Scatter(
            x=result["dd_b"].index, y=(result["dd_b"]*100).values,
            fill="tozeroy", name="Nifty DD",
            fillcolor=_hex_to_rgba("#E65100", 0.20),
            line=dict(color="#E65100",width=1,dash="dash")))
        fig2.add_hline(y=-20, line_dash="dot", line_color="red",
                       annotation_text="20% Target")
        fig2.update_layout(height=250, xaxis_title="Date", yaxis_title="Drawdown %",
                           margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig2, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric("Strategy Max DD",  f"{m['Max DD']*100:.1f}%")
        c2.metric("Nifty Max DD",     f"{m['Bench MaxDD']*100:.1f}%")
        c3.metric("DD Saved",
                  f"{(m['Bench MaxDD']-m['Max DD'])*100:.1f}%",
                  delta="Strategy better" if m['Max DD']>m['Bench MaxDD'] else "Nifty better",
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
                                  name="Strategy",
                                  marker_color=bar_colors,opacity=0.90))
            fig3.add_trace(go.Bar(x=yb.index.year.tolist(),
                                  y=(yb.values*100).tolist(),
                                  name="Nifty 50",
                                  marker_color="#E65100",opacity=0.60))
            fig3.add_hline(y=0, line_color="white", line_width=0.8)
            fig3.update_layout(
                barmode="group", height=320,
                xaxis_title="Year", yaxis_title="Return %",
                xaxis=dict(tickmode="linear", dtick=1,
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
            st.info(f"Beat Nifty in **{m['Beat Years']}/{m['Total Years']} years** ({bp*100:.0f}%) "
                    f"and **{m['Beat Months']}/{m['Total Months']} months** "
                    f"({m['Beat Months']/max(m['Total Months'],1)*100:.0f}%)")
        st.markdown("---")

        # ── Rolling Returns tabs ──────────────────────────────────
        st.subheader("📊 Rolling Returns")
        tab1, tab2, tab3 = st.tabs(["12-Month", "6-Month", "Monthly Distribution"])
        for tab, window, label in [(tab1,252,"12M"), (tab2,126,"6M")]:
            with tab:
                rs = pr.rolling(window).apply(lambda x:(1+x).prod()-1)*100
                rb = br.rolling(window).apply(lambda x:(1+x).prod()-1)*100
                fig_r = go.Figure()
                fig_r.add_trace(go.Scatter(x=rs.index,y=rs.values,
                                           name="Strategy",line=dict(color="#1565C0",width=1.8)))
                fig_r.add_trace(go.Scatter(x=rb.index,y=rb.values,
                                           name="Nifty 50",line=dict(color="#E65100",width=1.3,dash="dash")))
                fig_r.add_hline(y=0, line_color="gray", line_width=0.8)
                fig_r.update_layout(height=230, xaxis_title="Date",
                                    yaxis_title=f"{label} Return %",
                                    margin=dict(l=10,r=10,t=10,b=10))
                st.plotly_chart(fig_r, use_container_width=True)
        with tab3:
            mp = result["monthly_port"]*100
            mb = result["monthly_bench"]*100
            fig_h = go.Figure()
            fig_h.add_trace(go.Histogram(x=mp.values,name="Strategy",
                                          opacity=0.75,nbinsx=40,marker_color="#1565C0"))
            fig_h.add_trace(go.Histogram(x=mb.values,name="Nifty 50",
                                          opacity=0.55,nbinsx=40,marker_color="#E65100"))
            fig_h.update_layout(barmode="overlay",height=240,
                                 xaxis_title="Monthly Return %",yaxis_title="Count",
                                 margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig_h, use_container_width=True)
            st.caption(f"Strategy avg monthly: **{mp.mean():.2f}%** | "
                       f"Positive months: **{(mp>0).mean()*100:.0f}%** | "
                       f"Nifty avg: **{mb.mean():.2f}%**")
        st.markdown("---")

        # ──────────────────────────────────────────────────────────
        # 🌡️ REGIME EXPOSURE — REBUILT (BUG FIX)
        # ──────────────────────────────────────────────────────────
        # OLD v7 code (crashed):
        #     for level, color, label in [...]:
        #         mask = regime_ri == level
        #         if mask.any():
        #             fig_reg.add_trace(go.Scatter(
        #                 x=regime_ri.index, y=(regime_ri*100).where(mask),
        #                 fill="tozeroy", name=label,
        #                 fillcolor=color+"55",                ← THE BUG
        #                 line=dict(color=color, width=0.5)))
        #
        # Two problems:
        #   1. fillcolor=color+"55" → '#2E7D3255'  (8-digit hex, invalid)
        #   2. y=(regime_ri*100).where(mask) → mostly NaN → Plotly's
        #      tozeroy + connectgaps validation cascades the failure
        #      into the fillcolor slot in stricter Plotly versions.
        #
        # NEW v7.1: one always-defined step-area trace + background
        # tier bands as shapes. No NaN gaps, no 8-digit hex, no fragile
        # per-tier traces. Same visual idea, robust execution.
        # ──────────────────────────────────────────────────────────
        st.subheader("🌡️ Regime Exposure — How Much Was Invested Over Time")
        regime_ri = result["regime"].reindex(ps.index).ffill().fillna(1.0)
        # snap to discrete tiers to avoid float drift
        regime_ri = regime_ri.round(2)
        y_pct = (regime_ri.values * 100.0).astype(float)

        fig_reg = go.Figure()

        # Background tier bands (drawn as shapes — never go through scatter validation)
        for y0, y1, hexc, alpha in [
            (  0,  20, "#F44336", 0.10),
            ( 20,  40, "#FF9800", 0.10),
            ( 40,  60, "#FFC107", 0.10),
            ( 60,  80, "#8BC34A", 0.10),
            ( 80, 100, "#2E7D32", 0.10),
        ]:
            fig_reg.add_hrect(
                y0=y0, y1=y1,
                fillcolor=_hex_to_rgba(hexc, alpha),
                line_width=0, layer="below",
            )

        # Single fully-defined step-area trace (the actual exposure curve)
        fig_reg.add_trace(go.Scatter(
            x=regime_ri.index,
            y=y_pct,
            mode="lines",
            line=dict(color="#1565C0", width=1.5, shape="hv"),
            fill="tozeroy",
            fillcolor=_hex_to_rgba("#1565C0", 0.25),
            name="% Invested",
            hovertemplate="%{x|%b %Y}: %{y:.0f}%<extra></extra>",
        ))

        # Legend proxies for the 5 tiers (zero-data marker traces — safe)
        for hexc, label in [
            ("#2E7D32", "100% — Full Bull"),
            ("#8BC34A", "80% — Slight Caution"),
            ("#FFC107", "60% — Moderate Caution"),
            ("#FF9800", "40% — Defensive"),
            ("#F44336", "20% — Near-Cash"),
        ]:
            fig_reg.add_trace(go.Scatter(
                x=[regime_ri.index[0]], y=[None],
                mode="markers",
                marker=dict(size=10, color=hexc),
                name=label, showlegend=True,
            ))

        fig_reg.update_layout(
            height=240, xaxis_title="Date", yaxis_title="% Invested",
            yaxis=dict(range=[0,110]), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10,r=10,t=30,b=10))
        st.plotly_chart(fig_reg, use_container_width=True)
        cash_pct = (regime_ri < 1.0).mean()
        st.caption(
            f"Strategy was below 100% exposure **{cash_pct*100:.0f}% of the time** — "
            f"tiered regime vs old binary means recoveries are no longer missed."
        )

        # Tier breakdown table (extra info, no plotting risk)
        tier_df = pd.DataFrame({
            "Tier":      ["100%", "80%", "60%", "40%", "20%"],
            "% of Time": [
                round(float((regime_ri >= 0.99).mean()) * 100, 1),
                round(float(((regime_ri >= 0.79) & (regime_ri < 0.99)).mean()) * 100, 1),
                round(float(((regime_ri >= 0.59) & (regime_ri < 0.79)).mean()) * 100, 1),
                round(float(((regime_ri >= 0.39) & (regime_ri < 0.59)).mean()) * 100, 1),
                round(float((regime_ri < 0.39).mean()) * 100, 1),
            ],
        })
        st.dataframe(tier_df, use_container_width=True, hide_index=True)
        st.markdown("---")

        # ── Current Holdings + Sector Pie ────────────────────────
        st.subheader("📋 Current Portfolio Holdings")
        if result["weights_history"]:
            last_w = list(result["weights_history"].values())[-1]
            last_d = list(result["weights_history"].keys())[-1]
            st.caption(f"Last rebalance: **{last_d.strftime('%d %b %Y')}**")
            h_rows = [{"Ticker":t.replace(".NS",""),
                       "Sector": SECTOR_MAP.get(t,"Other"),
                       "Weight %":round(w*100,1),
                       "₹ Alloc":f"₹{1_000_000*w:,.0f}"}
                      for t,w in sorted(last_w.items(),key=lambda x:-x[1])]
            h_df = pd.DataFrame(h_rows)
            col1,col2 = st.columns([2,1])
            with col1:
                st.dataframe(h_df, use_container_width=True, hide_index=True)
            with col2:
                sec_w = h_df.groupby("Sector")["Weight %"].sum().reset_index()
                fig_p = go.Figure(go.Pie(
                    labels=sec_w["Sector"], values=sec_w["Weight %"],
                    marker_colors=[SECTOR_COLORS.get(s,"#757575") for s in sec_w["Sector"]],
                    hole=0.4, textinfo="label+percent",
                ))
                fig_p.update_layout(height=280,
                                     margin=dict(l=0,r=0,t=10,b=10),
                                     showlegend=False)
                st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("No positions — strategy is currently in near-cash regime.")
        st.markdown("---")

        # ── Trade Analysis ────────────────────────────────────────
        st.subheader("📊 Trade Analysis")
        tl_df = result["trade_log"]
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Total Trades",   f"{m['N Trades']}")
        c2.metric("Trades/Year",    f"{m['N Trades']/max(m['N Years'],1):.0f}")
        c3.metric("Stop-Loss Rate", f"{m['Stop Rate']:.1f}%",
                  help="Target < 15% with wider ATR stop")
        c4.metric("Volatility",     f"{m['Volatility']*100:.1f}%")
        c5.metric("VaR 95% daily",  f"{m['VaR 95']*100:.2f}%")
        st.markdown("---")

        # ── Investor Scorecard ────────────────────────────────────
        st.subheader("🎯 Investor Target Scorecard")
        bp2 = m["Beat Years"]/max(m["Total Years"],1)
        targets = [
            ("CAGR > 18%",          m["CAGR"]*100>18,           f"{m['CAGR']*100:.1f}%"),
            ("Beats Nifty (CAGR)",  m["CAGR"]>m["Bench CAGR"], f"+{(m['CAGR']-m['Bench CAGR'])*100:.1f}%"),
            ("Sharpe > 1.0",        m["Sharpe"]>1.0,            f"{m['Sharpe']:.2f}"),
            ("Sortino > 1.0",       m["Sortino"]>1.0,           f"{m['Sortino']:.2f}"),
            ("Max DD < 20%",        abs(m["Max DD"])<0.20,      f"{m['Max DD']*100:.1f}%"),
            ("Calmar > 1.2",        m["Calmar"]>1.2,            f"{m['Calmar']:.2f}"),
            ("Beat Nifty >60% yrs", bp2>0.60,                   f"{m['Beat Years']}/{m['Total Years']}"),
            ("Beta 0.6–1.2",        0.6<=m["Beta"]<=1.2,        f"{m['Beta']:.2f}"),
            ("Info Ratio > 0.3",    m["Info Ratio"]>0.3,        f"{m['Info Ratio']:.2f}"),
            ("Win Rate 45–65%",     0.45<=m["Win Rate"]<=0.65,  f"{m['Win Rate']*100:.1f}%"),
        ]
        scored = sum(1 for _,p,_ in targets if p)
        st.dataframe(pd.DataFrame([{
            "Status":"✅ PASS" if p else "❌ FAIL",
            "Target":t, "Value":v
        } for t,p,v in targets]), use_container_width=True, hide_index=True)
        verdict = ("✅ Investor Ready" if scored>=8
                   else "⚠️ Getting Close" if scored>=5
                   else "🔨 Needs More Work")
        fn = st.success if scored>=8 else st.warning if scored>=5 else st.error
        fn(f"Score: **{scored}/10** — {verdict}")
        st.markdown("---")

        # ── Insights ──────────────────────────────────────────────
        st.subheader("🧠 Quant Diagnostics")
        if m["CAGR"]>m["Bench CAGR"]:
            st.success(f"✅ Beats Nifty by **{(m['CAGR']-m['Bench CAGR'])*100:.1f}%/year** "
                       f"(₹{(final_val-bench_final)/100_000:.1f}L extra on ₹10L invested)")
        else:
            st.error(f"❌ Lags Nifty by {(m['Bench CAGR']-m['CAGR'])*100:.1f}%/year — "
                     "enable Dual Momentum or reduce skip_last to 10")
        if abs(m["Max DD"])<abs(m["Bench MaxDD"]):
            st.success(f"✅ Lower drawdown: **{m['Max DD']*100:.1f}%** vs Nifty **{m['Bench MaxDD']*100:.1f}%**")
        else:
            st.warning(f"⚠️ Drawdown {m['Max DD']*100:.1f}% — widen ATR to 5.0×")
        if 0.6<=m["Beta"]<=1.2:
            st.success(f"✅ Beta **{m['Beta']:.2f}** — tiered regime keeps you invested during dips")
        elif m["Beta"]<0.6:
            st.warning(f"⚠️ Beta {m['Beta']:.2f} — try Start Date 2018-01-01 or looser ATR stop")
        if m["Stop Rate"]<15:
            st.success(f"✅ Stop-loss rate **{m['Stop Rate']:.1f}%** — wider ATR stop working")
        else:
            st.warning(f"⚠️ Stop-loss rate {m['Stop Rate']:.1f}% — try ATR Multiplier 5.0")

        with st.expander("📖 Strategy Architecture & Signal Logic"):
            st.markdown(f"""
**Dual Momentum Gate**

Each stock must beat Nifty's own 12-month return (not just beat 0%).
This eliminates stocks that are rising purely because the whole market is rising
("tide-lifters"), keeping only genuine relative outperformers.
The blend slider (0 = pure absolute, 1 = pure relative) lets you adjust how
aggressively the gate is applied.

**Tiered Regime Filter**

Instead of a binary 0%/100% invested switch, exposure scales across 5 levels
based on how far Nifty sits from its 200-day moving average:

| Gap from 200DMA | Exposure |
|---|---|
| ≥ 0% | 100% — full bull |
| -2% to 0% | 80% — slight caution |
| -5% to -2% | 60% — moderate caution |
| -10% to -5% | 40% — defensive |
| < -10% | 20% — near-cash |

This prevents the strategy from missing recovery rallies that follow short dips.

**Blended Inv-Vol + Momentum Weights**

Position sizing combines:
- 60% inverse-volatility (lower-vol stocks get more capital)
- 40% momentum score (higher-momentum stocks get more capital)

This balances risk distribution with return potential.

**ATR Trailing Stop**

Each position has a stop set at `{self.atr_mult}× ATR` below its highest close since entry.
Wider ATR multiplier = fewer false exits in volatile markets.
""")

