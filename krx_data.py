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
import time
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

# ─── pkg_resources shim (Streamlit Cloud uv 환경 버그 우회용) ──────────────────
# pykrx 1.2.x 에서 pkg_resources를 import 하는데, 일부 환경에서 import가 꼬이는 경우를
# 방지하기 위해 최소한의 dummy 모듈을 sys.modules에 주입합니다.
try:
    import pkg_resources  # noqa: F401
except ImportError:
    import types as _types
    _pkg = _types.ModuleType("pkg_resources")
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

# FinanceDataReader는 처음 import 시 HTTP 요청이 발생할 수 있어 try/except로 감쌉니다.
try:
    import FinanceDataReader as fdr
except Exception as _fdr_err:
    fdr = None  # type: ignore[assignment]
    print(f"[krx_data] FinanceDataReader import 실패: {_fdr_err}")

# ─── Constants ───────────────────────────────────────────────────────────────
_KRX_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krx_mapping_cache.json")

INTRADAY_INTERVALS = [
    "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)",
    "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)",
]

_INTRADAY_MAX_DAYS: dict[str, int] = {
    "1시간 (60 Minute)": 30,
    "30분 (30 Minute)": 14,
    "10분 (10 Minute)": 7,
    "5분 (5 Minute)": 5,
    "3분 (3 Minute)": 5,
    "1분 (1 Minute)": 5,
}


# ─── Ticker Mapping ───────────────────────────────────────────────────────────

def get_krx_mapping_instant() -> dict[str, str]:
    """로컬 JSON 캐시에서 즉시 종목 매핑을 반환합니다 (네트워크 요청 없음).

    캐시 파일이 있으면 날짜 무관하게 바로 반환, 없으면 빈 dict를 반환합니다.
    UI를 블로킹하지 않기 위해 @st.cache_data를 사용하지 않습니다.
    """
    try:
        if os.path.exists(_KRX_CACHE_FILE):
            with open(_KRX_CACHE_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            if mapping:
                return mapping
    except Exception:
        pass
    return {}


@st.cache_data(ttl=86400, show_spinner="KRX 종목 마스터 로딩 중...")
def get_krx_mapping(cache_bust: int = 2) -> dict[str, str]:
    """코드→종목명 매핑을 반환합니다.

    순서: KRX → KRX-DESC → KOSPI/KOSDAQ 병합 → 로컬 JSON 캐시
    """
    def _save(mapping: dict) -> None:
        try:
            with open(_KRX_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False)
        except Exception:
            pass

    def _try_fdr(market: str) -> dict[str, str]:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = fdr.StockListing(market)
        if not df.empty and "Code" in df.columns and "Name" in df.columns:
            return dict(zip(df["Code"], df["Name"]))
        return {}

    # 로컬 JSON 캐시가 24시간 이내면 네트워크 없이 즉시 반환
    try:
        if os.path.exists(_KRX_CACHE_FILE) and (time.time() - os.path.getmtime(_KRX_CACHE_FILE)) < 86400:
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
    return df.rename(columns={"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume"})


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


def _fetch_naver_realtime_price(code: str) -> dict | None:
    """네이버 금융 폴링 API에서 특정 종목의 실시간 현재가/시가/고가/저가를 가져옵니다.

    Returns:
        dict with keys: current, open, high, low  (float values)
        None if fetch fails or market is closed.
    """
    kst = timezone(timedelta(hours=9))
    now = datetime.now(tz=kst)
    # 장 시간 외(09:00 ~ 15:35)는 보정하지 않음
    if not (now.weekday() < 5 and (9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 35))):
        return None

    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_REALTIME_STOCK_TICKS:{code}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=3)
        data = resp.json()
        inner = data.get("result", {}).get(f"SERVICE_REALTIME_STOCK_TICKS:{code}", {})
        datas = inner.get("datas", [])
        if not datas:
            return None
        item = datas[0]

        def _f(key: str) -> float | None:
            val = item.get(key)
            if val is None:
                return None
            try:
                return float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                return None

        current = _f("closePrice") or _f("nv")
        open_p = _f("openPrice") or _f("ov")
        high_p = _f("highPrice") or _f("hv")
        low_p = _f("lowPrice") or _f("lv")

        return {"current": current, "open": open_p, "high": high_p, "low": low_p} if current is not None else None
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_krx_data(code: str, s_str: str, e_str: str, interval: str, extra_data: list | tuple, include_nxt: bool = False) -> tuple[pd.DataFrame, str]:
    """KRX 종목 OHLCV 데이터를 반환합니다."""
    from kis_api import fetch_daily_history, fetch_intraday_history

    start_d = datetime.strptime(s_str, "%Y%m%d")
    m_name = "KRX"

    try:
        if interval in INTRADAY_INTERVALS:
            df = fetch_intraday_history(code)
            try:
                kosdaq = fdr.StockListing("KOSDAQ")
                m_name = "KOSDAQ" if ("Code" in kosdaq.columns and code in kosdaq["Code"].values) else "KOSPI"
            except Exception:
                m_name = "KOSPI"
        else:
            start_str = start_d.strftime("%Y%m%d")
            if interval in ("일/주/월/연봉 종합분석", "연봉 (Yearly)"):
                start_str = "19900101"
            safe_end = datetime.today().strftime("%Y%m%d")
            df = fetch_daily_history(code, start_str, safe_end)

            if m_name == "KRX":
                try:
                    kospi = fdr.StockListing("KOSPI")
                    m_name = "KOSPI" if ("Code" in kospi.columns and code in kospi["Code"].values) else "KOSDAQ"
                except Exception:
                    pass

        return df, m_name

    except Exception:
        traceback.print_exc()
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
    """네이버 금융 거래량/거래대금 상위 페이지를 스크래핑하여 대상 종목 코드 및 실시간 시세를 반환합니다.

    - KOSPI 거래량/거래대금 (각 최대 100개)
    - KOSDAQ 거래량/거래대금 (각 최대 100개)
    총 약 150~200개의 고유 종목 코드를 빠르게 수집합니다.
    """
    urls = [
        "https://finance.naver.com/sise/sise_quant.naver",
        "https://finance.naver.com/sise/sise_quant.naver?sosok=1",
        "https://finance.naver.com/sise/sise_quant_high.naver",
        "https://finance.naver.com/sise/sise_quant_high.naver?sosok=1",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    tickers: dict[str, dict] = {}

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            for row in soup.select("table.type_2 tr"):
                a = row.find("a", class_="tltle")
                if not a:
                    continue
                href = a.get("href", "")
                if "code=" not in href:
                    continue
                code = href.split("code=")[-1]
                name = a.text.strip()
                if not (len(code) == 6 and code.isdigit()):
                    continue
                tds = row.find_all("td", class_="number")
                if len(tds) >= 5:
                    try:
                        tickers[code] = {
                            "종목명": name,
                            "현재가_live": float(tds[0].text.strip().replace(",", "")),
                            "등락률_live": float(tds[2].text.strip().replace("%", "").strip() or "0"),
                            "거래량_live": float(tds[3].text.strip().replace(",", "")),
                            "거래대금_live": float(tds[4].text.strip().replace(",", "")) * 1_000_000,
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
    """네이버 증권 시세 페이지에서 거래량/거래대금 상위 100~200 종목을 반환합니다.

    FDR을 통해 해당 종목들만 병렬 fetch하여 전체 종목 스캔 없이 빠르게 렌더링됩니다.
    """
    codes_dict = _get_top_tickers_from_naver()

    if not codes_dict:
        mapping = get_krx_mapping()
        if mapping:
            codes_dict = {c: {"종목명": mapping[c]} for c in list(mapping.keys())[:200]}
        else:
            st.warning("⚠️ 실시간 랭킹 종목 목록을 가져오는데 실패했습니다.")
            return pd.DataFrame()

    codes = list(codes_dict.keys())

    for delta in range(5):
        date_str = (datetime.today() - timedelta(days=delta)).strftime("%Y-%m-%d")
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

        for col in ("시가", "고가", "저가", "종가", "거래량"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "거래량" in df.columns:
            df = df[df["거래량"] > 0]

        if df.empty:
            continue

        # 실시간 네이버 시세로 덮어쓰기
        if "_code" in df.columns:
            def _live(code: str, key: str):
                val = codes_dict.get(code, {}).get(key)
                return val if val is not None else float("nan")

            df["현재가_live"] = df["_code"].map(lambda x: _live(x, "현재가_live"))
            df["등락률_live"] = df["_code"].map(lambda x: _live(x, "등락률_live"))
            df["거래량_live"] = df["_code"].map(lambda x: _live(x, "거래량_live"))
            df["거래대금_live"] = df["_code"].map(lambda x: _live(x, "거래대금_live"))

            mask = df["현재가_live"].notna()
            for src, dst in (("현재가_live", "종가"), ("현재가_live", "현재가"), ("등락률_live", "등락률"), ("거래량_live", "거래량"), ("거래대금_live", "거래대금")):
                if dst in df.columns:
                    df.loc[mask, dst] = df.loc[mask, src]
            if "고가" in df.columns:
                df.loc[mask, "고가"] = df[["고가", "현재가_live"]].max(axis=1)
            if "저가" in df.columns:
                df.loc[mask, "저가"] = df[["저가", "현재가_live"]].min(axis=1)

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


# ─── NXT (Nextrade) Rankings ─────────────────────────────────────────────────

_NXT_API_URL = "https://www.nextrade.co.kr/brdinfoTime/brdinfoTimeList.do"
_NXT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.nextrade.co.kr/menu/transactionStatusMain/menuList.do",
    "X-Requested-With": "XMLHttpRequest",
}


@st.cache_data(ttl=300, show_spinner=False)
def get_nxt_ranking(rows: int = 50) -> pd.DataFrame:
    """넥스트레이드(NXT) API에서 거래량/거래대금 상위 종목을 가져옵니다.

    반환 DataFrame 컬럼:
        code (str): 6자리 종목코드
        종목명 (str)
        현재가 (float)
        등락률 (float)
        NXT거래량 (float)
        NXT거래대금 (float)
    """
    today_str = datetime.today().strftime("%Y%m%d")
    params = {
        "sidx": "accTdQty",
        "sord": "desc",
        "rows": str(rows),
        "scMktId": "",
        "scAggDd": today_str,
        "pageUnit": str(rows),
        "page": "1",
    }
    try:
        resp = requests.post(_NXT_API_URL, data=params, headers=_NXT_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rows_data = data.get("brdinfoTimeList") or data.get("rows") or []
        if not rows_data:
            for key in data:
                if isinstance(data[key], list) and data[key]:
                    rows_data = data[key]
                    break
        if not rows_data:
            return pd.DataFrame()

        def _f(val, default: float = 0.0) -> float:
            try:
                return float(str(val).replace(",", "")) if val else default
            except (ValueError, TypeError):
                return default

        records = []
        for item in rows_data:
            raw_code = str(item.get("isuSrdCd", "")).strip()
            code = raw_code.lstrip("A") if raw_code.startswith("A") else raw_code
            if not (code and len(code) == 6 and code.isdigit()):
                continue
            records.append({
                "code": code,
                "종목명": str(item.get("isuAbwdNm", "")).strip(),
                "현재가": _f(item.get("curPrc")),
                "등락률": _f(item.get("upDownRate")),
                "NXT거래량": _f(item.get("accTdQty")),
                "NXT거래대금": _f(item.get("accTrval")),
                "NXT시가": _f(item.get("oppr")),
                "NXT고가": _f(item.get("hgpr")),
                "NXT저가": _f(item.get("lwpr")),
                "NXT시간": str(item.get("nowTime", "")).strip(),
            })

        if not records:
            return pd.DataFrame()

        return pd.DataFrame(records).set_index("code").sort_values("NXT거래량", ascending=False)

    except Exception as e:
        print(f"[krx_data] NXT API 오류: {e}")
        return pd.DataFrame()
