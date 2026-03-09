import os
import time
import json
import requests
import pandas as pd
from datetime import datetime

# ==========================================
# KIS API Configuration
# ==========================================
APP_KEY = "PSTLmDIoSoohiGUNChhRXn3U4xeFUVFEkhZ4"
APP_SECRET = "/AYKEFWcwxjakgCy2JAALEkF9nZHiiIMjcHsr2ik4h9F42XdNQospgskZ0UY8hM/n9CssjbgCekkpZ1bU/6041NYy5nKb0UbIpTOSOWK1m7XT+cE5mk7F6n8dU9p9y3rfLORdmZ53TJQG7GexAg7e4YaF9Lwcfe/MX+nUyU6rag5YuDJn78="
DOMAIN = "https://openapi.koreainvestment.com:9443"

TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kis_token.json")

def _get_token() -> str:
    """OAuth 2.0 토큰 발급 및 캐싱 (24시간 유효)"""
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 만료 1시간 전까지만 사용
                if time.time() < data.get("expires_at", 0) - 3600:
                    return data["access_token"]
        except Exception:
            pass
            
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    url = f"{DOMAIN}/oauth2/tokenP"
    res = requests.post(url, headers=headers, json=body, timeout=10)
    res.raise_for_status()
    
    token = res.json().get("access_token")
    expires_in = res.json().get("expires_in", 86400)
    
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "access_token": token,
            "expires_at": time.time() + expires_in
        }, f)
        
    return token

def _base_headers(tr_id: str) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {_get_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P"
    }

def get_current_price(code: str) -> dict | None:
    """한국투자증권 주식현재가 시세 (REST)"""
    url = f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = _base_headers("FHKST01010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
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
                "ok": True
            }
    except Exception as e:
        print(f"[KIS] get_current_price failed: {e}")
    return None

def fetch_intraday_history(code: str, target_days: int = 5) -> pd.DataFrame:
    """당일 또는 과거 분봉 데이터 조회 (최대 target_days 수집)"""
    url = f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    headers = _base_headers("FHKST03010200")
    
    all_records = []
    # Start with today's 15:30 (장마감시간) to get backwards
    # KIS API pagination usually uses next-key from response header or passing the last time
    # Actually, KIS API provides up to 1-2 days basically, or we can just fetch multiple chunks if needed.
    # We will fetch until we collect enough data or it returns same
    last_time = "153000"
    last_date = ""
    
    for _ in range(15): # Max 15 chunks = ~450 records (~1.1 days per chunk at 380 min/day, so total maybe 5 days)
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": last_time,
            "FID_PW_DATA_INCU_YN": "Y"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            res.raise_for_status()
            data = res.json()
            if data.get("rt_cd") == "0":
                records = data.get("output2", [])
                if not records:
                    break
                
                # Check for infinite loop (same exact last fetch)
                if all_records and records[0] == all_records[-1]:
                    break

                all_records.extend(records)
                last_time = records[-1].get("stck_cntg_hour", "090000")
                if "090000" in last_time:  # reach the morning
                    last_time = "153000" # reset for previous day (KIS API handles the jump backward if YN=Y)
                time.sleep(0.1) # basic rate limit
            else:
                break
        except Exception as e:
            print(f"[KIS] fetch_intraday_history part failed: {e}")
            break
            
    if not all_records:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_records)
    # Remove duplicates
    df = df.drop_duplicates(subset=['stck_bsop_date', 'stck_cntg_hour'])
    
    df['Datetime'] = pd.to_datetime(df['stck_bsop_date'] + df['stck_cntg_hour'])
    df = df.rename(columns={
        'stck_oprc': 'Open',
        'stck_hgpr': 'High',
        'stck_lwpr': 'Low',
        'stck_prpr': 'Close',
        'cntg_vol': 'Volume'
    })
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = df[col].astype(float)
        
    df = df.set_index('Datetime').sort_index()
    # If the user queried from 153000 down to 090000 across multiple days, `FID_PW_DATA_INCU_YN: Y` natively supports it depending on the tr_id. 
    return df


def fetch_daily_history(code: str, start_date_str: str, end_date_str: str) -> pd.DataFrame:
    """일/주/월봉용 API (FHKST03010100). 1회 최대 100영업일까지 조회되므로 반복문으로 필요한 기간을 채웁니다."""
    url = f"{DOMAIN}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = _base_headers("FHKST03010100")
    
    all_records = []
    curr_end_str = end_date_str
    
    # KIS API limit is 100 per fetch. 1 year = ~250 trading days, 10 years = ~2500 requests (= 25 loops limit)
    for _ in range(50):
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_date_str,
            "FID_INPUT_DATE_2": curr_end_str,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0" # 수정주가 
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            res.raise_for_status()
            data = res.json()
            if data.get("rt_cd") == "0":
                records = data.get("output2", [])
                if not records:
                    break
                    
                # The data is returned in descending order (latest to oldest in the window)
                # or ascending depending on API. Actually usually descending.
                filtered = [r for r in records if r.get("stck_bsop_date")]
                if not filtered:
                    break
                
                # Check for infinite loop equivalent
                if all_records and filtered[0] == all_records[-1]:
                    break
                    
                all_records.extend(filtered)
                
                # Update next request's end_date
                oldest_date = min(r["stck_bsop_date"] for r in filtered)
                if oldest_date <= start_date_str:
                    break
                    
                # Substract 1 day from the oldest to avoid duplicate boundary
                oldest_dt = datetime.strptime(oldest_date, "%Y%m%d")
                curr_end_str = (oldest_dt - pd.Timedelta(days=1)).strftime("%Y%m%d")
                time.sleep(0.1)
            else:
                break
        except Exception as e:
            print(f"[KIS] fetch_daily_history pagination failed: {e}")
            break
            
    if not all_records:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_records)
    df = df.drop_duplicates(subset=['stck_bsop_date'])
    df['Date'] = pd.to_datetime(df['stck_bsop_date'])
    df = df.rename(columns={
        'stck_oprc': 'Open',
        'stck_hgpr': 'High',
        'stck_lwpr': 'Low',
        'stck_clpr': 'Close', # Note: daily uses stck_clpr
        'acml_vol': 'Volume'
    })
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = df[col].astype(float)
        
    df = df.set_index('Date').sort_index()
    # Ensure strict boundary trimming
    start_dt = pd.to_datetime(start_date_str)
    end_dt = pd.to_datetime(end_date_str)
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    return df
