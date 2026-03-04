"""get_browser_cookies.py — Chrome DevTools Protocol로 KRX 세션 쿠키 추출.

사용법:
    python get_browser_cookies.py

사전 조건:
    - Antigravity 브라우저가 실행 중이어야 합니다 (포트 9222 CDP 활성화)
    - KRX data.krx.co.kr 에 로그인된 탭이 열려 있어야 합니다
"""
import asyncio
import json
import urllib.request
import websockets


async def main():
    # 1. 열린 페이지 목록에서 KRX 탭 찾기
    try:
        res = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5)
        pages = json.loads(res.read())
    except Exception as e:
        print(f"[오류] Chrome DevTools에 연결할 수 없습니다: {e}")
        print("Antigravity 브라우저가 실행 중인지 확인하세요.")
        return

    krx_page = next(
        (p for p in pages if "krx.co.kr" in p.get("url", "") and p.get("type") == "page"),
        None,
    )
    if not krx_page:
        print("[오류] KRX 탭을 찾을 수 없습니다. data.krx.co.kr 에 로그인된 탭을 열어두세요.")
        for p in pages:
            print(f"  - {p.get('url', '')[:80]} (type={p.get('type')})")
        return

    page_id = krx_page["id"]
    print(f"[1] KRX 탭 발견: {krx_page['url'][:60]} (id={page_id})")

    # 2. WebSocket으로 쿠키 추출
    ws_url = f"ws://127.0.0.1:9222/devtools/page/{page_id}"
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": ["https://data.krx.co.kr"]}
        }))
        response = await ws.recv()
        cookies = json.loads(response)["result"]["cookies"]

    # 3. 쿠키 저장
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    with open("krx_cookies.json", "w", encoding="utf-8") as f:
        json.dump(cookie_dict, f, ensure_ascii=False)

    print(f"[2] 쿠키 저장 완료 ({len(cookie_dict)}개): {list(cookie_dict.keys())}")
    if "JSESSIONID" in cookie_dict:
        print(f"    JSESSIONID = {cookie_dict['JSESSIONID'][:40]}...")
    else:
        print("[경고] JSESSIONID가 없습니다. 로그인 상태인지 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
