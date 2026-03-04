import sys
from datetime import datetime
from krx_data import _fetch_one_stock_ohlcv

# Test for Samsung Electronics
date_str = datetime.today().strftime("%Y-%m-%d")
print(f"Fetching for {date_str}...")
code, row = _fetch_one_stock_ohlcv("005930", date_str)
print(f"Samsung: {code}, {row}")

# Check yesterday
import datetime as dt
yesterday = (dt.datetime.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
print(f"Fetching for {yesterday}...")
code, row = _fetch_one_stock_ohlcv("005930", yesterday)
print(f"Samsung Yesterday: {code}, {row}")

import FinanceDataReader as fdr
print("Raw FDR Call yesterday:")
try:
    df = fdr.DataReader("005930", yesterday, yesterday)
    print(df)
except Exception as e:
    print("Error:", e)
