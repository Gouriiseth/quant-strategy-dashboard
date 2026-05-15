import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from strategies.base import BaseStrategy


# ── Universe ─────────────────────────────────────────────────────────────────
NIFTY50_STOCKS = {
    "Reliance Industries": "RELIANCE.NS", "TCS": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS", "Infosys": "INFY.NS",
    "ICICI Bank": "ICICIBANK.NS", "Hindustan Unilever": "HINDUNILVR.NS",
    "ITC": "ITC.NS", "SBI": "SBIN.NS", "Bharti Airtel": "BHARTIARTL.NS",
    "Kotak Mahindra Bank": "KOTAKBANK.NS", "L&T": "LT.NS",
    "HCL Technologies": "HCLTECH.NS", "Asian Paints": "ASIANPAINT.NS",
    "Axis Bank": "AXISBANK.NS", "Bajaj Finance": "BAJFINANCE.NS",
    "Maruti Suzuki": "MARUTI.NS", "Sun Pharma": "SUNPHARMA.NS",
    "Titan Company": "TITAN.NS", "Wipro": "WIPRO.NS",
    "Nestle India": "NESTLEIND.NS", "UltraTech Cement": "ULTRACEMCO.NS",
    "Power Grid": "POWERGRID.NS", "NTPC": "NTPC.NS",
    "Tech Mahindra": "TECHM.NS", "JSW Steel": "JSWSTEEL.NS",
    "Tata Steel": "TATASTEEL.NS", "Tata Motors": "TATAMOTORS.NS",
    "ONGC": "ONGC.NS", "Bajaj Auto": "BAJAJ-AUTO.NS",
    "Bajaj Finserv": "BAJAJFINSV.NS", "Adani Ports": "ADANIPORTS.NS",
    "Adani Enterprises": "ADANIENT.NS", "Coal India": "COALINDIA.NS",
    "Cipla": "CIPLA.NS", "Eicher Motors": "EICHERMOT.NS",
    "Hindalco": "HINDALCO.NS", "IndusInd Bank": "INDUSINDBK.NS",
    "Britannia": "BRITANNIA.NS", "Dr Reddys": "DRREDDY.NS",
    "Grasim Industries": "GRASIM.NS", "Hero MotoCorp": "HEROMOTOCO.NS",
    "Divi's Labs": "DIVISLAB.NS", "Apollo Hospitals": "APOLLOHOSP.NS",
    "SBI Life Insurance": "SBILIFE.NS", "HDFC Life Insurance": "HDFCLIFE.NS",
    "Tata Consumer": "TATACONSUM.NS", "LTIMindtree": "LTIM.NS",
    "BEL": "BEL.NS", "Shriram Finance": "SHRIRAMFIN.NS", "Trent": "TRENT.NS",
}

SECTOR_MAP = {
    "HDFCBANK.NS": "Financials", "ICICIBANK.NS": "Financials",
    "KOTAKBANK.NS": "Financials", "AXISBANK.NS": "Financials",
    "SBIN.NS": "Financials", "INDUSINDBK.NS": "Financials",
    "BAJFINANCE.NS": "Financials", "BAJAJFINSV.NS": "Financials",
    "SBILIFE.NS": "Financials", "HDFCLIFE.NS": "Financials",
    "SHRIRAMFIN.NS": "Financials",
    "TCS.NS": "IT", "INFY.NS": "IT", "WIPRO.NS": "IT",
    "HCLTECH.NS": "IT", "TECHM.NS": "IT",
    "RELIANCE.NS": "Energy", "ONGC.NS": "Energy",
    "COALINDIA.NS": "Energy", "POWERGRID.NS": "Energy", "NTPC.NS": "Energy",
    "HINDUNILVR.NS": "Staples", "ITC.NS": "Staples", "NESTLEIND.NS": "Staples",
    "BRITANNIA.NS": "Staples", "TATACONSUM.NS": "Staples",
    "MARUTI.NS": "Auto", "TATAMOTORS.NS": "Auto", "EICHERMOT.NS": "Auto",
    "BAJAJ-AUTO.NS": "Auto", "HEROMOTOCO.NS": "Auto",
    "LT.NS": "Industrials", "ADANIPORTS.NS": "Industrials",
    "ADANIENT.NS": "Industrials", "BEL.NS": "Industrials",
    "JSWSTEEL.NS": "Materials", "TATASTEEL.NS": "Materials",
    "HINDALCO.NS": "Materials", "ULTRACEMCO.NS": "Materials",
    "GRASIM.NS": "Materials",
    "SUNPHARMA.NS": "Healthcare", "DRREDDY.NS": "Healthcare",
    "CIPLA.NS": "Healthcare", "DIVISLAB.NS": "Healthcare",
    "APOLLOHOSP.NS": "Healthcare",
    "ASIANPAINT.NS": "ConsDisc", "TITAN.NS": "ConsDisc", "TRENT.NS": "ConsDisc",
    "BHARTIARTL.NS": "Telecom",
}

SECTOR_PEERS = {
    s: [t for t, sec in SECTOR_MAP.items() if sec == s]
    for s in set(SECTOR_MAP.values())
}


# ── Strategy class ────────────────────────────────────────────────────────────
class SingleStockStrategy(BaseStrategy):
    NAME = "Single Stock Analysis"
    DESCRIPTION = (
        "Deep investor analysis of any Nifty 50 stock — "
        "returns vs Nifty, risk metrics, year-by-year performance, "
        "drawdown, holding period analysis, and fundamentals."
    )

    def render_sidebar(self):
        selected_name = st.sidebar.selectbox(
            "Select Stock", list(NIFTY50_STOCKS.keys())
        )
        self.stock       = NIFTY50_STOCKS[selected_name]
        self.stock_label = selected_name
        period_map       = {"1 Year": "1y", "3 Years": "3y", "5 Years": "5y"}
        period_label     = st.sidebar.selectbox("Time Period", list(period_map.keys()))
        self.period      = period_map[period_label]

    # ── Data ─────────────────────────────────────────────────────────────────
    @st.cache_data
    def _get_data(_self, stock, period):
        df = yf.download(stock, period=period, auto_adjust=True, progress=False)
        df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)
        return df

    @st.cache_data
    def _get_nifty(_self, period):
        df = yf.download("^NSEI", period=period, auto_adjust=True, progress=False)
        df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)
        return df["Close"]

    # ── Metrics ───────────────────────────────────────────────────────────────
    def _compute(self, df, nifty_close):
        close   = df["Close"]
        returns = close.pct_change().dropna()
        years   = len(df) / 252

        cagr      = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1
        vol       = returns.std() * np.sqrt(252)
        sharpe    = (returns.mean() * 252) / vol if vol != 0 else 0
        peak      = close.cummax()
        drawdown  = (close - peak) / peak
        max_dd    = drawdown.min()
        win_rate  = (returns > 0).mean()

        downside  = returns[returns < 0].std() * np.sqrt(252)
        sortino   = (returns.mean() * 252) / downside if downside != 0 else 0
        calmar    = cagr / abs(max_dd) if max_dd != 0 else 0
        var_95    = np.percentile(returns, 5)

        # Align with Nifty for beta/alpha/capture
        nifty_r   = nifty_close.pct_change().dropna()
        s_r, n_r  = returns.align(nifty_r, join="inner")

        if len(s_r) > 30:
            cov          = np.cov(s_r, n_r)
            beta         = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 1.0
            nifty_cagr   = (nifty_close.iloc[-1] / nifty_close.iloc[0]) ** (1 / years) - 1
            alpha        = cagr - beta * nifty_cagr
            up_mask      = n_r > 0
            dn_mask      = n_r < 0
            up_cap       = (s_r[up_mask].mean() / n_r[up_mask].mean()
                            if n_r[up_mask].mean() != 0 else 1.0)
            dn_cap       = (s_r[dn_mask].mean() / n_r[dn_mask].mean()
                            if n_r[dn_mask].mean() != 0 else 1.0)
        else:
            beta, alpha, nifty_cagr, up_cap, dn_cap = 1.0, 0.0, 0.0, 1.0, 1.0

        # 52-week
        close_1y       = close.iloc[-252:] if len(close) >= 252 else close
        high_52        = float(close_1y.max())
        low_52         = float(close_1y.min())
        cur            = float(close.iloc[-1])
        pct_from_high  = (cur - high_52) / high_52
        pct_from_low   = (cur - low_52)  / low_52
        pos_52         = (cur - low_52) / (high_52 - low_52) * 100 if high_52 > low_52 else 50

        # Equity curves normalised to ₹10L
        eq_stock = (1 + returns).cumprod() * 1_000_000
        eq_nifty = (1 + nifty_r).cumprod().reindex(eq_stock.index).ffill() * 1_000_000

        # Nifty drawdown (aligned)
        nifty_aligned  = nifty_close.reindex(drawdown.index).ffill()
        nifty_peak     = nifty_aligned.cummax()
        nifty_dd       = (nifty_aligned - nifty_peak) / nifty_peak

        return dict(
            close=close, returns=returns, drawdown=drawdown,
            nifty_r=nifty_r, nifty_dd=nifty_dd,
            eq_stock=eq_stock, eq_nifty=eq_nifty,
            cagr=cagr, vol=vol, sharpe=sharpe, max_dd=max_dd,
            win_rate=win_rate, sortino=sortino, calmar=calmar,
            var_95=var_95, beta=beta, alpha=alpha,
            nifty_cagr=nifty_cagr, up_cap=up_cap, dn_cap=dn_cap,
            high_52=high_52, low_52=low_52, cur=cur,
            pct_from_high=pct_from_high, pct_from_low=pct_from_low,
            pos_52=pos_52,
        )

    # ── Run ───────────────────────────────────────────────────────────────────
    def run(self):
        with st.spinner("Fetching data…"):
            df    = self._get_data(self.stock, self.period)
            nifty = self._get_nifty(self.period)

        if df.empty:
            st.error("No data returned. Try a different period.")
            return

        m = self._compute(df, nifty)

        # ────────────────────────────────────────────────────────────────────
        # 1. KPI ROW 1 — Return & risk-adjusted
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📊 Performance Summary")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric(
            "CAGR", f"{m['cagr']*100:.1f}%",
            delta=f"{(m['cagr']-m['nifty_cagr'])*100:+.1f}% vs Nifty",
        )
        c2.metric("Sharpe", f"{m['sharpe']:.2f}",
                  help="Annual return ÷ annual volatility. Target >1.")
        c3.metric("Sortino", f"{m['sortino']:.2f}",
                  help="Like Sharpe but only penalises downside vol. Target >1.")
        c4.metric("Max Drawdown", f"{m['max_dd']*100:.1f}%",
                  delta_color="inverse",
                  help="Worst peak-to-trough fall over the selected period.")
        c5.metric("Beta", f"{m['beta']:.2f}",
                  help="1.0 = moves in line with Nifty. >1 = amplified moves.")
        c6.metric("Alpha vs Nifty", f"{m['alpha']*100:+.1f}%",
                  help="Excess annual return after adjusting for market exposure.")

        # KPI ROW 2 — Risk detail
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Volatility", f"{m['vol']*100:.1f}%",
                  help="Annualised standard deviation of daily returns.")
        c2.metric("Win Rate", f"{m['win_rate']*100:.1f}%",
                  help="% of trading days with a positive return.")
        c3.metric("Calmar Ratio", f"{m['calmar']:.2f}",
                  help="CAGR ÷ |Max Drawdown|. Target >1.")
        c4.metric("VaR (95%)", f"{m['var_95']*100:.2f}%",
                  help="Expected loss on a bad day (worst 5% of days).")
        c5.metric(
            "Up / Down Capture",
            f"{m['up_cap']*100:.0f}% / {m['dn_cap']*100:.0f}%",
            help="How much of Nifty's up-days vs down-days this stock captures.",
        )
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 2. EQUITY CURVE vs NIFTY
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📈 ₹10L Invested — Stock vs Nifty 50")
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=m["eq_stock"].index, y=m["eq_stock"].values,
            name=self.stock_label,
            line=dict(color="#2ecc71", width=2.5),
        ))
        fig_eq.add_trace(go.Scatter(
            x=m["eq_nifty"].index, y=m["eq_nifty"].values,
            name="Nifty 50",
            line=dict(color="#e67e22", width=1.8, dash="dash"),
        ))
        # shade the alpha region
        ey = m["eq_stock"]
        en = m["eq_nifty"].reindex(ey.index).ffill()
        fig_eq.add_trace(go.Scatter(
            x=list(ey.index) + list(ey.index[::-1]),
            y=list(ey.values) + list(en.values[::-1]),
            fill="toself",
            fillcolor="rgba(46,204,113,0.07)",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ))
        fig_eq.update_layout(
            height=340,
            yaxis=dict(tickprefix="₹", tickformat=",.0f"),
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=10, r=10, t=10, b=10),
            hovermode="x unified",
        )
        final_stock = m["eq_stock"].iloc[-1]
        final_nifty = m["eq_nifty"].iloc[-1]
        st.plotly_chart(fig_eq, use_container_width=True)
        st.caption(
            f"₹10L → **₹{final_stock:,.0f}** (stock) vs "
            f"₹{final_nifty:,.0f} (Nifty) over the selected period."
        )
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 3. PRICE CHART with 50DMA + 200DMA
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📉 Price Chart — with Moving Averages")
        close = m["close"]
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(
            x=close.index, y=close.values,
            name="Price", line=dict(color="#90caf9", width=1.6),
        ))
        if len(close) >= 50:
            fig_p.add_trace(go.Scatter(
                x=close.index, y=close.rolling(50).mean().values,
                name="50 DMA", line=dict(color="#f39c12", width=1.4, dash="dot"),
            ))
        if len(close) >= 200:
            fig_p.add_trace(go.Scatter(
                x=close.index, y=close.rolling(200).mean().values,
                name="200 DMA", line=dict(color="#e74c3c", width=1.4, dash="dash"),
            ))
        fig_p.update_layout(
            height=320,
            yaxis=dict(tickprefix="₹"),
            legend=dict(x=0.01, y=0.99),
            margin=dict(l=10, r=10, t=10, b=10),
            hovermode="x unified",
        )
        st.plotly_chart(fig_p, use_container_width=True)

        # 52-week snapshot
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Price",     f"₹{m['cur']:,.1f}")
        c2.metric("52-Week High",      f"₹{m['high_52']:,.1f}",
                  delta=f"{m['pct_from_high']*100:.1f}% from high",
                  delta_color="inverse")
        c3.metric("52-Week Low",       f"₹{m['low_52']:,.1f}",
                  delta=f"{m['pct_from_low']*100:+.1f}% above low")
        c4.metric("Position in 52W Range", f"{m['pos_52']:.0f}%",
                  help="0% = at 52W low  |  100% = at 52W high")
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 4. YEAR-BY-YEAR RETURNS vs NIFTY
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📅 Year-by-Year Returns vs Nifty 50")
        stock_yr = m["returns"].resample("YE").apply(lambda r: (1 + r).prod() - 1)
        nifty_yr = m["nifty_r"].resample("YE").apply(lambda r: (1 + r).prod() - 1)
        idx      = stock_yr.index.intersection(nifty_yr.index)

        if len(idx) >= 1:
            sy  = stock_yr.reindex(idx)
            ny  = nifty_yr.reindex(idx)
            yrs = [str(d.year) for d in idx]
            bar_colors = [
                "#2ecc71" if s > n else "#e74c3c"
                for s, n in zip(sy.values, ny.values)
            ]
            fig_yr = go.Figure()
            fig_yr.add_trace(go.Bar(
                x=yrs, y=(sy.values * 100).tolist(),
                name=self.stock_label, marker_color=bar_colors, opacity=0.9,
            ))
            fig_yr.add_trace(go.Bar(
                x=yrs, y=(ny.values * 100).tolist(),
                name="Nifty 50", marker_color="#e67e22", opacity=0.6,
            ))
            fig_yr.add_hline(y=0, line_color="white", line_width=0.8)
            fig_yr.update_layout(
                barmode="group", height=300,
                yaxis_title="Return %",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig_yr, use_container_width=True)

            yr_df = pd.DataFrame({
                "Year":                yrs,
                f"{self.stock_label} %": [round(v * 100, 1) for v in sy.values],
                "Nifty 50 %":          [round(v * 100, 1) for v in ny.values],
                "Alpha %":             [round((s - n) * 100, 1)
                                        for s, n in zip(sy.values, ny.values)],
                "Beat Nifty":          ["✅" if s > n else "❌"
                                        for s, n in zip(sy.values, ny.values)],
            })
            beat = yr_df["Beat Nifty"].eq("✅").sum()
            st.dataframe(yr_df, use_container_width=True, hide_index=True)
            st.caption(f"Beat Nifty in **{beat}** of {len(yr_df)} calendar years.")
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 5. DRAWDOWN vs NIFTY
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📉 Drawdown vs Nifty 50")
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=m["drawdown"].index, y=(m["drawdown"] * 100).values,
            fill="tozeroy", name=self.stock_label,
            fillcolor="rgba(46,204,113,0.25)",
            line=dict(color="#2ecc71", width=1.5),
        ))
        fig_dd.add_trace(go.Scatter(
            x=m["nifty_dd"].index, y=(m["nifty_dd"] * 100).values,
            fill="tozeroy", name="Nifty 50",
            fillcolor="rgba(230,126,34,0.15)",
            line=dict(color="#e67e22", width=1.2, dash="dash"),
        ))
        fig_dd.update_layout(
            height=260, yaxis_title="Drawdown %",
            margin=dict(l=10, r=10, t=10, b=10),
            hovermode="x unified",
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        nifty_max_dd = m["nifty_dd"].min()
        saved = abs(nifty_max_dd) - abs(m["max_dd"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Stock Max DD",      f"{m['max_dd']*100:.1f}%")
        c2.metric("Nifty Max DD",      f"{nifty_max_dd*100:.1f}%")
        c3.metric("DD Saved vs Nifty", f"{saved*100:+.1f}%",
                  delta_color="normal" if saved >= 0 else "inverse")
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 6. HOLDING PERIOD ANALYSIS
        # ────────────────────────────────────────────────────────────────────
        st.subheader("📊 Holding Period Analysis — Rolling 1-Year Returns")
        roll_1y = (
            m["returns"]
            .rolling(252)
            .apply(lambda r: (1 + r).prod() - 1)
            .dropna()
        )
        if len(roll_1y) > 50:
            pct_pos    = (roll_1y > 0).mean() * 100
            median_ret = roll_1y.median() * 100
            vals       = (roll_1y * 100).values

            fig_hist = go.Figure()
            fig_hist.add_trace(go.Histogram(
                x=vals, nbinsx=40,
                marker_color="#2ecc71", opacity=0.75,
                name="1Y rolling return",
            ))
            fig_hist.add_vline(
                x=0, line_color="white", line_dash="dash", line_width=1.2,
            )
            fig_hist.add_vline(
                x=float(median_ret), line_color="#f39c12",
                line_dash="dot", line_width=1.5,
                annotation_text=f"Median {median_ret:.1f}%",
                annotation_position="top right",
            )
            fig_hist.update_layout(
                height=240,
                xaxis_title="1-Year Return %",
                yaxis_title="Frequency",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig_hist, use_container_width=True)
            st.caption(
                f"Invested for any random 1-year window: profitable "
                f"**{pct_pos:.0f}%** of the time. "
                f"Median 1-year gain: **{median_ret:.1f}%**."
            )
        else:
            st.info("Need at least 2 years of data for holding period analysis.")
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 7. FUNDAMENTALS + SECTOR CONTEXT
        # ────────────────────────────────────────────────────────────────────
        st.subheader("🏭 Fundamentals & Sector Context")
        stock_sector = SECTOR_MAP.get(self.stock, "Other")
        peers        = [t for t in SECTOR_PEERS.get(stock_sector, []) if t != self.stock]

        try:
            info = yf.Ticker(self.stock).info
        except Exception:
            info = {}

        own_pe  = info.get("trailingPE")
        own_roe = info.get("returnOnEquity")
        own_de  = info.get("debtToEquity")
        mkt_cap = info.get("marketCap")
        div_yld = info.get("dividendYield")

        # Peer average PE
        peer_pes = []
        for pt in peers[:8]:
            try:
                pe_v = yf.Ticker(pt).info.get("trailingPE")
                if pe_v and float(pe_v) > 0:
                    peer_pes.append(float(pe_v))
            except Exception:
                continue
        avg_peer_pe = round(sum(peer_pes) / len(peer_pes), 1) if peer_pes else None

        # Overview row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sector", stock_sector)
        if mkt_cap:
            c2.metric(
                "Market Cap",
                f"₹{mkt_cap/1e12:.2f}T" if mkt_cap >= 1e12
                else f"₹{mkt_cap/1e9:.0f}B",
            )
        if div_yld:
            c3.metric("Dividend Yield", f"{div_yld*100:.2f}%",
                      help="Trailing 12-month dividend yield")
        c4.metric("Sector Peers", f"{len(peers)}")

        # Valuation row
        st.markdown("##### Valuation & Quality")
        c1, c2, c3, c4 = st.columns(4)

        if own_pe:
            pe_delta = (
                f"{float(own_pe)-avg_peer_pe:+.1f}× vs sector avg {avg_peer_pe}×"
                if avg_peer_pe else None
            )
            c1.metric("PE Ratio", f"{float(own_pe):.1f}×",
                      delta=pe_delta, delta_color="inverse",
                      help="Lower = cheaper vs earnings. Compare to sector avg.")
        else:
            c1.metric("PE Ratio", "N/A")

        if avg_peer_pe:
            c2.metric("Sector Avg PE", f"{avg_peer_pe}×")

        if own_roe:
            c3.metric("ROE", f"{float(own_roe)*100:.1f}%",
                      help="Return on Equity — how efficiently management uses capital. >15% is healthy.")

        if own_de is not None:
            c4.metric("Debt / Equity", f"{float(own_de):.2f}×",
                      help="Lower = safer balance sheet. <1 is generally comfortable.")
        st.markdown("---")

        # ────────────────────────────────────────────────────────────────────
        # 8. SMART INSIGHTS
        # ────────────────────────────────────────────────────────────────────
        st.subheader("🧠 Smart Insights")

        checks = [
            (
                m["cagr"] > m["nifty_cagr"],
                f"✅ Beats Nifty by **{(m['cagr']-m['nifty_cagr'])*100:.1f}%/year** "
                f"({m['cagr']*100:.1f}% vs {m['nifty_cagr']*100:.1f}%)",
                f"❌ Underperforms Nifty — CAGR {m['cagr']*100:.1f}% vs Nifty {m['nifty_cagr']*100:.1f}%",
                False,
            ),
            (
                m["sharpe"] >= 1.0,
                f"✅ Strong risk-adjusted return — Sharpe **{m['sharpe']:.2f}** (≥1.0)",
                f"⚠️ Sharpe **{m['sharpe']:.2f}** — returns don't fully compensate the risk taken",
                True,
            ),
            (
                m["sortino"] >= 1.0,
                f"✅ Downside risk well-managed — Sortino **{m['sortino']:.2f}**",
                f"⚠️ Sortino **{m['sortino']:.2f}** — higher downside volatility relative to returns",
                True,
            ),
            (
                abs(m["max_dd"]) < 0.30,
                f"✅ Max drawdown **{m['max_dd']*100:.1f}%** is within acceptable range (<30%)",
                f"❌ Max drawdown **{m['max_dd']*100:.1f}%** — significant capital erosion in this period",
                False,
            ),
            (
                0.5 <= m["beta"] <= 1.2,
                f"✅ Beta **{m['beta']:.2f}** — stable market correlation",
                f"⚠️ Beta **{m['beta']:.2f}** — {'very low market sensitivity' if m['beta'] < 0.5 else 'amplifies market moves significantly'}",
                True,
            ),
            (
                m["dn_cap"] < 1.0,
                f"✅ Down-capture **{m['dn_cap']*100:.0f}%** — protects better than Nifty on bad days",
                f"⚠️ Down-capture **{m['dn_cap']*100:.0f}%** — falls more than Nifty during market sell-offs",
                True,
            ),
        ]

        passed = sum(1 for ok, _, _, _ in checks if ok)
        score_color = (
            "#2ecc71" if passed >= 5
            else "#f39c12" if passed >= 3
            else "#e74c3c"
        )
        st.markdown(
            f"<div style='font-size:15px; color:{score_color}; font-weight:700; "
            f"margin-bottom:12px;'>{passed} / 6 investor checks passed</div>",
            unsafe_allow_html=True,
        )
        for ok, good, bad, is_warn in checks:
            if ok:
                st.success(good)
            elif is_warn:
                st.warning(bad)
            else:
                st.error(bad)
