import pandas as pd
from datetime import datetime, timedelta
from krx_data import fetch_krx_data
from utils import resample_ohlcv, calculate_indicators

def test_intraday_resample():
    print("Fetching 1min data for 005930...")
    s_str = (datetime.today() - timedelta(days=5)).strftime("%Y%m%d")
    e_str = datetime.today().strftime("%Y%m%d")
    df_1m, _ = fetch_krx_data("005930", s_str, e_str, "1분 (1 Minute)", [])

    if df_1m.empty:
        print("No data fetched.")
        return

    print("Data shape:", df_1m.shape)
    
    print("Testing 60min resample...")
    df_60 = calculate_indicators(resample_ohlcv(df_1m, "60min"))
    print("60min shape:", df_60.shape)

    print("Testing 15min resample...")
    df_15 = calculate_indicators(resample_ohlcv(df_1m, "15min"))
    print("15min shape:", df_15.shape)

    print("Testing 5min resample...")
    df_5 = calculate_indicators(resample_ohlcv(df_1m, "5min"))
    print("5min shape:", df_5.shape)

    print("Done!")

if __name__ == "__main__":
    test_intraday_resample()
