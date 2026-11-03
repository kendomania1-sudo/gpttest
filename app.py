"""회사 이름으로 최근 3년 주가 흐름과 매출·이익·현금흐름을 보여주는 Streamlit 앱.

실행:  streamlit run app.py
데이터: Yahoo Finance (yfinance)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# Yahoo 검색은 한글 회사명을 잘 찾지 못하므로 자주 찾는 국내 기업은 직접 매핑합니다.
KOREAN_TICKERS = {
    "삼성전자": "005930.KS",
    "sk하이닉스": "000660.KS",
    "하이닉스": "000660.KS",
    "lg에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS",
    "현대차": "005380.KS",
    "현대자동차": "005380.KS",
    "기아": "000270.KS",
    "셀트리온": "068270.KS",
    "naver": "035420.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "posco홀딩스": "005490.KS",
    "포스코홀딩스": "005490.KS",
    "lg화학": "051910.KS",
    "삼성sdi": "006400.KS",
    "kb금융": "105560.KS",
    "신한지주": "055550.KS",
    "현대모비스": "012330.KS",
    "lg전자": "066570.KS",
    "삼성물산": "028260.KS",
    "sk이노베이션": "096770.KS",
    "한국전력": "015760.KS",
    "한화에어로스페이스": "012450.KS",
    "에코프로비엠": "247540.KQ",
    "에코프로": "086520.KQ",
    "알테오젠": "196170.KQ",
    "크래프톤": "259960.KS",
    "엔씨소프트": "036570.KS",
    "하이브": "352820.KS",
    "쿠팡": "CPNG",
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "엔비디아": "NVDA",
    "테슬라": "TSLA",
    "아마존": "AMZN",
    "구글": "GOOGL",
    "알파벳": "GOOGL",
    "메타": "META",
    "넷플릭스": "NFLX",
    "tsmc": "TSM",
}

# yfinance 재무제표 행 이름 후보 (회사/버전에 따라 이름이 조금씩 다름)
INCOME_ROWS = {
    "매출": ["Total Revenue", "Operating Revenue"],
    "영업이익": ["Operating Income", "EBIT"],
    "순이익": ["Net Income", "Net Income Common Stockholders"],
}
CASHFLOW_ROWS = {
    "영업활동 현금흐름": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "투자활동 현금흐름": ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"],
    "재무활동 현금흐름": ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"],
    "잉여현금흐름(FCF)": ["Free Cash Flow"],
}


# ---------------------------------------------------------------- data layer
def resolve_ticker(query: str) -> list[dict]:
    """회사 이름(또는 티커)을 후보 티커 목록으로 변환."""
    q = query.strip()
    key = q.lower().replace(" ", "")
    candidates: list[dict] = []
    if key in KOREAN_TICKERS:
        candidates.append({"symbol": KOREAN_TICKERS[key], "name": q, "exchange": ""})
    try:
        for item in yf.Search(q, max_results=8).quotes:
            if item.get("quoteType") not in ("EQUITY", "ETF"):
                continue
            sym = item.get("symbol")
            if any(c["symbol"] == sym for c in candidates):
                continue
            candidates.append({
                "symbol": sym,
                "name": item.get("longname") or item.get("shortname") or sym,
                "exchange": item.get("exchDisp") or item.get("exchange", ""),
            })
    except Exception:
        pass
    if not candidates:  # 검색 실패 시 입력값을 티커로 간주
        candidates.append({"symbol": q.upper(), "name": q, "exchange": ""})
    return candidates


@st.cache_data(ttl=3600, show_spinner=False)
def load_data(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    return {
        "info": info,
        "history": t.history(period="3y", auto_adjust=True),
        "income": t.income_stmt,
        "cashflow": t.cashflow,
        "q_income": t.quarterly_income_stmt,
        "q_cashflow": t.quarterly_cashflow,
    }


def pick_rows(stmt: pd.DataFrame, mapping: dict[str, list[str]], years: int = 3) -> pd.DataFrame:
    """재무제표에서 필요한 항목만 골라 기간(행) × 항목(열) 표로 반환."""
    if stmt is None or stmt.empty:
        return pd.DataFrame()
    out = {}
    for label, names in mapping.items():
        for n in names:
            if n in stmt.index:
                out[label] = stmt.loc[n]
                break
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().dropna(how="all")
    cutoff = pd.Timestamp.today() - pd.DateOffset(years=years, months=6)
    return df[df.index >= cutoff]


def scale_for(values: pd.DataFrame, currency: str) -> tuple[float, str]:
    m = values.abs().max().max() if not values.empty else 0
    if currency == "KRW":
        return (1e12, "조원") if m >= 1e12 else (1e8, "억원")
    return (1e9, f"십억 {currency}") if m >= 1e9 else (1e6, f"백만 {currency}")


def period_label(ts: pd.Timestamp, quarterly: bool) -> str:
    return f"{ts.year} Q{(ts.month - 1) // 3 + 1}" if quarterly else f"FY{ts.year}"


# ---------------------------------------------------------------- charts
def price_chart(hist: pd.DataFrame, currency: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="종가", line=dict(width=2)))
    for w, color in ((20, "#f59e0b"), (120, "#10b981")):
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"].rolling(w).mean(),
                                 name=f"{w}일 이동평균", line=dict(width=1, color=color)))
    fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"], name="거래량", yaxis="y2",
                         marker_color="rgba(128,128,128,0.3)"))
    fig.update_layout(
        height=480, hovermode="x unified", margin=dict(t=30, b=10),
        yaxis=dict(title=f"주가 ({currency})"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, title="거래량",
                    range=[0, hist["Volume"].max() * 4 if len(hist) else 1]),
        legend=dict(orientation="h", y=1.08),
    )
    return fig


def bar_chart(df: pd.DataFrame, quarterly: bool, div: float, unit: str) -> go.Figure:
    fig = go.Figure()
    x = [period_label(i, quarterly) for i in df.index]
    for col in df.columns:
        fig.add_trace(go.Bar(x=x, y=df[col] / div, name=col,
                             text=[f"{v:,.1f}" if pd.notna(v) else "" for v in df[col] / div],
                             textposition="outside"))
    fig.update_layout(barmode="group", height=420, yaxis_title=unit,
                      margin=dict(t=30, b=10), legend=dict(orientation="h", y=1.1))
    return fig


def fmt_table(df: pd.DataFrame, quarterly: bool, div: float) -> pd.DataFrame:
    t = (df / div).T
    t.columns = [period_label(c, quarterly) for c in t.columns]
    return t.map(lambda v: f"{v:,.1f}" if pd.notna(v) else "-")


# ---------------------------------------------------------------- UI
st.set_page_config(page_title="기업 3년 분석", page_icon="📈", layout="wide")
st.title("📈 기업 3년 주가 · 실적 · 현금흐름")

with st.sidebar:
    query = st.text_input("회사 이름 또는 티커", "삼성전자",
                          help="예: 삼성전자, 네이버, Apple, Tesla, 005930.KS, MSFT")
    quarterly = st.toggle("분기 실적 보기", value=False,
                          help="Yahoo는 분기 데이터를 최근 4~5개 분기만 제공합니다.")
    st.caption("데이터 출처: Yahoo Finance · 연간 재무제표는 보통 최근 4개 회계연도까지 제공됩니다.")

if not query.strip():
    st.stop()

candidates = resolve_ticker(query)
labels = [f"{c['name']} ({c['symbol']}{' · ' + c['exchange'] if c['exchange'] else ''})"
          for c in candidates]
choice = st.selectbox("검색 결과", range(len(candidates)), format_func=lambda i: labels[i])
symbol = candidates[choice]["symbol"]

with st.spinner(f"{symbol} 데이터를 불러오는 중..."):
    try:
        data = load_data(symbol)
    except Exception as e:
        st.error(f"데이터를 불러오지 못했습니다: {e}")
        st.stop()

info, hist = data["info"], data["history"]
if hist is None or hist.empty:
    st.error(f"'{symbol}'의 주가 데이터를 찾을 수 없습니다. 다른 이름이나 티커로 시도해 보세요.")
    st.stop()

currency = info.get("currency", "")
fin_currency = info.get("financialCurrency") or currency

# --- 요약 지표
st.subheader(info.get("longName") or info.get("shortName") or symbol)
start, last = hist["Close"].iloc[0], hist["Close"].iloc[-1]
one_year = hist[hist.index >= hist.index[-1] - pd.DateOffset(years=1)]["Close"]
pfmt = "{:,.0f}" if currency in ("KRW", "JPY") else "{:,.2f}"
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(f"현재가 ({currency})", pfmt.format(last))
c2.metric("3년 수익률", f"{(last / start - 1) * 100:+.1f}%")
c3.metric("1년 수익률", f"{(last / one_year.iloc[0] - 1) * 100:+.1f}%")
c4.metric("3년 최고가", pfmt.format(hist["Close"].max()))
c5.metric("3년 최저가", pfmt.format(hist["Close"].min()))
if info.get("sector"):
    st.caption(f"{info.get('sector')} · {info.get('industry', '')} · {info.get('country', '')}")

tab_price, tab_income, tab_cash = st.tabs(["주가 흐름", "매출 · 이익", "현금흐름"])

with tab_price:
    st.plotly_chart(price_chart(hist, currency), width="stretch")

income_src = data["q_income"] if quarterly else data["income"]
cash_src = data["q_cashflow"] if quarterly else data["cashflow"]

with tab_income:
    inc = pick_rows(income_src, INCOME_ROWS)
    if inc.empty:
        st.info("손익계산서 데이터가 없습니다.")
    else:
        div, unit = scale_for(inc, fin_currency)
        st.plotly_chart(bar_chart(inc, quarterly, div, unit), width="stretch")
        if "매출" in inc and inc["매출"].notna().any():
            margins = pd.DataFrame({
                k: inc[k] / inc["매출"] * 100 for k in ("영업이익", "순이익") if k in inc
            })
            margins.index = [period_label(i, quarterly) for i in margins.index]
            st.markdown("**이익률 (%)**")
            st.line_chart(margins.rename(columns=lambda c: f"{c}률"))
        st.markdown(f"**상세 ({unit})**")
        st.dataframe(fmt_table(inc, quarterly, div), width="stretch")

with tab_cash:
    cf = pick_rows(cash_src, CASHFLOW_ROWS)
    if cf.empty:
        st.info("현금흐름표 데이터가 없습니다.")
    else:
        div, unit = scale_for(cf, fin_currency)
        st.plotly_chart(bar_chart(cf, quarterly, div, unit), width="stretch")
        st.markdown(f"**상세 ({unit})**")
        st.dataframe(fmt_table(cf, quarterly, div), width="stretch")
