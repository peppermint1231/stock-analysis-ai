import time
from pykrx import stock

try:
    print("Testing get_market_ticker_list...")
    tickers = stock.get_market_ticker_list("20240105")
    print("Tickers count:", len(tickers))
    
    print("Testing get_market_ohlcv (single ticker)...")
    df1 = stock.get_market_ohlcv("20240102", "20240110", "005930")
    print("OHLCV length:", len(df1))
    
    print("Testing get_market_trading_volume_by_investor...")
    df2 = stock.get_market_trading_volume_by_investor("20240102", "20240110", "005930")
    print("Investor length:", len(df2))
except Exception as e:
    import traceback
    traceback.print_exc()
