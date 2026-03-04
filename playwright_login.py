"""playwright_login.py — Playwright로 KRX 자동 로그인 후 쿠키 저장.

NProtect 키보드 암호화가 적용된 KRX 로그인을 실제 브라우저 타이핑으로 우회합니다.

사용법:
    python playwright_login.py

또는 krx_session.py에서:
    from playwright_login import login_krx_playwright
    cookies = login_krx_playwright("user_id", "password")
"""
import json
import os
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

_COOKIE_FILE = Path(__file__).parent / "krx_cookies.json"


def login_krx_playwright(user_id: str, password: str, headless: bool = True) -> dict | None:
    """Playwright로 KRX 로그인 후 쿠키 dict를 반환합니다.

    CD011 (중복 로그인) 발생 시 팝업에서 확인(skipDup) 처리.
    성공 시 krx_cookies.json에 자동 저장.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = ctx.new_page()

        login_result: dict = {}

        def on_response(resp):
            if "MDCCOMS001D1.cmd" in resp.url:
                try:
                    login_result.update(resp.json())
                except Exception:
                    pass

        page.on("response", on_response)

        # 1. 초기 세션 발급 + 기존 세션 로그아웃 (CD011 예방)
        page.goto(
            "https://data.krx.co.kr/contents/MDC/MAIN/main/MF_MDC_NONE.cmd",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        page.wait_for_timeout(800)
        # 이전 세션이 있으면 로그아웃 처리 (CD011 방지)
        try:
            page.goto(
                "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS002.cmd",
                wait_until="domcontentloaded",
                timeout=8_000,
            )
            page.wait_for_timeout(500)
        except Exception:
            pass

        # 2. 로그인 페이지 이동
        page.goto(
            "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_timeout(3000)

        # 3. login.jsp iframe 탐색
        login_frame = page
        for frame in page.frames:
            if "login.jsp" in frame.url:
                login_frame = frame
                break

        # 4. ID / PW 입력
        try:
            login_frame.wait_for_selector("input[name='mbrId']", timeout=8000)
            login_frame.click("input[name='mbrId']")
            login_frame.fill("input[name='mbrId']", user_id)

            # PW: 실제 키 타이핑 (NProtect npkencrypt 우회)
            login_frame.click("input[name='pw']")
            page.wait_for_timeout(300)
            page.keyboard.type(password, delay=80)
            page.wait_for_timeout(500)
        except Exception as e:
            print(f"[playwright_login] 입력 오류: {e}")
            browser.close()
            return None

        # 5. 로그인 버튼 클릭
        for selector in ["a:has-text('로그인')", "button.btn_login", "a.btn_login", ".btn_login"]:
            try:
                login_frame.click(selector, timeout=2000)
                break
            except Exception:
                pass
        page.wait_for_timeout(4000)

        # 6. CD011 중복 로그인 → requests로 skipDup=Y 재전송
        err_code = login_result.get("_error_code", login_result.get("code", ""))
        if err_code == "CD011":
            print("[playwright_login] CD011 - requests로 skipDup=Y 재전송...")
            # Playwright 쿠키를 requests 세션에 복사
            pw_cookies = ctx.cookies()
            pw_cookie_dict = {c["name"]: c["value"] for c in pw_cookies}
            
            _sess = requests.Session()
            _sess.cookies.update(pw_cookie_dict)
            _hdrs = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd",
            }
            payload = {
                "brdNo": "", "telNo": "", "di": "", "rectType": "",
                "mbrId": user_id, "passwd": "",  # passwd는 빈 값 (이미 인증됨)
                "skipDup": "Y",
                "bld": "dbms/MDC/COMS/client/MDCCOMS001D1",
            }
            try:
                r = _sess.post(
                    "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd",
                    data=payload,
                    headers=_hdrs,
                    timeout=10,
                )
                skip_result = r.json()
                print(f"  skipDup 결과: {skip_result}")
                login_result.update(skip_result)
                # 업데이트된 쿠키 사용
                for ck in _sess.cookies:
                    ctx.add_cookies([{
                        "name": ck.name, "value": ck.value,
                        "domain": "data.krx.co.kr", "path": "/"
                    }])
            except Exception as e:
                print(f"  skipDup 오류: {e}")
        
        page.wait_for_timeout(1000)

        # 7. 결과 저장
        cookies = ctx.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        browser.close()

        final_code = login_result.get("code", login_result.get("_error_code", ""))
        if final_code in ("CD000", "CD001") or ("JSESSIONID" in cookie_dict and not login_result):
            # 유효성 검증 후 저장
            if verify_session(cookie_dict):
                print(f"[playwright_login] 로그인 성공 + 세션 검증 OK (code={final_code})")
                _COOKIE_FILE.write_text(
                    json.dumps(cookie_dict, ensure_ascii=False), encoding="utf-8"
                )
                print(f"[playwright_login] 쿠키 저장: {_COOKIE_FILE}")
                return cookie_dict
            else:
                print(f"[playwright_login] 로그인 응답은 성공이지만 세션 검증 실패")
                return None
        elif err_code == "CD011":
            # CD011 = 중복 로그인, 세션이 불완전 → 저장하지 않음
            print("[playwright_login] CD011 중복 로그인 - 세션 무효, 저장 안 함")
            print("  -> get_browser_cookies.py 로 브라우저 쿠키를 추출하세요")
            return None
        else:
            print(f"[playwright_login] 로그인 실패: {login_result}")
            return None


def verify_session(cookie_dict: dict) -> bool:
    """KRX API 호출로 쿠키 유효성을 검증합니다."""
    s = requests.Session()
    s.cookies.update(cookie_dict)
    try:
        r = s.post(
            "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={"bld": "dbms/MDC/STAT/standard/MDCSTAT01501", "mktId": "STK", "trdDd": "20260304"},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        data = r.json()
        return "OutBlock_1" in data and len(data["OutBlock_1"]) > 0
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    import streamlit as st

    try:
        uid = st.secrets["krx"]["user_id"]
        pw = st.secrets["krx"]["password"]
    except Exception:
        uid = os.environ.get("KRX_USER_ID", "peppermint3")
        pw = os.environ.get("KRX_PASSWORD", "qhdks12!!")

    print(f"KRX 로그인 중 (user={uid})...")
    cookies = login_krx_playwright(uid, pw)
    if cookies:
        valid = verify_session(cookies)
        print(f"쿠키 유효성 검증: {'OK' if valid else 'FAIL'}")
    else:
        print("로그인 실패")
        sys.exit(1)
