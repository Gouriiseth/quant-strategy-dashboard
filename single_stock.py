import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
from strategies.base import BaseStrategy


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
    "BEL": "BEL.NS", "Shriram Finance": "SHRIRAMFIN.NS", "Trent": "TRENT.NS"
}


class SingleStockStrategy(BaseStrategy):
    NAME = "Single Stock Analysis"
    DESCRIPTION = "Analyze any Nifty 50 stock — CAGR, Sharpe, Drawdown and more."

    def render_sidebar(self):
        selected_name = st.sidebar.selectbox("Select Stock", list(NIFTY50_STOCKS.keys()))
        self.stock = NIFTY50_STOCKS[selected_name]
        period_map = {"1 Year": "1y", "3 Years": "3y", "5 Years": "5y"}
        period_label = st.sidebar.selectbox("Time Period", list(period_map.keys()))
        self.period = period_map[period_label]

    @st.cache_data
    def _get_data(_self, stock, period):
        df = yf.download(stock, period=period, auto_adjust=True, progress=False)
        df.columns = df.columns.get_level_values(0)
        df.dropna(inplace=True)
        return df

    def _metrics(self, df):
        returns = df['Close'].pct_change().dropna()
        years = len(df) / 252
        cagr = (df['Close'].iloc[-1] / df['Close'].iloc[0]) ** (1 / years) - 1
        vol = returns.std() * np.sqrt(252)
        sharpe = (returns.mean() * 252) / vol if vol != 0 else 0
        peak = df['Close'].cummax()
        drawdown = (df['Close'] - peak) / peak
        max_dd = drawdown.min()
        win_rate = (returns > 0).mean()
        return cagr, vol, sharpe, max_dd, win_rate, returns, drawdown

    def run(self):
        with st.spinner("Fetching data..."):
            df = self._get_data(self.stock, self.period)

        if df.empty:
            st.error("Invalid stock or no data available")
            return

        cagr, vol, sharpe, max_dd, win_rate, returns, drawdown = self._metrics(df)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("CAGR", f"{cagr*100:.2f}%")
        col2.metric("Sharpe", f"{sharpe:.2f}")
        col3.metric("Max Drawdown", f"{max_dd*100:.2f}%")
        col4.metric("Volatility", f"{vol*100:.2f}%")
        col5.metric("Win Rate", f"{win_rate*100:.2f}%")

        st.markdown("---")
        st.subheader("📈 Price Chart")
        fig = px.line(df, x=df.index, y="Close", title=f"{self.stock} Price")
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Rolling Returns")
            st.line_chart(returns.rolling(20).mean())
        with col2:
            st.markdown("#### Drawdown")
            st.line_chart(drawdown)

        st.markdown("---")
        st.subheader("⚠️ Risk Analysis")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Volatility", f"{vol*100:.2f}%")
            st.metric("VaR (95%)", f"{np.percentile(returns, 5)*100:.2f}%")
        with col2:
            downside = returns[returns < 0].std() * np.sqrt(252)
            st.metric("Downside Dev", f"{downside*100:.2f}%")

        st.markdown("---")
        st.subheader("📉 Fundamentals")
        info = yf.Ticker(self.stock).info
        st.dataframe(pd.DataFrame({
            "Metric": ["PE", "ROE", "Debt/Equity"],
            "Value": [info.get("trailingPE"), info.get("returnOnEquity"), info.get("debtToEquity")]
        }))

        st.markdown("---")
        st.subheader("🧠 Smart Insights")
        st.success("Good risk-adjusted returns") if sharpe > 1 else st.warning("Low Sharpe Ratio")
        st.error("High drawdown risk") if max_dd < -0.3 else st.info("Drawdown within acceptable range")

        with st.expander("📊 Advanced Metrics"):
            downside = returns[returns < 0].std() * np.sqrt(252)
            sortino = (returns.mean() * 252) / downside if downside != 0 else 0
            st.write(f"Sortino Ratio: {sortino:.2f}")