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



# ─── KRX Rankings ─────────────────────────────────────────────────────────────
# 전략: KRX 직접 API(1순위) → FDR 전체 종목 병렬(폴백)

_KRX_API_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer":    "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
_KRX_COL_MAP = {
    "ISU_SRT_CD": "_ticker", "ISU_ABBRV": "종목명_raw",
    "TDD_OPNPRC": "시가",    "TDD_HGPRC": "고가",
    "TDD_LWPRC":  "저가",    "TDD_CLSPRC": "종가",
    "ACC_TRDVOL": "거래량",  "ACC_TRDVAL": "거래대금",
    "FLUC_RT":    "등락률",
}
# KRX JSON 응답에서 데이터 리스트를 찾아내기 위해 시도할 키 이름들
_KRX_OUTPUT_KEYS = ("output", "OutBlock_1", "output1", "data", "result")


def _parse_krx_rows(json_data: dict) -> list:
    """KRX API JSON 응답에서 데이터 행 리스트를 추출합니다."""
    for key in _KRX_OUTPUT_KEYS:
        rows = json_data.get(key)
        if rows:
            return rows
    # 값이 list인 첫 번째 키 찾기 (키 이름이 뭔지 몰라도 처리)
    for val in json_data.values():
        if isinstance(val, list) and val:
            return val
    return []


def _fetch_krx_market(date_str: str) -> tuple[pd.DataFrame, str]:
    """KRX data API로 전 종목 OHLCV를 fetch. 성공 시 (df, "krx"), 실패 시 (empty, reason)."""
    sess = requests.Session()
    sess.headers.update(_KRX_HEADERS)
    try:
        sess.get("http://data.krx.co.kr/", timeout=8)
    except Exception:
        pass

    all_rows: list[dict] = []
    debug_keys: list[str] = []

    for mkt in ("STK", "KSQ", "KNX"):
        payload = {
            "bld":         "dbms/MDC/STAT/standard/MDCSTAT02501",
            "locale":      "ko_KR",
            "mktId":       mkt,
            "trdDd":       date_str,
            "share":       "1",
            "money":       "1",
            "csvxls_isNo": "false",
        }
        try:
            resp = sess.post(_KRX_API_URL, data=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            debug_keys.append(f"{mkt}:{list(data.keys())[:4]}")
            rows = _parse_krx_rows(data)
            all_rows.extend(rows)
        except Exception as exc:
            debug_keys.append(f"{mkt}:err({exc})")

    if not all_rows:
        return pd.DataFrame(), f"빈 응답 (JSON keys: {debug_keys})"

    df = pd.DataFrame(all_rows).rename(columns=_KRX_COL_MAP)
    num_cols = ["시가", "고가", "저가", "종가", "거래량", "거래대금", "등락률"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
    if "_ticker" in df.columns:
        df = df.set_index("_ticker")
    if "종가" in df.columns:
        df["현재가"] = df["종가"]
    return df, "krx"


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


def _fdr_full_market_ranking() -> pd.DataFrame:
    """FDR로 KOSPI+KOSDAQ 전 종목 당일 OHLCV를 병렬 fetch해 거래량 기준 반환합니다."""
    import FinanceDataReader as fdr

    codes: list[str] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                listing = fdr.StockListing(market)
            code_col = next((c for c in ("Code", "Symbol") if c in listing.columns), None)
            if code_col:
                codes.extend(listing[code_col].dropna().astype(str).tolist())
        except Exception:
            pass

    if not codes:
        return pd.DataFrame()

    results: dict[str, pd.DataFrame] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        futs = {ex.submit(_fdr_today_ohlcv, c): c for c in codes}
        for fut in concurrent.futures.as_completed(futs, timeout=60):
            code, df = fut.result()
            if not df.empty:
                results[code] = df

    if not results:
        return pd.DataFrame()

    rename = {"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량"}
    rows = []
    for code, df in results.items():
        row = df.rename(columns=rename).iloc[-1].to_dict()
        row["_code"] = code
        rows.append(row)

    result_df = pd.DataFrame(rows).set_index("_code")
    if "등락률" not in result_df.columns and "시가" in result_df.columns and "종가" in result_df.columns:
        s = result_df["시가"].replace(0, float("nan"))
        result_df["등락률"] = ((result_df["종가"] - s) / s * 100).round(2)
    if "거래대금" not in result_df.columns and "종가" in result_df.columns and "거래량" in result_df.columns:
        result_df["거래대금"] = result_df["종가"] * result_df["거래량"]
    if "종가" in result_df.columns:
        result_df["현재가"] = result_df["종가"]
    if "거래량" in result_df.columns:
        result_df = result_df[result_df["거래량"] > 0]
    return result_df.sort_values("거래량", ascending=False) if "거래량" in result_df.columns else result_df


@st.cache_data(ttl=120, show_spinner=False)
def get_krx_ranking() -> pd.DataFrame:
    """전체 시장 거래량 상위 종목 OHLCV를 반환합니다.

    1순위: KRX 직접 HTTP API (data.krx.co.kr, 전 종목 단일 요청)
    2순위: FinanceDataReader 전 종목 병렬 fetch (1순위 실패 시)
    반환 DataFrame: 인덱스=종목코드, 컬럼=시가/고가/저가/종가/거래량/거래대금/등락률/현재가
    """
    check_date = datetime.today()
    krx_errors: list[str] = []

    # 1순위: KRX 직접 API (최근 10 거래일 역순)
    for _ in range(10):
        d_str = check_date.strftime("%Y%m%d")
        df, reason = _fetch_krx_market(d_str)
        if not df.empty:
            vol_col = "거래량" if "거래량" in df.columns else None
            if vol_col and df[vol_col].sum() > 0:
                return df
            krx_errors.append(f"{d_str}: 거래량 합계 0")
        else:
            krx_errors.append(f"{d_str}: {reason}")
        check_date -= timedelta(days=1)

    # KRX API 실패 이유 표시
    st.warning("⚠️ KRX 직접 API 실패, FDR 전체 종목 모드로 전환 중...\n" + "\n".join(f"- {e}" for e in krx_errors[:3]))

    # 2순위: FDR 전 종목 병렬 fetch (시간이 더 걸림)
    df = _fdr_full_market_ranking()
    if df.empty:
        st.info("장 시작 전이거나 휴장일입니다. (No Data for Ranking)")
    return df





