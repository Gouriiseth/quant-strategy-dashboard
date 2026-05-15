import streamlit as st
import importlib
import pkgutil
import strategies
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from strategies.base import BaseStrategy

st.set_page_config(layout="wide", page_title="Nifty 50 Strategy Analyzer")

# ---------------------------------------------------------------
# NIFTY 50 UNIVERSE + SECTOR MAP  (used by landing dashboard)
# ---------------------------------------------------------------
NIFTY50_TICKERS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS",
    "HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS",
    "LT.NS","AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS","SUNPHARMA.NS",
    "WIPRO.NS","HCLTECH.NS","POWERGRID.NS","NTPC.NS","ONGC.NS",
    "TATAMOTORS.NS","TATASTEEL.NS","TECHM.NS","COALINDIA.NS",
    "DRREDDY.NS","EICHERMOT.NS","CIPLA.NS","GRASIM.NS",
    "INDUSINDBK.NS","HINDALCO.NS","BRITANNIA.NS","BAJAJ-AUTO.NS",
    "HEROMOTOCO.NS","M&M.NS","ADANIPORTS.NS","BAJFINANCE.NS",
    "ULTRACEMCO.NS","NESTLEIND.NS","TITAN.NS","BAJAJFINSV.NS",
    "DIVISLAB.NS","SBILIFE.NS","HDFCLIFE.NS","APOLLOHOSP.NS",
    "TATACONSUM.NS","JSWSTEEL.NS","ADANIENT.NS","BEL.NS",
    "SHRIRAMFIN.NS","TRENT.NS",
]

SECTOR_MAP = {
    "HDFCBANK.NS":"Financials","ICICIBANK.NS":"Financials","KOTAKBANK.NS":"Financials",
    "AXISBANK.NS":"Financials","SBIN.NS":"Financials","INDUSINDBK.NS":"Financials",
    "BAJFINANCE.NS":"Financials","BAJAJFINSV.NS":"Financials","SBILIFE.NS":"Financials",
    "HDFCLIFE.NS":"Financials","SHRIRAMFIN.NS":"Financials",
    "TCS.NS":"IT","INFY.NS":"IT","WIPRO.NS":"IT","HCLTECH.NS":"IT","TECHM.NS":"IT",
    "RELIANCE.NS":"Energy","ONGC.NS":"Energy","COALINDIA.NS":"Energy",
    "POWERGRID.NS":"Energy","NTPC.NS":"Energy",
    "HINDUNILVR.NS":"Staples","ITC.NS":"Staples","NESTLEIND.NS":"Staples",
    "BRITANNIA.NS":"Staples","TATACONSUM.NS":"Staples",
    "MARUTI.NS":"Auto","TATAMOTORS.NS":"Auto","EICHERMOT.NS":"Auto",
    "BAJAJ-AUTO.NS":"Auto","HEROMOTOCO.NS":"Auto","M&M.NS":"Auto",
    "LT.NS":"Industrials","ADANIPORTS.NS":"Industrials","ADANIENT.NS":"Industrials","BEL.NS":"Industrials",
    "JSWSTEEL.NS":"Materials","TATASTEEL.NS":"Materials","HINDALCO.NS":"Materials",
    "ULTRACEMCO.NS":"Materials","GRASIM.NS":"Materials",
    "SUNPHARMA.NS":"Healthcare","DRREDDY.NS":"Healthcare","CIPLA.NS":"Healthcare",
    "DIVISLAB.NS":"Healthcare","APOLLOHOSP.NS":"Healthcare",
    "ASIANPAINT.NS":"ConsDisc","TITAN.NS":"ConsDisc","TRENT.NS":"ConsDisc",
    "BHARTIARTL.NS":"Telecom",
}

SECTOR_COLORS = {
    "Financials":"#1565C0","IT":"#6A1B9A","Energy":"#E65100",
    "Staples":"#2E7D32","Auto":"#F9A825","Industrials":"#4E342E",
    "Materials":"#546E7A","Healthcare":"#00695C","ConsDisc":"#AD1457",
    "Telecom":"#283593","Other":"#757575",
}

TICKER_LABEL = {t: t.replace(".NS", "") for t in NIFTY50_TICKERS}


# ---------------------------------------------------------------
# MARKET REGIME INDICATOR
# ---------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_market_regime():
    try:
        nifty = yf.download("^NSEI", period="1y", auto_adjust=True, progress=False)
        nifty.columns = nifty.columns.get_level_values(0)
        nifty = nifty["Close"].dropna()

        current = nifty.iloc[-1]
        ma200 = nifty.rolling(200).mean().iloc[-1]
        prev = nifty.iloc[-2]

        gap_pct = ((current - ma200) / ma200) * 100
        day_change = ((current - prev) / prev) * 100

        if gap_pct > 5:
            strength = "Strong Uptrend"
        elif gap_pct > 0:
            strength = "Weak Uptrend"
        elif gap_pct > -5:
            strength = "Weak Downtrend"
        else:
            strength = "Strong Downtrend"

        return {
            "bullish": bool(current > ma200),
            "current": round(float(current), 2),
            "ma200": round(float(ma200), 2),
            "gap_pct": round(float(gap_pct), 2),
            "day_change": round(float(day_change), 2),
            "strength": strength,
            "high_52w": round(float(nifty.rolling(252).max().iloc[-1]), 2),
            "low_52w": round(float(nifty.rolling(252).min().iloc[-1]), 2),
        }
    except Exception:
        return None


def show_regime_banner():
    regime = get_market_regime()

    if regime is None:
        st.warning("Could not fetch market regime data")
        return

    if regime["bullish"]:
        bg = "linear-gradient(90deg, #0d3b1e, #145a32)"
        border = "#2ecc71"
        label = "🟢 BULLISH REGIME"
        status = "FULLY ACTIVE"
        status_color = "#2ecc71"
        muted = "#a9dfbf"
        gap_color = "#2ecc71"
        gap_prefix = "+"
        desc = "Nifty is above its 200-day average. Market is healthy. Trend & Momentum strategies are fully deployed."
        desc_color = "#d5f5e3"
    else:
        bg = "linear-gradient(90deg, #3b0d0d, #5a1414)"
        border = "#e74c3c"
        label = "🔴 BEARISH REGIME"
        status = "CAPITAL PROTECTION MODE"
        status_color = "#e74c3c"
        muted = "#f1948a"
        gap_color = "#e74c3c"
        gap_prefix = ""
        desc = "Nifty is below its 200-day average. Market is weak. Strategies are reducing positions to protect capital."
        desc_color = "#fadbd8"

    day_arrow = "▲" if regime["day_change"] >= 0 else "▼"
    day_color = "#2ecc71" if regime["day_change"] >= 0 else "#e74c3c"

    st.markdown(f"""
    <div style="background:{bg}; border-left:6px solid {border};
                border-radius:10px; padding:18px 24px; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
                <span style="font-size:22px; font-weight:800; color:{border};">{label}</span>
                <span style="color:{muted}; font-size:14px; margin-left:12px;">{regime['strength']}</span>
            </div>
            <div style="color:{muted}; font-size:13px;">
                Strategy Status: <strong style="color:{status_color};">{status}</strong>
            </div>
        </div>
        <div style="display:flex; gap:40px; margin-top:12px; flex-wrap:wrap;">
            <div>
                <div style="color:{muted}; font-size:11px;">NIFTY 50</div>
                <div style="color:white; font-size:18px; font-weight:700;">
                    {regime['current']:,}
                    <span style="font-size:13px; color:{day_color};">
                        {day_arrow} {abs(regime['day_change'])}%
                    </span>
                </div>
            </div>
            <div>
                <div style="color:{muted}; font-size:11px;">200-DAY MA</div>
                <div style="color:white; font-size:18px; font-weight:700;">{regime['ma200']:,}</div>
            </div>
            <div>
                <div style="color:{muted}; font-size:11px;">GAP FROM MA</div>
                <div style="color:{gap_color}; font-size:18px; font-weight:700;">
                    {gap_prefix}{regime['gap_pct']}%
                </div>
            </div>
            <div style="max-width:320px;">
                <div style="color:{muted}; font-size:11px;">WHAT THIS MEANS</div>
                <div style="color:{desc_color}; font-size:13px;">{desc}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------
# LANDING DASHBOARD — Nifty 50 Market Overview
# ---------------------------------------------------------------
@st.cache_data(ttl=1800)
def get_nifty50_snapshot():
    """
    Returns a DataFrame with ticker, label, sector, 1-day return,
    1-month return, and whether price is above 200DMA.
    Downloads all Nifty 50 stocks for the last ~14 months.
    """
    try:
        raw = yf.download(
            NIFTY50_TICKERS, period="14mo",
            auto_adjust=True, progress=False, group_by="ticker"
        )
        rows = []
        for ticker in NIFTY50_TICKERS:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    close = raw[ticker]["Close"].dropna()
                else:
                    close = raw["Close"].dropna()
                if len(close) < 5:
                    continue
                day_ret  = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
                mo_ret   = float((close.iloc[-1] - close.iloc[-22]) / close.iloc[-22] * 100) if len(close) >= 22 else np.nan
                ma200    = close.rolling(200).mean().iloc[-1]
                above    = bool(close.iloc[-1] > ma200) if not np.isnan(ma200) else None
                rows.append({
                    "Ticker":  ticker,
                    "Label":   TICKER_LABEL[ticker],
                    "Sector":  SECTOR_MAP.get(ticker, "Other"),
                    "1D %":    round(day_ret, 2),
                    "1M %":    round(mo_ret, 2) if not np.isnan(mo_ret) else None,
                    "Above200": above,
                })
            except Exception:
                continue
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


def show_market_dashboard():
    st.markdown("### 📊 Nifty 50 — Live Market Overview")
    st.caption("Data refreshes every 30 minutes. Select a strategy from the sidebar to run a backtest.")

    with st.spinner("Loading market data…"):
        df = get_nifty50_snapshot()

    if df.empty:
        st.warning("Could not load market data. Please check your connection.")
        return

    regime = get_market_regime()

    # ── Row 1: Key metrics ──────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    above_count = int(df["Above200"].sum()) if "Above200" in df else 0
    below_count = len(df) - above_count
    avg_1d = df["1D %"].mean()
    avg_1m = df["1M %"].dropna().mean()

    m1.metric("Nifty 50", f"{regime['current']:,}" if regime else "—",
              delta=f"{regime['day_change']:+.2f}%" if regime else None)
    m2.metric("200-Day MA", f"{regime['ma200']:,}" if regime else "—")
    m3.metric("Stocks Above 200DMA", f"{above_count} / {len(df)}")
    m4.metric("Avg 1-Day Return", f"{avg_1d:+.2f}%")
    m5.metric("Avg 1-Month Return", f"{avg_1m:+.2f}%")

    st.markdown("---")

    # ── Row 2: Top Gainers & Losers ────────────────────────────
    col_g, col_l = st.columns(2)

    df_sorted = df.sort_values("1D %", ascending=False).dropna(subset=["1D %"])
    gainers = df_sorted.head(5)[["Label", "Sector", "1D %"]].reset_index(drop=True)
    losers  = df_sorted.tail(5).iloc[::-1][["Label", "Sector", "1D %"]].reset_index(drop=True)

    def color_pct(val):
        color = "#2ecc71" if val >= 0 else "#e74c3c"
        return f'<span style="color:{color};font-weight:600;">{val:+.2f}%</span>'

    def build_mover_table(data, title, emoji):
        rows_html = ""
        for _, row in data.iterrows():
            sector_color = SECTOR_COLORS.get(row["Sector"], "#757575")
            rows_html += f"""
            <tr>
                <td style="padding:6px 10px;font-weight:600;">{row['Label']}</td>
                <td style="padding:6px 10px;">
                    <span style="background:{sector_color}22;color:{sector_color};
                                 border-radius:4px;padding:2px 7px;font-size:12px;">
                        {row['Sector']}
                    </span>
                </td>
                <td style="padding:6px 10px;text-align:right;">{color_pct(row['1D %'])}</td>
            </tr>"""
        return f"""
        <div style="border:1px solid #2a2a2a;border-radius:8px;overflow:hidden;margin-bottom:4px;">
            <div style="background:#1a1a1a;padding:10px 14px;font-size:14px;font-weight:700;">
                {emoji} {title}
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <thead>
                    <tr style="border-bottom:1px solid #2a2a2a;">
                        <th style="padding:6px 10px;text-align:left;color:#888;">Stock</th>
                        <th style="padding:6px 10px;text-align:left;color:#888;">Sector</th>
                        <th style="padding:6px 10px;text-align:right;color:#888;">1D Change</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>"""

    with col_g:
        st.markdown(build_mover_table(gainers, "Top Gainers Today", "🟢"), unsafe_allow_html=True)
    with col_l:
        st.markdown(build_mover_table(losers, "Top Losers Today", "🔴"), unsafe_allow_html=True)

    st.markdown("---")

    # ── Row 3: Sector Heatmap + Market Breadth ─────────────────
    col_sec, col_breadth = st.columns([3, 2])

    with col_sec:
        st.markdown("#### 🗂 Sector Performance — 1 Month")
        sec_df = (
            df.dropna(subset=["1M %"])
            .groupby("Sector")["1M %"]
            .mean()
            .reset_index()
            .sort_values("1M %", ascending=False)
        )
        bar_colors = [
            "#2ecc71" if v >= 0 else "#e74c3c"
            for v in sec_df["1M %"]
        ]
        fig_sec = go.Figure(go.Bar(
            x=sec_df["Sector"],
            y=sec_df["1M %"],
            marker_color=bar_colors,
            text=[f"{v:+.1f}%" for v in sec_df["1M %"]],
            textposition="outside",
            hovertemplate="%{x}: %{y:+.2f}%<extra></extra>",
        ))
        fig_sec.update_layout(
            height=280,
            margin=dict(l=0, r=0, t=10, b=10),
            xaxis_title=None,
            yaxis_title="Avg Return %",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=12),
        )
        fig_sec.update_yaxes(showgrid=True, gridcolor="#2a2a2a", zeroline=True, zerolinecolor="#555")
        st.plotly_chart(fig_sec, use_container_width=True)

    with col_breadth:
        st.markdown("#### 📡 Market Breadth — Stocks Above 200DMA")
        breadth_df = df.dropna(subset=["Above200"])
        above_n = int(breadth_df["Above200"].sum())
        below_n = int((~breadth_df["Above200"]).sum())

        fig_b = go.Figure(go.Pie(
            labels=["Above 200DMA", "Below 200DMA"],
            values=[above_n, below_n],
            marker_colors=["#2ecc71", "#e74c3c"],
            hole=0.55,
            textinfo="label+value",
            hovertemplate="%{label}: %{value} stocks<extra></extra>",
        ))
        fig_b.update_layout(
            height=280,
            margin=dict(l=0, r=0, t=10, b=10),
            showlegend=False,
            annotations=[dict(
                text=f"{above_n}/{above_n + below_n}",
                x=0.5, y=0.5, font_size=20, showarrow=False,
                font=dict(color="#2ecc71" if above_n > below_n else "#e74c3c", weight=700),
            )],
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_b, use_container_width=True)

        # 52-week position
        if regime:
            h52 = regime.get("high_52w", 0)
            l52 = regime.get("low_52w", 0)
            cur = regime["current"]
            if h52 > l52:
                pos_pct = round((cur - l52) / (h52 - l52) * 100, 1)
                st.markdown(
                    f"<div style='font-size:13px;color:#aaa;margin-top:4px;'>"
                    f"<b>52-Week Range</b><br>"
                    f"Low: {l52:,} &nbsp;|&nbsp; High: {h52:,}<br>"
                    f"Current position: <b style='color:#fff;'>{pos_pct}%</b> of range"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.markdown("---")

    # ── Row 4: Available Strategies ────────────────────────────
    st.markdown("#### 📂 Available Strategies")
    st.caption("Select a strategy from the sidebar to configure and run a backtest.")
    for name, cls in ALL_STRATEGIES.items():
        st.markdown(f"- **{name}** — {cls.DESCRIPTION}")


# ---------------------------------------------------------------
# AUTO-DISCOVER ALL STRATEGIES
# ---------------------------------------------------------------
def load_all_strategies():
    found = {}
    for _, module_name, _ in pkgutil.iter_modules(strategies.__path__):
        if module_name in ("base",):
            continue
        try:
            module = importlib.import_module(f"strategies.{module_name}")
            # Only keep modules that contain a real BaseStrategy subclass
            has_strategy = False
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseStrategy)
                    and obj is not BaseStrategy
                ):
                    found[obj.NAME] = obj
                    has_strategy = True
            # Silently skip modules that have no strategy class
            # (e.g. standalone research scripts)
        except ImportError as e:
            # Only show warning if it looks like an intended strategy
            # (has 'strategy' or 'Strategy' in name) — skip standalone scripts
            if "strategy" in module_name.lower():
                st.sidebar.warning(f"Could not load {module_name}: {e}")
        except Exception as e:
            st.sidebar.warning(f"Could not load {module_name}: {e}")
    return found


ALL_STRATEGIES = load_all_strategies()

# ---------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------
st.sidebar.title("⚙️ Controls")

if not ALL_STRATEGIES:
    st.error("No strategies found in the strategies/ folder.")
    st.stop()

strategy_names = list(ALL_STRATEGIES.keys())

# Task 1 — No prefilled default; user must select explicitly
selected_strategy_name = st.sidebar.selectbox(
    "🎯 Select Strategy",
    strategy_names,
    index=None,
    placeholder="— Select a strategy —",
)

run = False
strategy_instance = None

if selected_strategy_name is not None:
    selected_class = ALL_STRATEGIES[selected_strategy_name]
    st.sidebar.caption(selected_class.DESCRIPTION)
    st.sidebar.markdown("---")

    strategy_instance = selected_class()
    strategy_instance.render_sidebar()

    st.sidebar.markdown("---")
    run = st.sidebar.button("🚀 Run Analysis")

# ---------------------------------------------------------------
# MAIN PAGE
# ---------------------------------------------------------------

# Inject CSS once — styles Streamlit's native spinner into a full-screen
# faded overlay with a centred green ring. No text, no labels.
st.markdown("""
<style>
/* Full-screen overlay when spinner is active */
div[data-testid="stSpinner"] {
    position: fixed !important;
    inset: 0 !important;
    z-index: 9999 !important;
    background: rgba(10, 10, 15, 0.78) !important;
    backdrop-filter: blur(3px) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    margin: 0 !important;
    padding: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
}
/* Hide whatever text the spinner normally shows */
div[data-testid="stSpinner"] p,
div[data-testid="stSpinner"] span {
    display: none !important;
}
/* Replace with a clean rotating ring */
div[data-testid="stSpinner"] > div {
    width: 64px !important;
    height: 64px !important;
    border: 5px solid #1a2e23 !important;
    border-top: 5px solid #2ecc71 !important;
    border-radius: 50% !important;
    background: transparent !important;
    animation: _ring 0.9s linear infinite !important;
    box-shadow: 0 0 24px rgba(46,204,113,0.18) !important;
}
@keyframes _ring {
    to { transform: rotate(360deg); }
}
</style>
""", unsafe_allow_html=True)

st.title("📊 Nifty 50 Strategy Analyzer")

# Regime banner — always visible at top
show_regime_banner()

if selected_strategy_name is not None:
    st.markdown(
        f"<p style='margin:4px 0 0 0; font-size:13px; color:#888;'>"
        f"Active Strategy: <strong style='color:#ccc;'>{selected_strategy_name}</strong>"
        f"</p><hr style='margin:10px 0;'>",
        unsafe_allow_html=True,
    )

# Wrap both branches in the same st.empty() so Streamlit properly replaces
# the dashboard content when switching to strategy view — prevents stale
# dashboard from bleeding through behind the spinners.
main_content = st.empty()

if run and strategy_instance is not None:
    with main_content.container():
        # st.spinner with a single non-breaking space activates the overlay
        # defined by the CSS above — no text visible, just the ring
        with st.spinner("\u200b"):
            strategy_instance.run()

else:
    with main_content.container():
        show_market_dashboard()
