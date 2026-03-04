import sys
import pandas as pd
from krx_data import get_krx_ranking

def test_ranking():
    df = get_krx_ranking()
    if not df.empty:
        print("Success! Columns:", df.columns)
        print(df.head(2)[["종목명", "종가", "현재가_live", "등락률", "고가", "저가"]])
    else:
        print("Empty DataFrame returned.")

if __name__ == "__main__":
    test_ranking()
