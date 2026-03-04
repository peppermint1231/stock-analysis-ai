"""
KRX 세션 기반 인증 크롤링 테스트 스크립트
1) 초기 페이지에서 세션쿠키 수집
2) 로그인 POST
3) getJsonData.cmd 로 시장 OHLCV 데이터 조회
"""
import requests
import json

BASE_URL = "https://data.krx.co.kr"
SESSION = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE_URL + "/",
    "X-Requested-With": "XMLHttpRequest",
}


def step1_get_initial_cookies():
    """초기 페이지 접속하여 세션 쿠키 수집"""
    print("[1] 초기 페이지 접속 중...")
    r = SESSION.get(BASE_URL + "/contents/MDC/MAIN/main/MF_MDC_NONE.cmd", headers=HEADERS, timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Cookies: {dict(SESSION.cookies)}")
    return r.status_code == 200


def step2_login(user_id: str, password: str):
    """KRX 로그인"""
    print("[2] 로그인 중...")
    
    # Logout first just in case
    SESSION.get(BASE_URL + "/comm/bldAttendant/logout.cmd", headers=HEADERS, timeout=5)
    
    # Update headers for login
    login_headers = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    
    # payload for MDCCOMS001D1.cmd
    payload = {
        "bld": "dbms/MDC/COMS/client/MDCCOMS001D1",
        "mbrId": user_id,
        "passwd": password, 
    }
    r = SESSION.post(
        BASE_URL + "/contents/MDC/COMS/client/MDCCOMS001D1.cmd",
        data=payload,
        headers=login_headers,
        timeout=10
    )
    print(f"  Status: {r.status_code}")
    try:
        data = r.json()
        print(f"  Response: {json.dumps(data, ensure_ascii=False)[:300]}")
        return data
    except Exception:
        print(f"  Response (text): {r.text[:300]}")
    return None


def step3_get_market_ohlcv(date_str: str = "20250303"):
    """getJsonData.cmd를 이용해 전종목 OHLCV 조회"""
    print("[3] 시장 OHLCV 데이터 조회 중...")
    
    # 코스피 시장 전종목 시세 (equpPblcScrgroupCd=STK = KOSPI)
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
        "mktId": "STK",   # STK=KOSPI, KSQ=KOSDAQ, KNX=KONEX
        "trdDd": date_str,
    }
    r = SESSION.post(
        BASE_URL + "/comm/fileDwldExec?name=fileDown&filetype=xls",
        data=payload,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=10
    )
    
    # Try the JSON endpoint
    r2 = SESSION.post(
        BASE_URL + "/comm/bldAttendant/getJsonData.cmd",
        data=payload,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=10
    )
    print(f"  JSON Status: {r2.status_code}")
    try:
        data = r2.json()
        keys = list(data.keys())
        print(f"  JSON keys: {keys}")
        for k in keys:
            v = data[k]
            if isinstance(v, list) and len(v) > 0:
                print(f"  '{k}' has {len(v)} rows, first row: {v[0]}")
                break
    except Exception as e:
        print(f"  Error parsing JSON: {e}")
        print(f"  Response text[:500]: {r2.text[:500]}")


def step4_get_investor_data(date_str: str = "20250303"):
    """getJsonData.cmd를 이용해 투자자별 거래실적(개별종목) 조회 - MDCSTAT02401"""
    print("[4] 투자자별 거래실적 데이터 조회 중...")
    
    # 삼성전자 (059300) 투자자별 거래실적 예시
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02401",
        "mktId": "ALL",
        "invstTpCd": "9999", # 전체
        "strtDd": date_str,
        "endDd": date_str,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
        "isuCd": "KR7005930003", # 삼성전자 표준코드?
        "isuCd2": "005930",
    }
    r = SESSION.post(
        BASE_URL + "/comm/bldAttendant/getJsonData.cmd",
        data=payload,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=10
    )
    print(f"  JSON Status: {r.status_code}")
    try:
        data = r.json()
        keys = list(data.keys())
        print(f"  JSON keys: {keys}")
        for k in keys:
            v = data[k]
            if isinstance(v, list) and len(v) > 0:
                print(f"  '{k}' has {len(v)} rows, first row: {v[0]}")
                break
    except Exception as e:
        print(f"  Error parsing JSON: {e}")
        print(f"  Response text[:500]: {r.text[:500]}")

if __name__ == "__main__":
    import os
    if os.path.exists("krx_cookies.json"):
        with open("krx_cookies.json", "r") as f:
            saved_cookies = json.load(f)
            SESSION.cookies.update(saved_cookies)
        print("[0] Loaded cookies from krx_cookies.json")
        step3_get_market_ohlcv("20250303")
        step4_get_investor_data("20250303")
    else:
        ok = step1_get_initial_cookies()
        if ok:
            step2_login("peppermint3", "qhdks12!!")
            step3_get_market_ohlcv("20250303")
