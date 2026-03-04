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
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup
# ─── pkg_resources shim (Streamlit Cloud uv 환경 버그 우회용) ──────────────────
# pykrx 1.2.x 에서는 여전히 __init__.py 에서 pkg_resources를 import 합니다.
# Streamlit Cloud 최신 환경에서는 setuptools가 명시적이어도 import가 꼬이는 경우가 있어
# pykrx가 사용하는 최소한의 dummy 함수만 있는 가짜 모듈을 sys.modules에 주입합니다.
try:
    import pkg_resources  # noqa: F401
except ImportError:
    import sys
    import types
    _pkg = types.ModuleType("pkg_resources")
    _pkg.resource_filename = lambda *a, **kw: ""  # type: ignore[assignment]
    _pkg.resource_string = lambda *a, **kw: b""  # type: ignore[assignment]
    _pkg.get_distribution = lambda name: type("Dist", (), {"version": "0.0.0"})()  # type: ignore[assignment]
    sys.modules["pkg_resources"] = _pkg

# ─── pykrx Session Patch (KRX API 인증 요구 대응, Issue #276/#277) ─────────────
# KRX가 2026-02-27부터 JSESSIONID 쿠키 인증을 요구하도록 API를 변경했습니다.
# pykrx의 Post/Get.read()를 인증 세션으로 교체하여 빈 값 반환 문제를 해결합니다.
try:
    from krx_session import ensure_pykrx_patched
    ensure_pykrx_patched()
except Exception as _patch_err:
    print(f"[krx_data] pykrx patch 건너뜀: {_patch_err}")

# ─── Constants ───────────────────────────────────────────────────────────────
_KRX_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krx_mapping_cache.json")

INTRADAY_INTERVALS = [
    "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)",
    "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)",
]

_INTERVAL_MAP: dict[str, str] = {
    "1시간 (60 Minute)": "60m",
    "30분 (30 Minute)": "30m",
    "10분 (10 Minute)": "15m",  # yfinance는 10m을 지원하지 않으므로 가장 가까운 15m으로 우회
    "5분 (5 Minute)": "5m",
    "3분 (3 Minute)": "2m",   # yfinance는 3m을 지원하지 않으므로 가장 가까운 2m으로 우회
    "1분 (1 Minute)": "1m",
}

_INTRADAY_MAX_DAYS: dict[str, int] = {
    "1시간 (60 Minute)": 30,
    "30분 (30 Minute)": 14,
    "10분 (10 Minute)": 7,
    "5분 (5 Minute)": 5,
    "3분 (3 Minute)": 5,
    "1분 (1 Minute)": 5,
}


# ─── Ticker Mapping ───────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner="KRX 종목 마스터 로딩 중...")
def get_krx_mapping(cache_bust: int = 2) -> dict[str, str]:
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

    # 로컬 JSON 캐시가 24시간 이내로 최신이면 네트워크 송수신 없이 즉시 반환 (속도 극대화)
    try:
        if os.path.exists(_KRX_CACHE_FILE):
            import time
            if (time.time() - os.path.getmtime(_KRX_CACHE_FILE)) < 86400:
                with open(_KRX_CACHE_FILE, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
                if mapping:
                    return mapping
    except Exception:
        pass

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


@st.cache_data(ttl=60, show_spinner=False)
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
                kst = timezone(timedelta(hours=9))
                now_kst = datetime.now(tz=kst).replace(tzinfo=None)
                if df.index[-1].date() == now_kst.date():
                    idx = df.index.tolist()
                    idx[-1] = now_kst
                    df.index = pd.DatetimeIndex(idx)

            if m_name == "KRX":
                try:
                    kospi = fdr.StockListing("KOSPI")
                    m_name = "KOSPI" if ("Code" in kospi.columns and code in kospi["Code"].values) else "KOSDAQ"
                except Exception:
                    pass

        return df, m_name

    except Exception as e:
        import traceback; traceback.print_exc()
        return pd.DataFrame(), "KRX"


def clamp_intraday_dates(interval: str, start: datetime, end: datetime) -> datetime:
    """인트라데이 봉 유형에 따라 시작일을 제한하고 경고를 표시합니다."""
    max_days = _INTRADAY_MAX_DAYS.get(interval)
    if max_days and (end - start).days > max_days:
        name = interval.split(" ")[0]
        st.warning(f"{name} 봉은 최대 {max_days}일 데이터만 제공됩니다. 기간을 자동 조정합니다.")
        return end - timedelta(days=max_days - 1)
    return start



# ─── KRX Rankings (FDR 전 종목 병렬 조회 방식) ────────────────────────────────

def _fetch_one_stock_ohlcv(code: str, date_str: str) -> tuple[str, dict | None]:
    """단일 종목의 특정 날짜 OHLCV를 FDR DataReader로 가져옵니다."""
    import FinanceDataReader as fdr

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = fdr.DataReader(code, date_str, date_str)
        if df.empty:
            return code, None
        row = df.iloc[-1].rename({
            "Open": "시가", "High": "고가", "Low": "저가",
            "Close": "종가", "Volume": "거래량",
        }).to_dict()
        if row.get("거래량", 0) == 0:
            return code, None
        row["_code"] = code
        return code, row
    except Exception:
        return code, None


def _get_top_tickers_from_naver() -> dict[str, dict]:
    """네이버 금융 거래량/거래대금 상위 페이지를 스크래핑하여 대상 종목 코드 및 실시간 시세 반환합니다.

    - KOSPI 거래량/거래대금 (각 최대 100개)
    - KOSDAQ 거래량/거래대금 (각 최대 100개)
    총 약 150~200개의 고유 종목 코드를 매우 빠르게 수집합니다.
    """
    urls = [
        "https://finance.naver.com/sise/sise_quant.naver",        # 코스피 거래량
        "https://finance.naver.com/sise/sise_quant.naver?sosok=1", # 코스닥 거래량
        "https://finance.naver.com/sise/sise_quant_high.naver",        # 코스피 거래대금
        "https://finance.naver.com/sise/sise_quant_high.naver?sosok=1" # 코스닥 거래대금
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    tickers = {}
    
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            # a 태그 중 href가 code= 로 끝나는 종목 링크 및 해당 tr 추출
            rows = soup.select("table.type_2 tr")
            for row in rows:
                a = row.find("a", class_="tltle")
                if not a: continue
                
                href = a.get("href", "")
                if "code=" in href:
                    code = href.split("code=")[-1]
                    name = a.text.strip()
                    # ETF/ETN (통상 5~6자리지만 숫자로만 구성됨)
                    if len(code) == 6 and code.isdigit():
                        tds = row.find_all("td", class_="number")
                        if len(tds) >= 5:
                            try:
                                price = float(tds[0].text.strip().replace(",", ""))
                                pct_str = tds[2].text.strip().replace("%", "").strip()
                                pct = float(pct_str) if pct_str and pct_str != "0.00" else 0.0
                                vol = float(tds[3].text.strip().replace(",", ""))
                                val = float(tds[4].text.strip().replace(",", "")) * 1_000_000 # 백만원 단위
                                
                                tickers[code] = {
                                    "종목명": name,
                                    "현재가_live": price,
                                    "등락률_live": pct,
                                    "거래량_live": vol,
                                    "거래대금_live": val
                                }
                            except ValueError:
                                tickers[code] = {"종목명": name}
                        else:
                            tickers[code] = {"종목명": name}
        except Exception:
            continue
            
    return tickers


@st.cache_data(ttl=600, show_spinner=False)
def get_krx_ranking() -> pd.DataFrame:
    """네이버 증권 시세 페이지에서 (거래량, 거래대금) 상위 100~200 종목 코드만 추출한 뒤
    FDR을 통해 해당 종목들만 병렬 fetch하여 반환합니다.
    수천 개의 전체 종목 API 호출을 생략하여 타임아웃 오류 없이 즉시 렌더링됩니다.
    """
    codes_dict = _get_top_tickers_from_naver()
    
    if not codes_dict:
        # Fallback: 로컬 캐시에서 일부라도 가져오기 시도
        mapping = get_krx_mapping()
        if mapping:
            codes = list(mapping.keys())[:200]
            codes_dict = {c: {"종목명": mapping[c]} for c in codes}
        else:
            st.warning("⚠️ 실시간 랭킹 종목 목록을 가져오는데 실패했습니다.")
            return pd.DataFrame()
    else:
        codes = list(codes_dict.keys())

    # 최근 5 거래일 역순 시도
    for delta in range(5):
        check_date = datetime.today() - timedelta(days=delta)
        date_str = check_date.strftime("%Y-%m-%d")

        rows: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
            futs = {ex.submit(_fetch_one_stock_ohlcv, code, date_str): code for code in codes}
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=120):
                    try:
                        _, row = fut.result()
                        if row is not None:
                            rows.append(row)
                    except Exception:
                        pass
            except concurrent.futures.TimeoutError:
                st.warning("⚠️ 일부 종목 데이터를 가져오는 중 지연이 발생하여 수집된 데이터까지만 표시합니다.")

        if not rows:
            continue

        df = pd.DataFrame(rows)

        # 숫자형 변환 및 거래량 필터
        for col in ("시가", "고가", "저가", "종가", "거래량"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "거래량" in df.columns:
            df = df[df["거래량"] > 0]

        if df.empty:
            continue

        # 실시간 네이버 시세(Live Price) 강제 덮어쓰기
        if "_code" in df.columns:
            def _get_live(code, key):
                val = codes_dict.get(code, {}).get(key)
                return val if val is not None else float("nan")
                
            df["현재가_live"] = df["_code"].map(lambda x: _get_live(x, "현재가_live"))
            df["등락률_live"] = df["_code"].map(lambda x: _get_live(x, "등락률_live"))
            df["거래량_live"] = df["_code"].map(lambda x: _get_live(x, "거래량_live"))
            df["거래대금_live"] = df["_code"].map(lambda x: _get_live(x, "거래대금_live"))
            
            mask = df["현재가_live"].notna()
            if "종가" in df.columns:
                df.loc[mask, "종가"] = df.loc[mask, "현재가_live"]
            if "현재가" in df.columns:
                df.loc[mask, "현재가"] = df.loc[mask, "현재가_live"]
            if "등락률" in df.columns:
                df.loc[mask, "등락률"] = df.loc[mask, "등락률_live"]
            if "거래량" in df.columns:
                df.loc[mask, "거래량"] = df.loc[mask, "거래량_live"]
            if "거래대금" in df.columns:
                df.loc[mask, "거래대금"] = df.loc[mask, "거래대금_live"]
                
            # 고가, 저가가 실시간 현재가 범위를 벗어났으면 보정
            if "고가" in df.columns:
                df.loc[mask, "고가"] = df[["고가", "현재가_live"]].max(axis=1)
            if "저가" in df.columns:
                df.loc[mask, "저가"] = df[["저가", "현재가_live"]].min(axis=1)

        # 등락률 및 거래대금(위에서 안 덮어씌워진 경우) 추가 계산
        if "등락률" not in df.columns and "시가" in df.columns and "종가" in df.columns:
            s = df["시가"].replace(0, float("nan"))
            df["등락률"] = ((df["종가"] - s) / s * 100).round(2)

        if "거래대금" not in df.columns and "종가" in df.columns and "거래량" in df.columns:
            df["거래대금"] = df["종가"] * df["거래량"]

        if "종가" in df.columns and "현재가" not in df.columns:
            df["현재가"] = df["종가"]

        df["종목명"] = df["_code"].map(lambda x: codes_dict.get(x, {}).get("종목명"))

        if "_code" in df.columns:
            df = df.set_index("_code")

        return df.sort_values("거래량", ascending=False) if "거래량" in df.columns else df

    return pd.DataFrame()
