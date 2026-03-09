"""kis_api.py — 한국투자증권(KIS) Open API 클라이언트

OAuth 2.0 토큰 관리, 현재가 조회, 분봉/일봉 이력 데이터를 제공합니다.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# ─── KIS API 자격증명 ──────────────────────────────────────────────────────────
# 실 서비스 배포 시 환경변수 또는 st.secrets 로 관리를 권장합니다.
APP_KEY = "PSTLmDIoSoohiGUNChhRXn3U4xeFUVFEkhZ4"
APP_SECRET = "/AYKEFWcwxjakgCy2JAALEkF9nZHiiIMjcHsr2ik4h9F42XdNQospgskZ0UY8hM/n9CssjbgCekkpZ1bU/6041NYy5nKb0UbIpTOSOWK1m7XT+cE5mk7F6n8dU9p9y3rfLORdmZ53TJQG7GexAg7e4YaF9Lwcfe/MX+nUyU6rag5YuDJn78="
DOMAIN = "https://openapi.koreainvestment.com:9443"

_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kis_token.json")
_KST = timezone(timedelta(hours=9))


# ─── 인증 ──────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    """OAuth 2.0 액세스 토큰을 반환합니다. 만료 1시간 전까지 파일 캐시를 사용합니다."""
    if os.path.exists(_TOKEN_PATH):
        try:
            with open(_TOKEN_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() < data.get("expires_at", 0) - 3600:
                return data["access_token"]
        except Exception:
            pass

    res = requests.post(
        f"{DOMAIN}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
        timeout=10,
    )
    res.raise_for_status()
    body = res.json()
    token = body["access_token"]
    with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"access_token": token, "expires_at": time.time() + body.get("expires_in", 86400)}, f)
    return token


def _base_headers(tr_id: str) -> dict:
    """KIS REST API 공통 헤더를 반환합니다."""
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {_get_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }


# ─── 현재가 조회 ───────────────────────────────────────────────────────────────

def get_current_price(code: str) -> dict | None:
    """KIS 주식현재가 시세 REST API로 현재가를 조회합니다."""
    try:
        res = requests.get(
            f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=_base_headers("FHKST01010100"),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            timeout=5,
        )
        res.raise_for_status()
        data = res.json()
        if data.get("rt_cd") == "0":
            out = data.get("output", {})
            return {
                "price": float(out.get("stck_prpr", 0)),
                "diff": float(out.get("prdy_vrss", 0)),
                "rate": float(out.get("prdy_ctrt", 0)),
                "vol": float(out.get("acml_vol", 0)),
                "val": float(out.get("acml_tr_pbmn", 0)),
                "open": float(out.get("stck_oprc", 0)),
                "high": float(out.get("stck_hgpr", 0)),
                "low": float(out.get("stck_lwpr", 0)),
                "ok": True,
            }
    except Exception as e:
        print(f"[KIS] get_current_price 실패: {e}")
    return None


# ─── 분봉 이력 ─────────────────────────────────────────────────────────────────

def fetch_intraday_history(code: str, target_days: int = 5) -> pd.DataFrame:
    """당일 및 과거 분봉 데이터를 조회합니다 (최대 target_days 분량).

    KIS API는 1회 요청당 약 30개 레코드를 반환하므로 페이지네이션으로 수집합니다.
    """
    url = f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = _base_headers("FHKST03010200")

    all_records: list = []
    last_time = "153000"

    for _ in range(100):  # 최대 100회 = ~3,000개 레코드 (~8일치 1분봉)
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": last_time,
            "FID_PW_DATA_INCU_YN": "Y",
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            res.raise_for_status()
            data = res.json()
            if data.get("rt_cd") != "0":
                break
            records = data.get("output2", [])
            if not records:
                break
            if all_records and records[0] == all_records[-1]:
                break
            all_records.extend(records)
            last_time = records[-1].get("stck_cntg_hour", "090000")
            time.sleep(0.1)
        except Exception as e:
            print(f"[KIS] fetch_intraday_history 페이지네이션 실패: {e}")
            break

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records).drop_duplicates(subset=["stck_bsop_date", "stck_cntg_hour"])
    df["Datetime"] = pd.to_datetime(df["stck_bsop_date"] + df["stck_cntg_hour"])
    df = df.rename(columns={"stck_oprc": "Open", "stck_hgpr": "High", "stck_lwpr": "Low", "stck_prpr": "Close", "cntg_vol": "Volume"})
    df = df[["Datetime", "Open", "High", "Low", "Close", "Volume"]]
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = df[col].astype(float)

    df = df.set_index("Datetime").sort_index()

    # KIS API는 장중에 미래 더미 행(volume=0)을 포함하는 경우가 있으므로 현재 시각 이후 행을 제거합니다.
    kst_now = datetime.now(tz=_KST).replace(tzinfo=None)
    return df[df.index <= kst_now]


# ─── 일봉 이력 ─────────────────────────────────────────────────────────────────

def fetch_daily_history(code: str, start_date_str: str, end_date_str: str) -> pd.DataFrame:
    """일봉/주봉/월봉용 KIS API로 지정 기간의 OHLCV를 조회합니다.

    KIS API 1회 한도(100 영업일)를 초과하는 경우 페이지네이션으로 전체 기간을 수집합니다.
    """
    url = f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = _base_headers("FHKST03010100")

    all_records: list = []
    curr_end_str = end_date_str

    for _ in range(50):  # 최대 50회 = ~5,000 영업일 (약 20년치)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_date_str,
            "FID_INPUT_DATE_2": curr_end_str,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",  # 수정주가
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            res.raise_for_status()
            data = res.json()
            if data.get("rt_cd") != "0":
                break
            records = [r for r in data.get("output2", []) if r.get("stck_bsop_date")]
            if not records:
                break
            if all_records and records[0] == all_records[-1]:
                break
            all_records.extend(records)

            oldest_date = min(r["stck_bsop_date"] for r in records)
            if oldest_date <= start_date_str:
                break
            curr_end_str = (datetime.strptime(oldest_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            time.sleep(0.1)
        except Exception as e:
            print(f"[KIS] fetch_daily_history 페이지네이션 실패: {e}")
            break

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records).drop_duplicates(subset=["stck_bsop_date"])
    df["Date"] = pd.to_datetime(df["stck_bsop_date"])
    df = df.rename(columns={"stck_oprc": "Open", "stck_hgpr": "High", "stck_lwpr": "Low", "stck_clpr": "Close", "acml_vol": "Volume"})
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = df[col].astype(float)

    df = df.set_index("Date").sort_index()
    start_dt, end_dt = pd.to_datetime(start_date_str), pd.to_datetime(end_date_str)
    return df[(df.index >= start_dt) & (df.index <= end_dt)]
