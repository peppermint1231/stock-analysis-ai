"""us_data.py — US stock data fetching layer.

미국 주식 관련 데이터 fetch/캐싱 로직을 담당합니다.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ─── Constants ────────────────────────────────────────────────────────────────
INTRADAY_INTERVALS = [
    "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)",
    "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)",
]

_YF_INTERVAL_MAP: dict[str, str] = {
    "1시간 (60 Minute)": "60m",
    "30분 (30 Minute)": "30m",
    "10분 (10 Minute)": "10m",
    "5분 (5 Minute)": "5m",
    "3분 (3 Minute)": "3m",
    "1분 (1 Minute)": "1m",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _flatten_multiindex(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        try:
            return df.xs(ticker, level=1, axis=1)
        except Exception:
            df.columns = df.columns.get_level_values(0)
    return df


def _to_kst(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and df.index.tzinfo is not None:
        df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)
    return df


def clean_currency(x) -> float:
    if isinstance(x, str):
        try:
            return float(x.split(" ")[0].replace(",", ""))
        except Exception:
            return 0.0
    return float(x) if x is not None else 0.0


def clean_volume(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        x = x.replace(",", "")
        if "M" in x:
            return float(x.replace("M", "")) * 1_000_000
        if "B" in x:
            return float(x.replace("B", "")) * 1_000_000_000
        try:
            return float(x)
        except Exception:
            return 0.0
    return 0.0


def clean_percentage(x) -> float:
    if isinstance(x, str):
        try:
            return float(x.replace("%", "").replace("+", "").replace(",", ""))
        except Exception:
            return 0.0
    return float(x) if x is not None else 0.0


# ─── Live 1-Minute Data Append ───────────────────────────────────────────────

def append_live_minute_data(df: pd.DataFrame, ticker: str, m_name: str | None = None) -> pd.DataFrame:
    """마지막 일봉에 실시간 1분봉 데이터를 추가/업데이트합니다."""
    try:
        if df.empty:
            return df
        now = datetime.now()

        yf_ticker = ticker
        if m_name == "KOSDAQ":
            yf_ticker += ".KQ"
        elif m_name in ("KOSPI", "KRX", "KR"):
            yf_ticker += ".KS"

        live_df = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
        if live_df.empty:
            return df

        if isinstance(live_df.columns, pd.MultiIndex):
            live_df.columns = live_df.columns.get_level_values(0)

        live_df = _to_kst(live_df)
        last_row = live_df.iloc[-1:]
        today_date = now.date()

        df_filtered = df[df.index.date != today_date].copy() if hasattr(df.index, "date") else df.copy()

        prev_close = df_filtered.iloc[-1]["Close"] if not df_filtered.empty else float("nan")
        new_close = float(last_row["Close"].iloc[0])
        change_val = (new_close / prev_close - 1) if prev_close else float("nan")

        new_row = {
            "Open": float(live_df["Open"].iloc[0]),
            "High": float(live_df["High"].max()),
            "Low": float(live_df["Low"].min()),
            "Close": new_close,
            "Volume": float(live_df["Volume"].sum()),
            "Change": change_val,
        }
        for c in df_filtered.columns:
            if c not in new_row:
                new_row[c] = float("nan")

        new_df = pd.DataFrame([new_row], index=[pd.to_datetime(last_row.index[0])])
        if not df_filtered.empty:
            new_df = new_df[df_filtered.columns]
        df = pd.concat([df_filtered, new_df])
    except Exception:
        pass
    return df


# ─── US Data Fetching ─────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_us_data(ticker: str, s_str: str, e_str: str, interval: str) -> pd.DataFrame:
    """Yahoo Finance에서 미국 주식 OHLCV 데이터를 반환합니다."""
    start_d = datetime.strptime(s_str, "%Y%m%d")
    end_d = datetime.strptime(e_str, "%Y%m%d")

    fetch_int = "1d"
    df = pd.DataFrame()

    if interval in ("전체 (All)", "연봉 (Yearly)", "일/주/월/연봉 종합분석"):
        df = yf.download(ticker, period="max", interval="1d", progress=False)
    elif interval in _YF_INTERVAL_MAP:
        fetch_int = _YF_INTERVAL_MAP[interval]
        df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
    else:
        df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)

    if not df.empty:
        df = _flatten_multiindex(df, ticker)
        df = _to_kst(df)
        if fetch_int == "1d":
            df = append_live_minute_data(df, ticker, "US")

    return df


# ─── US Rankings ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_us_most_active() -> pd.DataFrame:
    """Yahoo Finance Most Active Top 10을 반환합니다."""
    try:
        r = requests.get(
            "https://finance.yahoo.com/most-active",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        dfs = pd.read_html(io.StringIO(r.text))
        return dfs[0].head(10) if dfs else pd.DataFrame()
    except Exception as e:
        st.warning(f"미국 랭킹 데이터를 가져오는데 실패했습니다: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner="미국 S&P 500 종목 리스트를 불러오는 중입니다...")
def get_sp500_mapping() -> dict[str, str]:
    """Wikipedia에서 S&P 500 종목 코드→회사명 매핑을 반환합니다."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        r.raise_for_status()
        df = pd.read_html(io.StringIO(r.text))[0]
        return dict(zip(df["Symbol"], df["Security"]))
    except Exception as e:
        st.error(f"S&P 500 목록을 가져오는데 실패했습니다: {e}")
        return {}


def prepare_us_ranking_df(us_top_df: pd.DataFrame) -> pd.DataFrame:
    """Most Active DataFrame을 정제합니다 (컬럼 표준화, 숫자 변환, 52주 고가 추가)."""
    df = us_top_df.copy()

    rename_map = {"Symbol": "Symbol", "Name": "Name", "Price (Intraday)": "Price", "Volume": "Volume"}
    df = df.rename(columns=rename_map)

    pct_col = [c for c in df.columns if "%" in c]
    df = df.rename(columns={pct_col[0]: "Change_Pct"}) if pct_col else df.assign(Change_Pct=0)

    if "Price" in df.columns:
        df["Price"] = df["Price"].apply(clean_currency)
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].apply(clean_volume)
    if "Change_Pct" in df.columns:
        df["Change_Pct"] = df["Change_Pct"].apply(clean_percentage)

    df["TradingValue"] = df["Price"] * df["Volume"]

    # 52주 고가 + 당일 OHLC
    tickers_list = df["Symbol"].tolist()
    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=365)

    highs_map: dict[str, float] = {}
    opens, day_highs, day_lows, breakouts = [], [], [], []

    try:
        hist_all = yf.download(tickers_list, start=start_dt, end=end_dt, group_by="ticker", progress=False)

        for _, row in df.iterrows():
            ticker = row["Symbol"]
            curr_price = row["Price"]
            try:
                hist = (
                    hist_all[ticker]
                    if len(tickers_list) > 1 and ticker in hist_all.columns.get_level_values(0)
                    else hist_all
                )
                if not hist.empty and "High" in hist.columns:
                    prev_high = hist["High"].iloc[:-1].max() if len(hist) > 1 else 0
                    highs_map[ticker] = max(prev_high, hist["High"].iloc[-1])
                    breakouts.append(bool(prev_high > 0 and curr_price >= prev_high))
                    opens.append(hist["Open"].iloc[-1])
                    day_highs.append(hist["High"].iloc[-1])
                    day_lows.append(hist["Low"].iloc[-1])
                else:
                    raise ValueError("no high data")
            except Exception:
                highs_map[ticker] = 0
                breakouts.append(False)
                opens.append(0); day_highs.append(0); day_lows.append(0)

    except Exception as e:
        st.warning(f"52주 데이터 가져오기 실패: {e}")
        n = len(df)
        highs_map = {}
        breakouts = [False] * n
        opens = [0] * n; day_highs = [0] * n; day_lows = [0] * n

    df["52주최고"] = df["Symbol"].map(highs_map).fillna(0)
    df["is_breakout"] = breakouts
    df["시가"] = opens
    df["고가"] = day_highs
    df["저가"] = day_lows
    df.loc[df["52주최고"] == 0, "is_breakout"] = False

    return df
