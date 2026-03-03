"""krx_data.py — KRX data fetching layer.

모든 KRX(한국 주식) 관련 데이터 fetch/캐싱 로직을 담당합니다.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ─── pkg_resources shim ──────────────────────────────────────────────────────
# pykrx 1.0.51 uses pkg_resources at import time (get_distribution, resource_filename).
# In uv/venv environments, pkg_resources may be missing OR present-but-incomplete.
# We inject/patch a minimal shim covering every attribute pykrx actually uses.
def _make_resource_filename():
    import importlib.util as _ilu
    import os as _os

    def _resource_filename(package_or_req: str, resource_name: str) -> str:
        try:
            spec = _ilu.find_spec(package_or_req)
            if spec and spec.origin:
                return _os.path.join(_os.path.dirname(spec.origin), resource_name)
        except Exception:
            pass
        return resource_name

    return _resource_filename


try:
    import pkg_resources  # noqa: F401
    # Even if import succeeds, the installed version may be incomplete.
    if not hasattr(pkg_resources, "resource_filename"):
        pkg_resources.resource_filename = _make_resource_filename()  # type: ignore[attr-defined]
    if not hasattr(pkg_resources, "resource_string"):
        pkg_resources.resource_string = lambda *a, **kw: b""  # type: ignore[attr-defined]
except ImportError:
    import importlib.metadata as _ilm
    import types as _types

    _pkg = _types.ModuleType("pkg_resources")

    class _Dist:
        def __init__(self, name: str) -> None:
            try:
                self.version = _ilm.version(name)
            except _ilm.PackageNotFoundError:
                self.version = "0.0.0"
        def __str__(self) -> str:
            return self.version

    _pkg.get_distribution = lambda name: _Dist(name)  # type: ignore[assignment]
    _pkg.require = lambda *a, **kw: []  # type: ignore[assignment]
    _pkg.resource_filename = _make_resource_filename()  # type: ignore[assignment]
    _pkg.resource_string = lambda *a, **kw: b""  # type: ignore[assignment]
    _pkg.resource_listdir = lambda *a, **kw: []  # type: ignore[assignment]
    _pkg.resource_exists = lambda *a, **kw: False  # type: ignore[assignment]
    _pkg.DistributionNotFound = Exception  # type: ignore[assignment]
    _pkg.VersionConflict = Exception  # type: ignore[assignment]
    sys.modules["pkg_resources"] = _pkg




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
        # FDR이 KRX 서버 장애 시 HTML 에러 페이지를 stdout으로 출력하므로 억제합니다.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
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

    # 로컬 캐시도 없을 때: 경고만 표시하고 빈 dict 반환 (text_input 폴백 사용)
    # NOTE: get_krx_mapping.clear()를 호출하면 캐시가 지워져 매 리런마다 재시도됩니다 — 절대 하지 않습니다.
    st.warning(
        "⚠️ KRX 종목 목록을 가져오는데 실패했습니다. (KRX 서버 일시 장애)\n"
        "아래 **종목 코드 직접 입력** 으로 개별 종목 분석은 계속 사용하실 수 있습니다."
    )
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



# ─── KRX Rankings (FinanceDataReader) ────────────────────────────────────────

def _fdr_listing() -> pd.DataFrame:
    """KOSPI+KOSDAQ 전 종목 정보(코드, 이름, 시가총액, 현재가 등)를 FDR로 반환합니다."""
    import FinanceDataReader as fdr

    frames: list[pd.DataFrame] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = fdr.StockListing(market)
            if not df.empty:
                df["_market"] = market
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _fdr_today_ohlcv(code: str) -> tuple[str, pd.DataFrame]:
    """단일 종목의 오늘 OHLCV를 FDR로 가져옵니다."""
    import FinanceDataReader as fdr

    today = datetime.today().strftime("%Y-%m-%d")
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = fdr.DataReader(code, today, today)
        return code, df
    except Exception:
        return code, pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def get_krx_ranking() -> pd.DataFrame:
    """FinanceDataReader로 KOSPI+KOSDAQ 거래량 상위 종목 OHLCV를 반환합니다.

    1단계: StockListing으로 전 종목 + 시가총액 조회
    2단계: 시가총액 상위 N개의 당일 OHLCV를 병렬 fetch
    3단계: 거래량 기준 정렬 반환
    반환 DataFrame: 인덱스=종목코드, 컬럼=시가/고가/저가/종가/거래량/거래대금/등락률/현재가
    """
    import FinanceDataReader as fdr

    # 1단계: 전 종목 리스팅
    listing = _fdr_listing()
    if listing.empty:
        st.warning("⚠️ FDR 종목 리스팅 실패")
        return pd.DataFrame()

    # Code 컬럼 확인
    code_col = next((c for c in ("Code", "Symbol", "code") if c in listing.columns), None)
    if code_col is None:
        st.warning(f"⚠️ FDR 종목 코드 컬럼 없음 (컬럼: {list(listing.columns[:8])})")
        return pd.DataFrame()

    # 시가총액 기준 상위 N개 선정 (없으면 순서대로)
    marcap_col = next((c for c in ("Marcap", "MarCap", "marcap", "시가총액") if c in listing.columns), None)
    if marcap_col:
        listing[marcap_col] = pd.to_numeric(listing[marcap_col], errors="coerce").fillna(0)
        top_listing = listing.sort_values(marcap_col, ascending=False).head(60)
    else:
        top_listing = listing.head(60)

    codes = top_listing[code_col].dropna().astype(str).tolist()

    # 2단계: 병렬로 당일 OHLCV fetch
    today = datetime.today().strftime("%Y-%m-%d")
    results: dict[str, pd.DataFrame] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        futures = {ex.submit(_fdr_today_ohlcv, code): code for code in codes}
        for fut in concurrent.futures.as_completed(futures, timeout=20):
            code, df = fut.result()
            if not df.empty:
                results[code] = df

    if not results:
        st.warning("⚠️ 당일 OHLCV 조회 결과 없음 (장전/휴장)")
        return pd.DataFrame()

    # 3단계: 결과 조합
    rows = []
    rename = {"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량"}
    for code, df in results.items():
        row = df.rename(columns=rename).iloc[-1].to_dict()
        row["_code"] = code
        rows.append(row)

    result_df = pd.DataFrame(rows).set_index("_code")

    # 등락률 계산 (없으면 시가→종가 근사)
    if "등락률" not in result_df.columns and "시가" in result_df.columns and "종가" in result_df.columns:
        시가 = result_df["시가"].replace(0, float("nan"))
        result_df["등락률"] = ((result_df["종가"] - 시가) / 시가 * 100).round(2)

    # 거래대금 계산 (없으면 종가 × 거래량)
    if "거래대금" not in result_df.columns and "종가" in result_df.columns and "거래량" in result_df.columns:
        result_df["거래대금"] = result_df["종가"] * result_df["거래량"]

    if "종가" in result_df.columns:
        result_df["현재가"] = result_df["종가"]

    # 거래량 0인 행 제거 (장전 데이터)
    if "거래량" in result_df.columns:
        result_df = result_df[result_df["거래량"] > 0]

    return result_df.sort_values("거래량", ascending=False) if "거래량" in result_df.columns else result_df




