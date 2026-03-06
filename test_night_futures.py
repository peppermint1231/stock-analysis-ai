import requests
from bs4 import BeautifulSoup

def test_kospi_night_futures():
    url = "https://finance.naver.com/futures/now.naver?symbol=KSF"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    print(f"Fetching from {url}...")
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        # 현재가 탐색 시도 1: #now
        price_tag = soup.select_one("#now")
        print("price_tag (#now):", price_tag)
        
        # 현재가 탐색 시도 2: .tit_area .num
        price_tag_alt = soup.select_one(".tit_area .num")
        print("price_tag_alt (.tit_area .num):", price_tag_alt)

        # 등락률 및 기타
        diff_tag = soup.select_one("#change")
        print("diff_tag (#change):", diff_tag)
        
        pct_tag = soup.select_one("#rate")
        print("pct_tag (#rate):", pct_tag)

    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_kospi_night_futures()
