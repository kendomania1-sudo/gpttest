"""국내 상장사 목록 (자동완성용).

우선순위
1. data/kr_listings.csv  — 공식 기관 목록에서 받아 둔 전체 상장사 파일
   (열: name, code, market   예: 삼성전자,005930,KOSPI)
2. 아래 FALLBACK         — 파일이 없을 때 쓰는 주요 종목 일부

공식 목록을 자동으로 받아오는 소스는 이 모듈의 load_listings()에 연결합니다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).parent / "data" / "kr_listings.csv"
YAHOO_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ", "KONEX": ".KN"}
MARKET_KO = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스"}

FALLBACK = [
    ("삼성전자", "005930", "KOSPI"), ("삼성전자우", "005935", "KOSPI"),
    ("SK하이닉스", "000660", "KOSPI"), ("LG에너지솔루션", "373220", "KOSPI"),
    ("삼성바이오로직스", "207940", "KOSPI"), ("현대차", "005380", "KOSPI"),
    ("기아", "000270", "KOSPI"), ("셀트리온", "068270", "KOSPI"),
    ("NAVER", "035420", "KOSPI"), ("카카오", "035720", "KOSPI"),
    ("카카오뱅크", "323410", "KOSPI"), ("카카오페이", "377300", "KOSPI"),
    ("POSCO홀딩스", "005490", "KOSPI"), ("LG화학", "051910", "KOSPI"),
    ("LG전자", "066570", "KOSPI"), ("LG", "003550", "KOSPI"),
    ("LG디스플레이", "034220", "KOSPI"), ("LG생활건강", "051900", "KOSPI"),
    ("LG유플러스", "032640", "KOSPI"), ("삼성SDI", "006400", "KOSPI"),
    ("삼성물산", "028260", "KOSPI"), ("삼성생명", "032830", "KOSPI"),
    ("삼성전기", "009150", "KOSPI"), ("삼성화재", "000810", "KOSPI"),
    ("KB금융", "105560", "KOSPI"), ("신한지주", "055550", "KOSPI"),
    ("하나금융지주", "086790", "KOSPI"), ("우리금융지주", "316140", "KOSPI"),
    ("현대모비스", "012330", "KOSPI"), ("현대건설", "000720", "KOSPI"),
    ("현대글로비스", "086280", "KOSPI"), ("HD현대중공업", "329180", "KOSPI"),
    ("HD한국조선해양", "009540", "KOSPI"), ("현대제철", "004020", "KOSPI"),
    ("SK이노베이션", "096770", "KOSPI"), ("SK텔레콤", "017670", "KOSPI"),
    ("SK", "034730", "KOSPI"), ("KT", "030200", "KOSPI"),
    ("한국전력", "015760", "KOSPI"), ("한화에어로스페이스", "012450", "KOSPI"),
    ("한화오션", "042660", "KOSPI"), ("두산에너빌리티", "034020", "KOSPI"),
    ("크래프톤", "259960", "KOSPI"), ("엔씨소프트", "036570", "KOSPI"),
    ("넷마블", "251270", "KOSPI"), ("하이브", "352820", "KOSPI"),
    ("아모레퍼시픽", "090430", "KOSPI"), ("CJ제일제당", "097950", "KOSPI"),
    ("대한항공", "003490", "KOSPI"), ("고려아연", "010130", "KOSPI"),
    ("에코프로비엠", "247540", "KOSDAQ"), ("에코프로", "086520", "KOSDAQ"),
    ("알테오젠", "196170", "KOSDAQ"), ("HLB", "028300", "KOSDAQ"),
    ("리가켐바이오", "141080", "KOSDAQ"), ("레인보우로보틱스", "277810", "KOSDAQ"),
    ("펄어비스", "263750", "KOSDAQ"), ("JYP Ent.", "035900", "KOSDAQ"),
    ("에스엠", "041510", "KOSDAQ"), ("셀트리온제약", "068760", "KOSDAQ"),
]

# 해외 기업의 한글 이름 → Yahoo 티커 (Yahoo 검색은 한글을 못 찾음)
FOREIGN_ALIASES = {
    "애플": "AAPL", "마이크로소프트": "MSFT", "엔비디아": "NVDA", "테슬라": "TSLA",
    "아마존": "AMZN", "구글": "GOOGL", "알파벳": "GOOGL", "메타": "META",
    "넷플릭스": "NFLX", "쿠팡": "CPNG", "TSMC": "TSM", "브로드컴": "AVGO",
    "도요타": "7203.T", "소니": "6758.T",
}


def load_listings() -> tuple[pd.DataFrame, str]:
    """(목록, 출처 설명)을 반환. 열: name, code, market, symbol, label."""
    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH, dtype=str)
        source = "data/kr_listings.csv"
    else:
        df = pd.DataFrame(FALLBACK, columns=["name", "code", "market"])
        source = "기본 목록(주요 종목)"
    df = df.dropna(subset=["name", "code", "market"]).copy()
    df["code"] = df["code"].str.strip().str.lstrip("A").str.zfill(6)
    df["market"] = df["market"].str.upper().str.strip()
    df = df[df["market"].isin(YAHOO_SUFFIX)]
    df["symbol"] = df["code"] + df["market"].map(YAHOO_SUFFIX)
    df["label"] = (df["name"] + " (" + df["code"] + " · "
                   + df["market"].map(MARKET_KO) + ")")
    return df.drop_duplicates("symbol").sort_values("name").reset_index(drop=True), source


def match(df: pd.DataFrame, query: str, limit: int = 10) -> pd.DataFrame:
    """회사명 부분 일치 검색 (앞부분 일치 → 포함 순, 대소문자·공백 무시)."""
    key = query.lower().replace(" ", "")
    if not key:
        return df.iloc[0:0]
    names = df["name"].str.lower().str.replace(" ", "", regex=False)
    exact = df[names == key]
    starts = df[names.str.startswith(key) & (names != key)]
    contains = df[names.str.contains(key, regex=False) & ~names.str.startswith(key)]
    by_code = df[df["code"] == key.zfill(6)] if key.isdigit() else df.iloc[0:0]
    out = pd.concat([by_code, exact, starts.sort_values("name", key=lambda s: s.str.len()),
                     contains])
    return out.drop_duplicates("symbol").head(limit)
