"""회사 이름으로 최근 3년 주가 흐름과 매출·이익·현금흐름을 보여주는 Streamlit 앱.

실행:  streamlit run app.py
데이터: Yahoo Finance (yfinance), 국내 상장사 목록은 kr_listings.py
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

import kr_listings

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


class DataUnavailable(Exception):
    """일시적 실패. 캐시에 남기지 않도록 예외로 올립니다 (st.cache_data는 예외를 캐시하지 않음)."""


# ---------------------------------------------------------------- data layer
@st.cache_data(ttl=86400, show_spinner=False)
def get_listings() -> tuple[pd.DataFrame, str]:
    return kr_listings.load_listings()


@st.cache_data(ttl=3600, show_spinner=False)
def yahoo_search(query: str) -> list[dict]:
    try:
        quotes = yf.Search(query, max_results=10).quotes
    except Exception as e:  # 네트워크 오류는 캐시하지 않음
        raise DataUnavailable(str(e)) from e
    out = []
    for item in quotes:
        if item.get("quoteType") not in ("EQUITY", "ETF"):
            continue
        out.append({
            "symbol": item["symbol"],
            "label": f"{item.get('longname') or item.get('shortname') or item['symbol']} "
                     f"({item['symbol']} · {item.get('exchDisp') or item.get('exchange', '')})",
        })
    return out


def resolve(query: str, listings: pd.DataFrame) -> list[dict]:
    """입력값 → 후보 종목 목록. 국내 상장사 부분 일치를 해외 검색 결과보다 먼저 보여줍니다."""
    q = query.strip()
    cands = [{"symbol": r.symbol, "label": r.label}
             for r in kr_listings.match(listings, q).itertuples()]
    alias = kr_listings.FOREIGN_ALIASES.get(q.upper()) or kr_listings.FOREIGN_ALIASES.get(q)
    if alias:
        cands.insert(0, {"symbol": alias, "label": f"{q} ({alias})"})
    if q.isascii():  # Yahoo 검색은 한글을 찾지 못하므로 영문/티커일 때만
        try:
            cands += yahoo_search(q)
        except DataUnavailable:
            pass
        if not cands:  # 검색 결과가 없으면 입력값을 티커로 간주
            cands.append({"symbol": q.upper(), "label": q.upper()})
    seen, uniq = set(), []
    for c in cands:
        if c["symbol"] not in seen:
            seen.add(c["symbol"])
            uniq.append(c)
    return uniq


@st.cache_data(ttl=3600, show_spinner=False)
def load_price(symbol: str) -> tuple[pd.DataFrame, dict]:
    t = yf.Ticker(symbol)
    try:
        hist = t.history(period="3y", auto_adjust=False)
        meta = t.history_metadata or {}
    except Exception as e:
        raise DataUnavailable(str(e)) from e
    if hist is None or hist.empty:
        raise DataUnavailable("empty history")
    return hist, {k: meta.get(k) for k in ("currency", "longName", "shortName", "instrumentType")}


@st.cache_data(ttl=3600, show_spinner=False)
def load_financials(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}  # 회사 정보는 부가 정보라 실패해도 계속
    try:
        return {
            "info": {k: info.get(k) for k in ("sector", "industry", "country", "financialCurrency")},
            "income": t.income_stmt, "cashflow": t.cashflow,
            "q_income": t.quarterly_income_stmt, "q_cashflow": t.quarterly_cashflow,
        }
    except Exception as e:
        raise DataUnavailable(str(e)) from e


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
    # 분기는 회사마다 회계연도가 달라 'Q2' 대신 분기 말 날짜로 표기
    return f"{ts:%Y.%m}" if quarterly else f"FY{ts.year}"


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
        height=420, hovermode="x unified", margin=dict(t=30, b=10, l=10, r=10),
        yaxis=dict(title=f"주가 ({currency})"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, showticklabels=False,
                    range=[0, hist["Volume"].max() * 4 if len(hist) else 1]),
        legend=dict(orientation="h", y=1.12),
    )
    return fig


def bar_chart(df: pd.DataFrame, quarterly: bool, div: float, unit: str) -> go.Figure:
    fig = go.Figure()
    x = [period_label(i, quarterly) for i in df.index]
    for col in df.columns:
        fig.add_trace(go.Bar(x=x, y=df[col] / div, name=col,
                             text=[f"{v:,.1f}" if pd.notna(v) else "" for v in df[col] / div],
                             textposition="outside"))
    fig.update_layout(barmode="group", height=400, yaxis_title=unit,
                      margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", y=1.12))
    return fig


def line_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col in df.columns:
        fig.add_trace(go.Scatter(x=list(df.index), y=df[col], name=col, mode="lines+markers"))
    fig.update_layout(height=280, yaxis_title="%", hovermode="x unified",
                      margin=dict(t=30, b=10, l=10, r=10), legend=dict(orientation="h", y=1.15))
    return fig


# 확대/이동/드래그를 막아 터치 실수로 그래프가 변하지 않게 고정 (값 툴팁은 유지)
LOCKED = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False,
          "showAxisDragHandles": False}


def show(fig: go.Figure) -> None:
    fig.update_layout(dragmode=False)
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, width="stretch", config=LOCKED)


def fmt_table(df: pd.DataFrame, quarterly: bool, div: float) -> pd.DataFrame:
    t = (df / div).T
    t.columns = [period_label(c, quarterly) for c in t.columns]
    return t.map(lambda v: f"{v:,.1f}" if pd.notna(v) else "-")


def stat_grid(items: list[tuple[str, str, str]]) -> None:
    """휴대폰에서도 2열 이상으로 보이는 요약 지표 (st.metric은 모바일에서 한 줄씩 쌓임)."""
    cells = "".join(
        f'<div class="kpi"><div class="kpi-l">{html.escape(label)}</div>'
        f'<div class="kpi-v {tone}">{html.escape(value)}</div></div>'
        for label, value, tone in items
    )
    st.markdown(f'<div class="kpis">{cells}</div>', unsafe_allow_html=True)


def tone(v: float) -> str:
    return "up" if v > 0 else "down" if v < 0 else ""


# ---------------------------------------------------------------- UI
st.set_page_config(page_title="기업 3년 분석", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 3.2rem;}
.app-title {font-size: 1.15rem; font-weight: 700; margin-bottom: .4rem;}
.kpis {display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
       gap: .5rem; margin: .25rem 0 .75rem;}
.kpi {border: 1px solid rgba(128,128,128,.25); border-radius: .6rem; padding: .55rem .75rem;}
.kpi-l {font-size: .8rem; opacity: .7;}
.kpi-v {font-size: 1.25rem; font-weight: 600; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis;}
.kpi-v.up {color: #d92d20;} .kpi-v.down {color: #1d4ed8;}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="app-title">📈 기업 3년 주가 · 실적 · 현금흐름</div>', unsafe_allow_html=True)

listings, listing_source = get_listings()
options = listings["label"].tolist()

# ?q=회사명 으로 바로 열기 지원
if "query" not in st.session_state:
    st.session_state.query = st.query_params.get("q", "삼성전자")

def on_pick() -> None:
    # 고른 값을 저장하고 입력창은 비웁니다. 직접 입력한 값이 남아 있으면
    # 다음 입력의 Enter가 반영되지 않는 selectbox 동작이 있어서입니다.
    picked = st.session_state.search_box
    if picked:
        st.session_state.query = picked
        st.query_params["q"] = picked
    st.session_state.search_box = None


st.selectbox(
    "회사 이름 또는 티커",
    options,
    index=None,
    key="search_box",
    on_change=on_pick,
    placeholder=f"🔍 {st.session_state.query} · 회사명 입력",
    accept_new_options=True,
    help="국내 상장사는 이름 일부만 입력해도 목록에 나타납니다. "
         "해외 종목은 영문명이나 티커(예: Apple, TSLA, 7203.T)를 입력 후 Enter.",
)

query = st.session_state.query
if query in options:  # 국내 상장사 목록에서 직접 고른 경우: 바로 확정
    row = listings[listings["label"] == query].iloc[0]
    candidates = [{"symbol": row.symbol, "label": row.label}]
else:
    candidates = resolve(query, listings)

if not candidates:
    st.warning(f"'{query}'에 해당하는 종목을 찾지 못했습니다. "
               "국내 종목은 회사명 일부나 종목코드(예: 005930), "
               "해외 종목은 영문명이나 티커(예: Apple, TSLA)로 입력해 보세요.")
    st.stop()

if len(candidates) > 1:
    choice = st.selectbox("검색 결과", range(len(candidates)),
                          format_func=lambda i: candidates[i]["label"], key=f"pick_{query}")
else:
    choice = 0
symbol = candidates[choice]["symbol"]

# --- 1단계: 주가 (먼저 그려서 첫 화면을 빨리 보여줌)
try:
    with st.spinner(f"{symbol} 주가를 불러오는 중..."):
        hist, meta = load_price(symbol)
except DataUnavailable:
    st.error(f"'{symbol}'의 주가 데이터를 가져오지 못했습니다. "
             "종목이 없거나 데이터 제공처가 일시적으로 응답하지 않는 상태일 수 있습니다.")
    if st.button("🔄 다시 시도"):
        st.rerun()
    st.stop()

currency = meta.get("currency") or ""
name = meta.get("longName") or meta.get("shortName") or candidates[choice]["label"]
quarterly = st.toggle("분기 실적 보기", value=False,
                      help="Yahoo는 분기 데이터를 최근 4~5개 분기만 제공합니다.")

st.markdown(f"##### {name}")
close = hist["Close"]                      # 화면 표시: 실제 종가
adj = hist.get("Adj Close", close)         # 수익률: 배당 재투자 반영 가격
first, last_day = hist.index[0], hist.index[-1]
span_years = (last_day - first).days / 365.25
pfmt = "{:,.0f}" if currency in ("KRW", "JPY") else "{:,.2f}"
ret_total = (adj.iloc[-1] / adj.iloc[0] - 1) * 100
# 데이터가 3년이 안 되면(최근 상장 등) 실제 시작 시점을 표시
total_label = "3년 수익률" if span_years >= 2.9 else f"{first:%Y.%m} 이후 수익률"
one_year = adj[adj.index >= last_day - pd.DateOffset(years=1)]
items = [
    (f"현재가 ({currency})" if currency else "현재가", pfmt.format(close.iloc[-1]), ""),
    (total_label, f"{ret_total:+.1f}%", tone(ret_total)),
]
if span_years >= 1:
    ret_1y = (one_year.iloc[-1] / one_year.iloc[0] - 1) * 100
    items.append(("1년 수익률", f"{ret_1y:+.1f}%", tone(ret_1y)))
items.append(("기간 최저 ~ 최고", f"{pfmt.format(close.min())} ~ {pfmt.format(close.max())}", ""))
stat_grid(items)

is_fund = meta.get("instrumentType") in ("ETF", "MUTUALFUND", "INDEX")
if is_fund:
    show(price_chart(hist, currency))
    st.info("ETF·펀드·지수는 재무제표(매출·이익·현금흐름)가 없어 주가 흐름만 표시합니다.")
    st.stop()

tab_price, tab_income, tab_cash = st.tabs(["주가 흐름", "매출 · 이익", "현금흐름"])
with tab_price:
    show(price_chart(hist, currency))

# --- 2단계: 재무제표 (주가 화면이 뜬 뒤에 불러옴)
try:
    with st.spinner("재무제표를 불러오는 중..."):
        fin = load_financials(symbol)
except DataUnavailable:
    with tab_income:
        st.error("재무제표를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        if st.button("🔄 다시 시도", key="retry_fin"):
            st.rerun()
    st.stop()

info = fin["info"]
fin_currency = info.get("financialCurrency") or currency
inc = pick_rows(fin["q_income"] if quarterly else fin["income"], INCOME_ROWS)
cf = pick_rows(fin["q_cashflow"] if quarterly else fin["cashflow"], CASHFLOW_ROWS)
if info.get("sector"):
    with tab_price:
        st.caption(" · ".join(filter(None, (info.get("sector"), info.get("industry"),
                                            info.get("country")))))

with tab_income:
    if inc.empty:
        st.info("이 종목은 손익계산서 데이터가 제공되지 않습니다.")
    else:
        div, unit = scale_for(inc, fin_currency)
        show(bar_chart(inc, quarterly, div, unit))
        if "매출" in inc and inc["매출"].notna().any():
            margins = pd.DataFrame({
                k: inc[k] / inc["매출"] * 100 for k in ("영업이익", "순이익") if k in inc
            })
            margins.index = [period_label(i, quarterly) for i in margins.index]
            st.markdown("**이익률 (%)**")
            show(line_chart(margins.rename(columns=lambda c: f"{c}률")))
        st.markdown(f"**상세 ({unit})**")
        st.dataframe(fmt_table(inc, quarterly, div), width="stretch")

with tab_cash:
    if cf.empty:
        st.info("이 종목은 현금흐름표 데이터가 제공되지 않습니다.")
    else:
        div, unit = scale_for(cf, fin_currency)
        show(bar_chart(cf, quarterly, div, unit))
        st.markdown(f"**상세 ({unit})**")
        st.dataframe(fmt_table(cf, quarterly, div), width="stretch")

st.caption(f"데이터: Yahoo Finance · 국내 종목 목록: {listing_source} · "
           "연간 재무는 최근 4개 회계연도, 분기는 최근 4~5개 분기까지 제공됩니다.")
