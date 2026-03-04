import traceback
from pykrx import stock

try:
    stock.get_market_ohlcv('20260304', market='KOSPI')
except Exception as e:
    traceback.print_exc()
