"""krx_session.py — KRX 인증 세션 관리 및 pykrx monkey-patch.

KRX는 2026-02-27부터 API에 JSESSIONID 쿠키 인증을 요구합니다.
pykrx의 내장 Post/Get 클래스가 세션 없이 requests.post()를 직접 호출하므로,
이 모듈에서 인증된 Session을 pykrx 내부에 주입(monkey-patch)합니다.

사용법:
    import krx_session
    krx_session.ensure_pykrx_patched()   # 앱 기동 시 1회 호출
"""
from __future__ import annotations

import json
import os
import time
import requests
import streamlit as st
from datetime import datetime
import pandas as pd

# ─── Constants ───────────────────────────────────────────────────────────────
_BASE_URL = "https://data.krx.co.kr"
_COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krx_cookies.json")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ─── riemannulus의 4단계 로그인 흐름 (Issue #276 참고) ─────────────────────────

def login_krx(login_id: str, login_pw: str) -> requests.Session | None:
    """KRX data.krx.co.kr 로그인 후 세션 쿠키(JSESSIONID)를 획득합니다.

    로그인 흐름:
        1. GET MDCCOMS001.cmd  → 초기 JSESSIONID 발급
        2. GET login.jsp       → iframe 세션 초기화
        3. POST MDCCOMS001D1.cmd → 실제 로그인
        4. CD011(중복 로그인) 발생 시 skipDup=Y 파라미터로 재전송
    """
    _LOGIN_PAGE = f"{_BASE_URL}/contents/MDC/COMS/client/MDCCOMS001.cmd"
    _LOGIN_JSP  = f"{_BASE_URL}/contents/MDC/COMS/client/view/login.jsp?site=mdc"
    _LOGIN_URL  = f"{_BASE_URL}/contents/MDC/COMS/client/MDCCOMS001D1.cmd"

    session = requests.Session()
    headers = {"User-Agent": _UA}

    try:
        # 1. 초기 세션 발급
        session.get(_LOGIN_PAGE, headers=headers, timeout=15)
        # 2. iframe 세션 초기화
        session.get(_LOGIN_JSP, headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15)

        # 3. 로그인 POST
        payload = {
            "brdNo": "",
            "telNo": "",
            "di": "",
            "rectType": "",
            "mbrId": login_id,
            "passwd": login_pw,
            "skipDup": "",
            "bld": "dbms/MDC/COMS/client/MDCCOMS001D1",
        }
        login_headers = {
            "User-Agent": _UA,
            "Referer": _LOGIN_PAGE,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        r = session.post(_LOGIN_URL, data=payload, headers=login_headers, timeout=15)
        data = r.json()

        # 4. CD011 = 중복 로그인 처리
        if data.get("code") == "CD011":
            payload["skipDup"] = "Y"
            r = session.post(_LOGIN_URL, data=payload, headers=login_headers, timeout=15)
            data = r.json()

        if data.get("code") in ("CD000", "CD001"):
            # 로그인 성공
            return session
        else:
            print(f"[KRX login] 실패: {data}")
            return None

    except Exception as e:
        print(f"[KRX login] 오류: {e}")
        return None


def _build_anon_session() -> requests.Session:
    """로그인 없이 익명 세션(초기 쿠키만)을 반환합니다."""
    session = requests.Session()
    try:
        session.get(
            f"{_BASE_URL}/contents/MDC/MAIN/main/MF_MDC_NONE.cmd",
            headers={"User-Agent": _UA},
            timeout=8,
        )
    except Exception:
        pass
    return session


def build_krx_session() -> requests.Session:
    """가능한 방법으로 KRX 인증 세션을 빌드합니다.

    우선순위:
        1. krx_cookies.json 로컬 파일 (앱 UI에서 수동/자동 저장)
        2. st.secrets["krx"] 자격증명으로 Playwright 로그인
        3. 익명 세션 (fallback)
    """
    # 1. 로컬 쿠키 파일 (앱 내 UI에서 최우선으로 저장한 쿠키)
    if os.path.exists(_COOKIE_FILE):
        try:
            with open(_COOKIE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved:
                session = requests.Session()
                session.cookies.update(saved)
                print("[KRX session] 로컬 쿠키 파일 로드 완료")
                return session
        except Exception:
            pass

    # 2. Streamlit secrets로 로그인 (Playwright 사용 - NProtect 우회)
    try:
        secrets = st.secrets
        if "krx" in secrets and "user_id" in secrets["krx"] and "password" in secrets["krx"]:
            uid = secrets["krx"]["user_id"]
            pw = secrets["krx"]["password"]
            try:
                from playwright_login import login_krx_playwright
                cookie_dict = login_krx_playwright(uid, pw)
                if cookie_dict:
                    session = requests.Session()
                    session.cookies.update(cookie_dict)
                    print("[KRX session] Playwright 로그인 성공")
                    return session
            except ImportError:
                pass
            # Playwright 없으면 기존 requests 방식 시도
            session = login_krx(uid, pw)
            if session:
                print("[KRX session] requests 로그인 성공")
                return session
    except Exception:
        pass

    # 3. 익명 세션 (fallback)
    print("[KRX session] 인증 불가, 익명 세션 사용 (일부 API 제한)")
    return _build_anon_session()


# ─── pykrx Monkey-Patch ───────────────────────────────────────────────────────

_patched = False


def patch_pykrx(session: requests.Session) -> None:
    """pykrx의 내부 Post/Get 클래스가 인증된 session을 사용하도록 교체합니다.

    pykrx의 website/comm/webio.py 의 Post.read() / Get.read() 는
    requests.post()/get()을 직접 호출하여 세션 쿠키를 전달하지 못합니다.
    이 함수는 해당 메서드를 session.post()/get()으로 교체합니다.
    """
    global _patched
    if _patched:
        return

    try:
        from pykrx.website.comm import webio

        _session = session  # closure

        def _patched_post_read(self, **params):
            resp = _session.post(self.url, headers=self.headers, data=params)
            return resp

        def _patched_get_read(self, **params):
            resp = _session.get(self.url, headers=self.headers, params=params)
            return resp

        webio.Post.read = _patched_post_read
        webio.Get.read  = _patched_get_read

        _patched = True
        print("[pykrx patch] Post/Get.read() → 인증 세션으로 교체 완료")
    except Exception as e:
        print(f"[pykrx patch] 실패: {e}")


@st.cache_resource(ttl=3600)
def _get_cached_session() -> requests.Session:
    """1시간마다 갱신되는 캐시된 KRX 세션을 반환합니다."""
    return build_krx_session()


def ensure_pykrx_patched() -> None:
    """앱 기동 시 1회 호출: KRX 세션으로 pykrx를 패치합니다."""
    session = _get_cached_session()
    patch_pykrx(session)


# ─── KRX Session Manager (하위 호환용) ────────────────────────────────────────

class KRXSessionManager:
    """Manages an authenticated requests.Session for KRX data portal."""
    BASE_URL = _BASE_URL

    def __init__(self):
        self.session = _get_cached_session()
        self.headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": self.BASE_URL + "/",
            "X-Requested-With": "XMLHttpRequest",
        }

    def post(self, url, data, **kwargs):
        """Wrapper for session.post with default headers."""
        headers = kwargs.pop(
            "headers",
            {**self.headers, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        return self.session.post(url, data=data, headers=headers, **kwargs)


@st.cache_resource(ttl=3600)
def get_krx_session() -> KRXSessionManager:
    return KRXSessionManager()


# ─── KRX API 헬퍼 함수 ────────────────────────────────────────────────────────

def get_krx_market_ohlcv(date_str: str) -> pd.DataFrame:
    """특정 날짜의 전종목 OHLCV를 인증 세션으로 조회합니다."""
    session_mgr = get_krx_session()
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
        "mktId": "ALL",
        "trdDd": date_str,
    }
    try:
        r = session_mgr.post(
            session_mgr.BASE_URL + "/comm/bldAttendant/getJsonData.cmd",
            data=payload,
            timeout=15,
        )
        data = r.json()
        if "OutBlock_1" in data:
            return pd.DataFrame(data["OutBlock_1"])
    except Exception:
        pass
    return pd.DataFrame()


def get_krx_investor_data(isu_cd: str, isu_cd2: str, date_str: str) -> pd.DataFrame:
    """특정 종목의 투자자별 거래실적을 조회합니다."""
    session_mgr = get_krx_session()
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02401",
        "mktId": "ALL",
        "invstTpCd": "9999",
        "strtDd": date_str,
        "endDd": date_str,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
        "isuCd": isu_cd,
        "isuCd2": isu_cd2,
    }
    try:
        r = session_mgr.post(
            session_mgr.BASE_URL + "/comm/bldAttendant/getJsonData.cmd",
            data=payload,
            timeout=10,
        )
        data = r.json()
        if "output" in data:
            return pd.DataFrame(data["output"])
    except Exception:
        pass
    return pd.DataFrame()
