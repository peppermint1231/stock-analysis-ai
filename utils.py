"""utils.py — 기술적 지표 계산 및 OHLCV 리샘플링 유틸리티"""
from __future__ import annotations

import pandas as pd
import numpy as np


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 기술적 지표를 추가하여 반환합니다.

    추가 컬럼: SMA_5, SMA_20, SMA_60, RSI_14, MACD, BB_Upper, BB_Lower
    """
    if df is None or df.empty:
        return df

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df = df.copy()

    # 이동평균
    df["SMA_5"] = df["Close"].rolling(window=5, min_periods=1).mean()
    df["SMA_20"] = df["Close"].rolling(window=20, min_periods=1).mean()
    df["SMA_60"] = df["Close"].rolling(window=60, min_periods=1).mean()

    # RSI (14)
    delta = df["Close"].diff()
    avg_gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    avg_loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df["RSI_14"] = (100 - 100 / (1 + avg_gain / avg_loss)).bfill().fillna(50)

    # MACD
    df["MACD"] = (
        df["Close"].ewm(span=12, adjust=False).mean()
        - df["Close"].ewm(span=26, adjust=False).mean()
    ).bfill().fillna(0)

    # 볼린저 밴드 (20일, 2σ)
    std_20 = df["Close"].rolling(window=20, min_periods=1).std()
    df["BB_Upper"] = (df["SMA_20"] + std_20 * 2).bfill().fillna(df["Close"])
    df["BB_Lower"] = (df["SMA_20"] - std_20 * 2).bfill().fillna(df["Close"])

    return df


def resample_ohlcv(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """OHLCV DataFrame을 지정 주기로 리샘플링합니다.

    Args:
        period: 'D'(일), 'W'(주), 'ME'(월말), 'YE'(연말) 또는 분봉용 '60min' 등
    """
    if period == "D":
        return df.copy()

    # 구버전 pandas 별칭 대응
    period = {"M": "ME", "Y": "YE"}.get(period, period)

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    agg = {k: v for k, v in {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}.items() if k in df.columns}
    resampled = df.resample(period).agg(agg).dropna()

    # 미래 날짜 캡: 리샘플 주기 끝이 원본 마지막 날보다 이후면 원본 날짜로 교체
    is_intraday = isinstance(period, str) and any(k in period.lower() for k in ("min", "h")) and period not in ("ME", "YE")
    if not resampled.empty and not df.empty and not is_intraday:
        last_orig = df.index[-1]
        if resampled.index[-1] > last_orig:
            idx = resampled.index.tolist()
            idx[-1] = last_orig
            resampled.index = pd.DatetimeIndex(idx)

    return resampled
