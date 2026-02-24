
import pandas as pd
import requests
import io

def get_sp500_mapping():
    """Fetches S&P 500 tickers and names from Wikipedia."""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print(f"Requesting {url}...")
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        
        print("Parsing HTML...")
        dfs = pd.read_html(io.StringIO(r.text))
        df = dfs[0]
        
        print(f"Columns: {df.columns}")
        
        # Check expected columns
        if 'Symbol' not in df.columns or 'Security' not in df.columns:
             print("Mapping columns not found.")
             return {}
             
        mapping = dict(zip(df['Symbol'], df['Security']))
        return mapping
    except Exception as e:
        print(f"Error: {e}")
        return {}

m = get_sp500_mapping()
print(f"Mapped {len(m)} companies.")
if m:
    first_5 = list(m.items())[:5]
    print("Sample:", first_5)
