import sys
import contextlib
import io
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup

def test_naver_scraping():
    urls = [
        "https://finance.naver.com/sise/sise_quant.naver",
        "https://finance.naver.com/sise/sise_quant.naver?sosok=1",
        "https://finance.naver.com/sise/sise_quant_high.naver",
        "https://finance.naver.com/sise/sise_quant_high.naver?sosok=1"
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    tickers = {}
    
    for url in urls:
        print(f"Fetching {url}...")
        try:
            res = requests.get(url, headers=headers, timeout=5)
            print(f"Status CODE: {res.status_code}")
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.select("table.type_2 a.tltle")
            print(f"Found {len(links)} links")
            for a in links:
                href = a.get("href", "")
                if "code=" in href:
                    code = href.split("code=")[-1]
                    name = a.text.strip()
                    if len(code) == 6 and code.isdigit():
                        tickers[code] = name
        except Exception as e:
            print(f"Error {url}: {e}")
            continue
            
    print(f"Total Naver Scraped Tickers: {len(tickers)}")
    return tickers

def test_fdr_krx():
    try:
        print("Fetching fdr.StockListing('KRX')...")
        df = fdr.StockListing("KRX")
        print(f"FDR KRX shape: {df.shape}")
        if not df.empty:
            print("Columns:", df.columns)
            print(df.head(2))
    except Exception as e:
        print("Error FDR KRX:", e)

    try:
        print("Fetching fdr.StockListing('KRX-DESC')...")
        df = fdr.StockListing("KRX-DESC")
        print(f"FDR KRX-DESC shape: {df.shape}")
        if not df.empty:
            print("Columns:", df.columns)
            print(df.head(2))
    except Exception as e:
        print("Error FDR KRX-DESC:", e)

    try:
        print("Fetching fdr.StockListing('KOSPI')...")
        df = fdr.StockListing("KOSPI")
        print(f"FDR KOSPI shape: {df.shape}")
        if not df.empty:
            print("Columns:", df.columns)
            print(df.head(2))
    except Exception as e:
        print("Error FDR KOSPI:", e)

if __name__ == "__main__":
    test_naver_scraping()
    test_fdr_krx()
