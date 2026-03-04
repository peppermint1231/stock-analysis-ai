import requests
from bs4 import BeautifulSoup

def test_naver_prices():
    url = "https://finance.naver.com/sise/sise_quant.naver"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("table.type_2 tr")
    
    for row in rows:
        a_tag = row.find("a", class_="tltle")
        if not a_tag: continue
        tds = row.find_all("td", class_="number")
        print(f"Number of TDs: {len(tds)}")
        for i, td in enumerate(tds):
            print(f" TD[{i}]: {td.text.strip()}")
        break

if __name__ == "__main__":
    test_naver_prices()
