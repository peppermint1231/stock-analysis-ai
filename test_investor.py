from pykrx import stock
import traceback

ticker = "005930"
fromdate = "20260220"
todate = "20260303"

print("=== 1. get_market_trading_value_by_date ===")
try:
    df = stock.get_market_trading_value_by_date(fromdate, todate, ticker)
    print(df)
except Exception as e:
    traceback.print_exc()

print("\n=== 2. get_market_trading_value_by_investor ===")
try:
    df = stock.get_market_trading_value_by_investor(fromdate, todate, ticker)
    print(df)
except Exception as e:
    traceback.print_exc()

print("\n=== 3. get_market_trading_volume_by_date ===")
try:
    df = stock.get_market_trading_volume_by_date(fromdate, todate, ticker)
    print(df)
except Exception as e:
    traceback.print_exc()

print("\n=== 4. get_market_trading_volume_by_investor ===")
try:
    df = stock.get_market_trading_volume_by_investor(fromdate, todate, ticker)
    print(df)
except Exception as e:
    traceback.print_exc()
