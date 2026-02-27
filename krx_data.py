"""krx_data.py — KRX data fetching layer.

모든 KRX(한국 주식) 관련 데이터 fetch/캐싱 로직을 담당합니다.
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ─── Constants ───────────────────────────────────────────────────────────────
_KRX_CACHE_FILE = "krx_mapping_cache.json"

INTRADAY_INTERVALS = [
    "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)",
    "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)",
]

_INTERVAL_MAP: dict[str, str] = {
    "1시간 (60 Minute)": "60m",
    "30분 (30 Minute)": "30m",
    "10분 (10 Minute)": "10m",
    "5분 (5 Minute)": "5m",
    "3분 (3 Minute)": "3m",
    "1분 (1 Minute)": "1m",
}

_INTRADAY_MAX_DAYS: dict[str, int] = {
    "1시간 (60 Minute)": 30,
    "30분 (30 Minute)": 14,
    "10분 (10 Minute)": 7,
    "5분 (5 Minute)": 4,
    "3분 (3 Minute)": 2,
    "1분 (1 Minute)": 1,
}


# ─── Ticker Mapping ───────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner="KRX 종목 마스터 로딩 중...")
def get_krx_mapping() -> dict[str, str]:
    """코드→종목명 매핑을 반환합니다.

    순서: KRX → KRX-DESC → KOSPI/KOSDAQ 병합 → 로컬 JSON 캐시
    """
    import FinanceDataReader as fdr

    def _save(mapping: dict) -> None:
        try:
            with open(_KRX_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False)
        except Exception:
            pass

    def _try_fdr(market: str) -> dict[str, str]:
        df = fdr.StockListing(market)
        if not df.empty and "Code" in df.columns and "Name" in df.columns:
            return dict(zip(df["Code"], df["Name"]))
        return {}

    for market in ("KRX", "KRX-DESC"):
        try:
            mapping = _try_fdr(market)
            if mapping:
                _save(mapping)
                return mapping
        except Exception:
            pass

    # KOSPI + KOSDAQ 병합 폴백
    try:
        combined: dict[str, str] = {}
        for market in ("KOSPI", "KOSDAQ"):
            combined.update(_try_fdr(market))
        if combined:
            _save(combined)
            return combined
    except Exception:
        pass

    # 로컬 JSON 캐시 최후 폴백
    try:
        if os.path.exists(_KRX_CACHE_FILE):
            with open(_KRX_CACHE_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            if mapping:
                st.warning("KRX 접속 장애로 인해 로컬에 저장된 이전 종목 마스터를 사용합니다.")
                return mapping
    except Exception:
        pass

    st.error("종목 목록을 가져오는데 실패했습니다 (KRX, KRX-DESC 수배 오류). 일시적인 접속장애일 수 있습니다.")
    get_krx_mapping.clear()
    return {}


def build_name_to_ticker(ticker_to_name: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """종목명→코드 매핑과 정렬된 이름 목록을 반환합니다. 동명 종목은 코드를 괄호에 표시합니다."""
    name_counts: dict[str, int] = {}
    for name in ticker_to_name.values():
        name_counts[name] = name_counts.get(name, 0) + 1

    name_to_ticker: dict[str, str] = {}
    for ticker, name in ticker_to_name.items():
        display = f"{name} ({ticker})" if name_counts[name] > 1 else name
        name_to_ticker[display] = ticker

    return name_to_ticker, sorted(name_to_ticker.keys())


# ─── Data Fetching ────────────────────────────────────────────────────────────

def _fetch_chunk(func, s: datetime, e: datetime, code: str, **kwargs) -> pd.DataFrame:
    try:
        return func(s.strftime("%Y%m%d"), e.strftime("%Y%m%d"), code, **kwargs)
    except Exception:
        return pd.DataFrame()


def fetch_krx_chunked(func, start_d: datetime, end_d: datetime, code: str, **kwargs) -> pd.DataFrame:
    """180일 단위로 날짜를 분할하여 병렬로 KRX 데이터를 가져옵니다."""
    chunks: list[tuple[datetime, datetime]] = []
    curr = start_d
    while curr < end_d:
        nxt = min(curr + timedelta(days=180), end_d)
        chunks.append((curr, nxt))
        curr = nxt + timedelta(days=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_chunk, func, s, e, code, **kwargs) for s, e in chunks]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    valid = [r for r in results if not r.empty]
    if not valid:
        return pd.DataFrame()

    df = pd.concat(valid).sort_index()
    return df[~df.index.duplicated(keep="last")]


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """한글 컬럼명을 영문 OHLCV로 변환합니다."""
    rename = {"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume"}
    return df.rename(columns=rename)


def _flatten_multiindex(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yfinance MultiIndex 컬럼을 평탄화합니다."""
    if isinstance(df.columns, pd.MultiIndex):
        try:
            return df.xs(ticker, level=1, axis=1)
        except Exception:
            df.columns = df.columns.get_level_values(0)
    return df


def _to_kst(df: pd.DataFrame) -> pd.DataFrame:
    """timezone-aware 인덱스를 KST naive로 변환합니다."""
    if not df.empty and df.index.tzinfo is not None:
        df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_krx_data(code: str, s_str: str, e_str: str, interval: str, extra_data: list) -> tuple[pd.DataFrame, str]:
    """KRX 종목 OHLCV 데이터를 반환합니다. (ticker_code, market_name)"""
    import FinanceDataReader as fdr

    start_d = datetime.strptime(s_str, "%Y%m%d")
    end_d = datetime.strptime(e_str, "%Y%m%d")
    df = pd.DataFrame()
    m_name = "KRX"

    try:
        if interval in INTRADAY_INTERVALS:
            fetch_int = _INTERVAL_MAP[interval]
            suffix = ".KS"
            try:
                kosdaq = fdr.StockListing("KOSDAQ")
                if "Code" in kosdaq.columns and code in kosdaq["Code"].values:
                    suffix = ".KQ"
                    m_name = "KOSDAQ"
                else:
                    m_name = "KOSPI"
            except Exception:
                pass

            yf_ticker = code + suffix
            df = yf.download(yf_ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
            df = _flatten_multiindex(df, yf_ticker)
            df = _to_kst(df)
        else:
            safe_end = datetime.today().strftime("%Y-%m-%d")
            start_fdr = f"{s_str[:4]}-{s_str[4:6]}-{s_str[6:]}"

            if interval in ("일/주/월/연봉 종합분석", "연봉 (Yearly)"):
                df = fdr.DataReader(code, "1990-01-01", safe_end)
            else:
                df = fdr.DataReader(code, start_fdr, safe_end)

        if not df.empty:
            df = _normalize_ohlcv(df)

            if interval in ("일/주/월/연봉 종합분석", "일봉 (Daily)"):
                from us_data import append_live_minute_data
                df = append_live_minute_data(df, code, m_name)

            if m_name == "KRX":
                try:
                    kospi = fdr.StockListing("KOSPI")
                    m_name = "KOSPI" if ("Code" in kospi.columns and code in kospi["Code"].values) else "KOSDAQ"
                except Exception:
                    pass

        return df, m_name

    except Exception:
        return pd.DataFrame(), "KRX"


def clamp_intraday_dates(interval: str, start: datetime, end: datetime) -> datetime:
    """인트라데이 봉 유형에 따라 시작일을 제한하고 경고를 표시합니다."""
    max_days = _INTRADAY_MAX_DAYS.get(interval)
    if max_days and (end - start).days > max_days:
        name = interval.split(" ")[0]
        st.warning(f"{name} 봉은 최대 {max_days}일 데이터만 제공됩니다. 기간을 자동 조정합니다.")
        return end - timedelta(days=max_days - 1)
    return start


# ─── Naver Rankings ───────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_naver_ranking(kind: str = "quant") -> pd.DataFrame:
    """네이버 금융 거래량(quant) 또는 거래대금(amount) Top 랭킹을 반환합니다."""
    from bs4 import BeautifulSoup

    url = (
        "https://finance.naver.com/sise/sise_quant_high.naver"
        if kind == "amount"
        else "https://finance.naver.com/sise/sise_quant.naver"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        ticker_map = {a.text: a["href"].split("code=")[-1] for a in soup.select("a.tltle")}

        dfs = pd.read_html(io.StringIO(r.text), encoding="euc-kr")
        df = dfs[1].dropna(how="all").copy()

        if kind == "quant":
            want = ["N", "종목명", "현재가", "전일비", "등락률", "거래량", "거래대금", "매수호가", "매도호가", "시가총액", "PER", "ROE"]
        else:
            want = ["N", "종목명", "현재가", "전일비", "등락률", "거래대금", "거래량", "매수호가", "매도호가", "시가총액", "PER", "ROE"]

        df = df[[c for c in want if c in df.columns]]
        df["Ticker"] = df["종목명"].map(ticker_map)

        for col in ("현재가", "거래량", "거래대금"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

        if "등락률" in df.columns:
            df["등락률"] = pd.to_numeric(
                df["등락률"].astype(str).str.replace("%", "").str.replace("+", ""),
                errors="coerce",
            )

        return df
    except Exception:
        return pd.DataFrame()
