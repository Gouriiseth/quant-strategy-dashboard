import streamlit as st
import importlib
import pkgutil
import strategies
import yfinance as yf
import pandas as pd
from strategies.base import BaseStrategy
# from base import BaseStrategy

st.set_page_config(layout="wide", page_title="Equity Strategy Analyzer")

# -------------------------------
# G:ARKET REGIME INDICATOR
# -------------------------------
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
            "strength": strength
        }
    except Exception as e:
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


# -------------------------------
# AUTO-DISCOVER ALL STRATEGIES
# -------------------------------
def load_all_strategies():
    found = {}
    for _, module_name, _ in pkgutil.iter_modules(strategies.__path__):
        if module_name in ("base",):
            continue
        try:
            module = importlib.import_module(f"strategies.{module_name}")
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseStrategy)
                    and obj is not BaseStrategy
                ):
                    found[obj.NAME] = obj
        except Exception as e:
            st.sidebar.warning(f"Could not load {module_name}: {e}")
    return found


ALL_STRATEGIES = load_all_strategies()

# -------------------------------
# SIDEBAR
# -------------------------------
st.sidebar.title("⚙️ Controls")

if not ALL_STRATEGIES:
    st.error("No strategies found in the strategies/ folder.")
    st.stop()

strategy_names = list(ALL_STRATEGIES.keys())
selected_strategy_name = st.sidebar.selectbox("🎯 Select Strategy", strategy_names)

selected_class = ALL_STRATEGIES[selected_strategy_name]
st.sidebar.caption(selected_class.DESCRIPTION)
st.sidebar.markdown("---")

strategy_instance = selected_class()
strategy_instance.render_sidebar()

st.sidebar.markdown("---")
run = st.sidebar.button("🚀 Run Analysis")

# -------------------------------
# MAIN PAGE
# -------------------------------
st.title("📊 Equity Strategy Analyzer")

# Regime banner — always visible at top
show_regime_banner()

st.caption(f"Active Strategy: **{selected_strategy_name}**")
st.markdown("---")

if run:
    strategy_instance.run()
else:
    st.info("Configure your strategy in the sidebar and click **Run Analysis**")
    st.markdown("### 📂 Available Strategies")
    for name, cls in ALL_STRATEGIES.items():
        st.markdown(f"- **{name}** — {cls.DESCRIPTION}")