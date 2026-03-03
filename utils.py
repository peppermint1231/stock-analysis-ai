import pandas as pd
import numpy as np

def calculate_indicators(df):
    """
    Calculates technical indicators using standard pandas functions.
    Expects df to have 'Close' column.
    Returns df with added columns: SMA_5, SMA_20, SMA_60, RSI_14, MACD, BB_Upper, BB_Lower.
    """
    if df is None or df.empty:
        return df
    
    # Ensure Index is Datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Make a copy to avoid SettingWithCopy warnings on the original dataframe slice if applicable
    df = df.copy()

    # 1. Moving Averages
    df['SMA_5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['SMA_20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['SMA_60'] = df['Close'].rolling(window=60, min_periods=1).mean()
    
    # 2. RSI (Relative Strength Index)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    
    rs = avg_gain / avg_loss
    df['RSI_14'] = 100 - (100 / (1 + rs))
    
    # Fill NaN caused by division by zero if any (though rare in stock prices)
    df['RSI_14'] = df['RSI_14'].fillna(50) 

    # 3. MACD
    # EMA 12
    k12 = df['Close'].ewm(span=12, adjust=False).mean()
    # EMA 26
    k26 = df['Close'].ewm(span=26, adjust=False).mean()
    
    df['MACD'] = k12 - k26
    # Signal line (often not displayed but needed for full macd, here we just return MACD line as per request or usage)
    # df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
    # 4. Bollinger Bands
    # Middle Band = 20 SMA
    # Upper Band = 20 SMA + (20 SD * 2)
    # Lower Band = 20 SMA - (20 SD * 2)
    std_20 = df['Close'].rolling(window=20, min_periods=1).std()
    
    df['BB_Upper'] = df['SMA_20'] + (std_20 * 2)
    df['BB_Lower'] = df['SMA_20'] - (std_20 * 2)
    
    # Fill any remaining NaNs (std_20 needs at least 2 periods, so first row is NaN)
    df['BB_Upper'] = df['BB_Upper'].bfill().fillna(df['Close'])
    df['BB_Lower'] = df['BB_Lower'].bfill().fillna(df['Close'])
    
    # Also bfill RSI and MACD just in case
    df['RSI_14'] = df['RSI_14'].bfill().fillna(50)
    df['MACD'] = df['MACD'].bfill().fillna(0)
        
    return df
def resample_ohlcv(df, period):
    """
    Resamples OHLCV data to a different period.
    period: 'W' (Weekly), 'M' (Monthly), 'D' (Daily - returns copy)
    """
    if period == 'D':
        return df.copy()
        
    # Map deprecated pandas resample aliases
    period_map = {'M': 'ME', 'Y': 'YE'}
    period = period_map.get(period, period)
        
    # Validation: Ensure index is Datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Resampling Logic
    # Open: first, High: max, Low: min, Close: last, Volume: sum
    # Note: Column names must match app.py (Open, High, Low, Close, Volume)
    agg_dict = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }
    
    # Handle case where some cols might be missing
    existing_agg = {k: v for k, v in agg_dict.items() if k in df.columns}
    
    resampled = df.resample(period).agg(existing_agg)
    resampled = resampled.dropna() # Remove empty periods
    
    return resampled
