from pykrx.website.krx import get_market_ohlcv_by_ticker
try:
    df = get_market_ohlcv_by_ticker('20240105', 'KOSPI')
    print("Columns are:", df.columns.tolist())
    print("Length:", len(df))
except Exception as e:
    import traceback
    traceback.print_exc()
