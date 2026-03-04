import requests
from bs4 import BeautifulSoup

def test_naver_prices():
    urls = [
        "https://finance.naver.com/sise/sise_quant.naver"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for url in urls:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        
        # In Naver's table.type_2, there are rows `tr`
        rows = soup.select("table.type_2 tr")
        print(f"Total rows: {len(rows)}")
        
        count = 0
        for row in rows:
            a_tag = row.find("a", class_="tltle")
            if not a_tag: continue
            
            href = a_tag.get("href", "")
            code = href.split("code=")[-1]
            name = a_tag.text.strip()
            
            # The td cells usually contain numbers: 현재가, 전일비, 등락률, 거래량, 거래대금, 매수호가, 매도호가
            tds = row.find_all("td", class_="number")
            if len(tds) >= 5:
                # td[0] = 현재가, td[1] = 전일비, td[2] = 등락률, td[3] = 거래량, td[4] = 거래대금...
                price = tds[0].text.strip().replace(",", "")
                change_pct = tds[2].text.strip().replace("%", "").strip()
                vol = tds[3].text.strip().replace(",", "")
                val = tds[4].text.strip().replace(",", "")
                
                print(f"{code} {name}: Price={price}, Pct={change_pct}%, Vol={vol}, Val={val}")
                count += 1
            if count > 5:
                break

if __name__ == "__main__":
    test_naver_prices()
