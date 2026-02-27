import streamlit as st
import yfinance as yf

import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import requests
import io
import time
from streamlit_autorefresh import st_autorefresh
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx
from streamlit_local_storage import LocalStorage

# ─────────────────────────────────────────────────────────────────────────────

import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

# Korean Standard Time (UTC+9)
_KST = timezone(timedelta(hours=9))
def now_kst(): return datetime.now(tz=_KST)
def today_kst(): return datetime.now(tz=_KST).replace(tzinfo=None)
import pandas as pd
import numpy as np
import requests
import io
import time
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx
from streamlit_local_storage import LocalStorage

# Page Configuration
st.set_page_config(layout="wide", page_title="Stock Technical Analysis")

# Initialize LocalStorage
localS = LocalStorage()

# Mobile Optimization & Custom CSS
st.markdown(
    """
    <style>
    /* Mobile Optimization */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 2rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.2rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        /* Make dataframes scrollable horizontally */
        div[data-testid="stDataFrame"] {
            overflow-x: auto;
        }
        /* Buttons span full width */
        .stButton>button {
            width: 100%;
        }
        /* Inputs span full width */
        .stSelectbox>div[data-baseweb="select"] {
            width: 100%;
        }
        .stTextInput>div[data-baseweb="input"] {
            width: 100%;
        }
        /* Hide plotly toolbars on mobile */
        .modebar-container {
            display: none !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True
)

def append_live_minute_data(df, ticker, m_name=None):
    """Fetches real-time 1m data using yfinance and appends/updates the last Daily row."""
    try:
        if df.empty: return df
        now = datetime.now()
        
        yf_ticker = ticker
        if m_name == "KOSDAQ": yf_ticker += ".KQ"
        elif m_name in ["KOSPI", "KRX", "KR"]: yf_ticker += ".KS"
        # For US, yf_ticker is just the ticker
        
        live_df = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
        if not live_df.empty:
            if isinstance(live_df.columns, pd.MultiIndex):
                live_df.columns = live_df.columns.get_level_values(0)
            
            if live_df.index.tzinfo is not None:
                live_df.index = live_df.index.tz_convert('Asia/Seoul').tz_localize(None)
                
            last_row = live_df.iloc[-1:]
            
            # Remove today's row if it exists in daily df (exact shape matching)
            today_date = now.date()
            if hasattr(df.index, 'date'):
                df_filtered = df[df.index.date != today_date].copy()
            else:
                df_filtered = df.copy()
            
            # Create a new row for the exact current time
            new_idx = pd.to_datetime(last_row.index[0])
            
            new_row_dict = {
                'Open': float(last_row['Open'].iloc[0]),
                'High': float(last_row['High'].iloc[0]),
                'Low': float(last_row['Low'].iloc[0]),
                'Close': float(last_row['Close'].iloc[0]),
                'Volume': float(live_df['Volume'].sum())
            }
            
            # Preserve existing columns
            for c in df_filtered.columns:
                if c not in new_row_dict:
                    new_row_dict[c] = float('nan')
                    
            new_df = pd.DataFrame([new_row_dict], index=[new_idx])
            # Reorder columns to match original
            new_df = new_df[df_filtered.columns] if not df_filtered.empty else new_df
            df = pd.concat([df_filtered, new_df])
    except Exception as e:
        pass
    return df

import concurrent.futures

def fetch_krx_chunked(func, start_d, end_d, code, **kwargs):
    """Fetches KRX data by chunking dates into 180-day periods and running them concurrently."""
    chunks = []
    curr = start_d
    while curr < end_d:
        next_curr = min(curr + timedelta(days=180), end_d)
        chunks.append((curr, next_curr))
        curr = next_curr + timedelta(days=1)
        
    def fetch_chunk(s, e):
        s_str = s.strftime("%Y%m%d")
        e_str = e.strftime("%Y%m%d")
        try:
            return func(s_str, e_str, code, **kwargs)
        except Exception:
            return pd.DataFrame()
            
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_chunk, s, e): (s, e) for s, e in chunks}
        results = []
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            
    if not results:
        return pd.DataFrame()
        
    # pykrx sometimes returns empty DFs with no columns or wrong index; filter them
    valid_results = [res for res in results if not res.empty]
    if not valid_results:
        return pd.DataFrame()
        
    df_chunk = pd.concat(valid_results).sort_index()
    # Remove any potential duplicates from overlapping
    df_chunk = df_chunk[~df_chunk.index.duplicated(keep='last')]
    return df_chunk



@st.cache_data(ttl=300, show_spinner=False)
def fetch_krx_data(code, s_str, e_str, interval, extra_data):
    df = pd.DataFrame()
    m_name = "KRX"
    
    start_d = datetime.strptime(s_str, "%Y%m%d")
    end_d = datetime.strptime(e_str, "%Y%m%d")

    try:
        if interval in ["1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"]:
            # Yahoo Finance Fetch
            fetch_int = "60m"
            if "30분" in interval: fetch_int = "30m"
            elif "10분" in interval: fetch_int = "10m"
            elif "5분" in interval: fetch_int = "5m"
            elif "3분" in interval: fetch_int = "3m"
            elif "1분" in interval: fetch_int = "1m"
            
            suffix = ".KS"
            try:
                import FinanceDataReader as fdr
                kosdaq_df = fdr.StockListing("KOSDAQ")
                if "Code" in kosdaq_df.columns and code in kosdaq_df["Code"].values:
                     suffix = ".KQ"
                     m_name = "KOSDAQ"
                else:
                     m_name = "KOSPI"
            except:
                pass
            
            yf_ticker = code + suffix
            # Add 1 day to end_date for yfinance to include it
            df = yf.download(yf_ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
            
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                     try:
                         df = df.xs(yf_ticker, level=1, axis=1)
                     except:
                         df.columns = df.columns.get_level_values(0)
                if df.index.tzinfo is not None:
                    df.index = df.index.tz_convert('Asia/Seoul').tz_localize(None)
        else:
            # Standard Daily/Historical Fetch handling by FinanceDataReader
            safe_e_str = datetime.today().strftime("%Y-%m-%d")
            start_fdr_str = f"{s_str[:4]}-{s_str[4:6]}-{s_str[6:]}"
            
            import FinanceDataReader as fdr
            if interval in ["일/주/월/연봉 종합분석", "연봉 (Yearly)"]:
                # Fetch Max for All View (from 1990-01-01)
                df = fdr.DataReader(code, "1990-01-01", safe_e_str)
            else:
                # Standard KRX Fetch
                df = fdr.DataReader(code, start_fdr_str, safe_e_str)
            
            # --- Additional Data Fetching ---
            # NOTE: pykrx has been replaced. FinanceDataReader does not provide daily 
            # fundamental, market cap, and investor turnover natively.
            # We skip adding these extra features for now to ensure stability.

        
        if not df.empty:
            # Rename if needed (KRX returns Korean cols)
            if '시가' in df.columns:
                rename_map = {
                    '시가': 'Open', '고가': 'High', '저가': 'Low', 
                    '종가': 'Close', '거래량': 'Volume'
                }
                df = df.rename(columns=rename_map)
                
            # Append real-time 1m data for daily and multi-timeframe analysis
            if interval in ["일/주/월/연봉 종합분석", "일봉 (Daily)"]:
                df = append_live_minute_data(df, code, m_name)
            
            # Determine Market Name
            if m_name == "KRX": # Default or not set by YF branch
                try:
                    import FinanceDataReader as fdr
                    kospi_df = fdr.StockListing("KOSPI")
                    if "Code" in kospi_df.columns and code in kospi_df["Code"].values:
                        m_name = "KOSPI"
                    else:
                        m_name = "KOSDAQ"
                except:
                    pass
                    
        return df, m_name

    except Exception as e:
        return pd.DataFrame(), "KRX"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_us_data(ticker, s_str, e_str, interval):
    start_d = datetime.strptime(s_str, "%Y%m%d")
    end_d = datetime.strptime(e_str, "%Y%m%d")
    
    df = pd.DataFrame()
    fetch_int = "1d"
    
    if interval in ["전체 (All)", "연봉 (Yearly)", "일/주/월/연봉 종합분석"]:
        # Fetch Max for All View
         df = yf.download(ticker, period="max", interval="1d", progress=False)
    
    elif interval == "1시간 (60 Minute)":
         fetch_int = "60m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)

    elif interval == "30분 (30 Minute)":
         fetch_int = "30m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)

    elif interval == "10분 (10 Minute)":
         fetch_int = "10m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
         
    elif interval == "5분 (5 Minute)":
         fetch_int = "5m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)

    elif interval == "3분 (3 Minute)":
         fetch_int = "3m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)

    elif interval == "1분 (1 Minute)":
         fetch_int = "1m"
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
    
    else:
         df = yf.download(ticker, start=start_d, end=end_d + timedelta(days=1), interval=fetch_int, progress=False)
    
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
             try:
                 df = df.xs(ticker, level=1, axis=1)
             except:
                 df.columns = df.columns.get_level_values(0)
            
        if df.index.tzinfo is not None:
            df.index = df.index.tz_convert('Asia/Seoul').tz_localize(None)
            
        # Append live 1m data for daily or multi-timeframe
        if fetch_int == "1d":
            df = append_live_minute_data(df, ticker, "US")
            
    return df

# Auto-refresh removed as per user request
# st_autorefresh(interval=60 * 1000, key="sidebar_refresh")

# Set language to Korean to prevent browser translation
st.markdown(
    """
    <script>
        var element = window.parent.document.getElementsByTagName('html')[0];
        element.setAttribute("lang", "ko");
    </script>
    """,
    unsafe_allow_html=True
)

st.title("📈 AI 주식 기술적 분석 (v2.2)")

# Sidebar / Common Inputs
# Global Market Indices in Sidebar
if st.sidebar.button("새로고침 (Refresh)"):
    st.cache_data.clear()
    # Explicitly clear session state to force re-fetch
    for key in ['krx_market_df', 'krx_time', 'us_top_df', 'us_time']:
        if key in st.session_state:
            del st.session_state[key]
    # st.rerun() # Standard rerun is sufficient

st.sidebar.markdown("---")
st.sidebar.subheader("🌍 주요 시장 지수")

@st.cache_data(ttl=1) # Cache for 1 second to force refresh
def get_major_indices_v2():
    indices = {
        "🇺🇸 S&P 500": "^GSPC",
        "🇺🇸 NASDAQ": "^IXIC", 
        "🇰🇷 KOSPI": "^KS11",
        "🇰🇷 KOSDAQ": "^KQ11",
        "💵 USD/KRW": "KRW=X"
    }
    # Ticker, Unit
    commodities = {
        "🥇 Gold": ("GC=F", "/oz"),
        "🥈 Silver": ("SI=F", "/oz"),
        "🥉 Copper": ("HG=F", "/lb"),
        "💰 Bitcoin": ("BTC-USD", ""),
        "💎 Ethereum": ("ETH-USD", "")
    }
    
    results = {"indices": {}, "commodities": {}}
    
    try:
        comm_tickers = [v[0] for v in commodities.values()]
        all_tickers = list(indices.values()) + comm_tickers
        df = yf.download(all_tickers, period="5d", progress=False)
        
        if not df.empty and 'Close' in df.columns:
            closes = df['Close']
            
            def get_data(ticker):
                series = None
                if isinstance(closes, pd.DataFrame) and ticker in closes.columns:
                    series = closes[ticker]
                elif isinstance(closes, pd.Series):
                    series = closes
                
                if series is not None:
                    if isinstance(series, pd.DataFrame):
                        series = series.iloc[:, 0]
                    series = series.dropna()
                    if len(series) >= 2:
                        val = float(series.iloc[-1])
                        diff = float(series.iloc[-1] - series.iloc[-2])
                        pct = (diff / float(series.iloc[-2])) * 100
                        return val, diff, pct
                return None

            # Indices
            for name, ticker in indices.items():
                data = get_data(ticker)
                if data:
                    results["indices"][name] = data
            
            # Commodities (calc KRW)
            krw_data = get_data("KRW=X")
            krw_rate = krw_data[0] if krw_data else 1350.0
            
            for name, (ticker, unit) in commodities.items():
                data = get_data(ticker)
                if data:
                    usd, diff, pct = data
                    krw = usd * krw_rate
                    results["commodities"][name] = (usd, diff, pct, krw, unit)
                    
    except Exception as e:
        pass
        
    return results

data = get_major_indices_v2()

if data:
    st.sidebar.caption(f"기준: {now_kst().strftime('%m/%d %H:%M')} (KST)")
    
    url_map = {
        "🇺🇸 S&P 500": "https://finance.naver.com/world/sise.naver?symbol=SPI@SPX",
        "🇺🇸 NASDAQ": "https://finance.naver.com/world/sise.naver?symbol=NAS@IXIC",
        "🇰🇷 KOSPI": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
        "🇰🇷 KOSDAQ": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
        "💵 USD/KRW": "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW",
        "🥇 Gold": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_GC",
        "🥈 Silver": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_SI",
        "🥉 Copper": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_HG",
        "💰 Bitcoin": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-BTC",
        "💎 Ethereum": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-ETH"
    }
        
    # 1. Indices
    for name, val_data in data.get("indices", {}).items():
        val, diff, pct = val_data
        
        # Add Unit
        val_fmt = f"{val:,.2f}"
        if "USD/KRW" in name:
             val_fmt += " 원"
        
        url = url_map.get(name, "#")
        st.sidebar.markdown(f"**[{name}]({url})**")
        st.sidebar.metric(" ", val_fmt, f"{diff:,.2f} ({pct:+.2f}%)", label_visibility="collapsed")
        
    st.sidebar.markdown("---")
    st.sidebar.subheader("💎 원자재 & 코인")
    
    # 2. Commodities / Crypto
    for name, val_data in data.get("commodities", {}).items():
        usd, diff, pct, krw, unit = val_data
        
        # Explicit Label Formatting
        label = f"{name} {unit}" if unit else name
        url = url_map.get(name, "#")
        st.sidebar.markdown(f"**[{label}]({url})**")
        
        # Metric with $ prefix
        st.sidebar.metric(" ", f"${usd:,.2f}", f"{pct:+.2f}%", label_visibility="collapsed")
        
        # Subtext for KRW with larger font
        st.sidebar.markdown(f"<div style='color:gray; font-size:1.1em; margin-top:-10px; margin-bottom:10px;'>약 {krw:,.0f} 원</div>", unsafe_allow_html=True)
        
else:
    st.sidebar.caption("지수 데이터 로딩 실패")

# Tabs
tab_kr, tab_us = st.tabs(["🇰🇷 국내 주식 (KRX)", "🇺🇸 해외 주식 (US)"])

from utils import calculate_indicators, resample_ohlcv
from prompts import generate_chatgpt_prompt, generate_gemini_prompt, generate_multi_timeframe_gemini_prompt, generate_multi_timeframe_chatgpt_prompt
from ai_client import get_gemini_response
from date_fragment import date_selector_fragment

@st.fragment
def render_krx_inputs_fragment(sorted_names, name_to_ticker, default_index):
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_name = None
        kr_code_input = None
        
        # Check if a pill was clicked and prepare the default values
        pill_val = st.session_state.get('kr_pill_clicked_val')
        
        if name_to_ticker:
            if "kr_select_box" not in st.session_state:
                st.session_state["kr_select_box"] = sorted_names[default_index] if sorted_names else None
            
            if pill_val and pill_val in sorted_names:
                st.session_state["kr_select_box"] = pill_val
                st.session_state['kr_pill_clicked_val'] = None
                
            st.selectbox("종목 선택 (이름으로 검색)", sorted_names, key="kr_select_box")
            selected_name = st.session_state.get("kr_select_box")
        else:
            if "kr_code_input" not in st.session_state:
                st.session_state["kr_code_input"] = pill_val if pill_val else "005930"
            elif pill_val:
                st.session_state["kr_code_input"] = pill_val
                
            if pill_val:
                st.session_state['kr_pill_clicked_val'] = None
                
            st.text_input("종목 코드 입력 (예: 005930)", key="kr_code_input")
            kr_code_input = st.session_state.get("kr_code_input")
        
        # --- Recent Searches (KRX) ---
        # Initialize from LocalStorage if not in session state
        ls_recent_kr = localS.getItem("recent_kr")
        if ls_recent_kr is not None and isinstance(ls_recent_kr, list):
            st.session_state['recent_kr'] = ls_recent_kr
        elif 'recent_kr' not in st.session_state:
            st.session_state['recent_kr'] = []
            
        def clear_kr_recent():
            st.session_state['recent_kr'] = []
            localS.setItem("recent_kr", [])
            
        if st.session_state['recent_kr']:
            st.write("최근 검색 (Recent):")
            c_rec, c_del = st.columns([0.85, 0.15])
            with c_rec:
                selected_pill = st.pills("Recent Stocks", st.session_state['recent_kr'], selection_mode="single", key="pills_kr", label_visibility="collapsed")
            with c_del:
                st.button("🗑️", on_click=clear_kr_recent, help="기록 삭제", key="btn_clear_kr")
            
            if selected_pill:
                if name_to_ticker:
                    current_sel = st.session_state.get("kr_select_box")
                    if selected_pill in sorted_names and selected_pill != current_sel:
                         st.session_state['kr_pill_clicked_val'] = selected_pill
                         st.session_state['run_krx'] = True
                         st.rerun()
                else:
                    current_code = st.session_state.get("kr_code_input")
                    if selected_pill != current_code:
                         st.session_state['kr_pill_clicked_val'] = selected_pill
                         st.rerun()

    with col2:
        st.pills("분석간격", ["일/주/월/연봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)", "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"], default="일/주/월/연봉 종합분석", selection_mode="single", key="kr_int")
        
        extra_opts = ["기본 시세 (OHLCV)", "기술적 지표 (Indicators)", "펀더멘털 (Fundamental)", "수급 (Investor)", "시가총액 (Market Cap)"]
        st.multiselect("데이터 항목 선택 (Data Selection)", extra_opts, default=extra_opts, key="kr_data_sel")
        
    # Date Logic
    interval_kr_sel = st.session_state.get("kr_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    default_start = default_end - timedelta(days=365)
    
    # We inline the date logic or call the fragment?
    # Calling fragment inside fragment: OK.
    # Note: verify date_selector_fragment uses keys. Yes it does.
    date_selector_fragment("kr", default_start, default_end, interval_kr_sel)

@st.fragment
def render_us_inputs_fragment(us_sorted_names, us_name_to_ticker, default_idx):
    col1, col2 = st.columns([2, 1])
    with col1:
        # Check if a pill was clicked and prepare the default values
        pill_val = st.session_state.get('us_pill_clicked_val')
        
        if us_name_to_ticker:
            if "us_select_box" not in st.session_state:
                st.session_state["us_select_box"] = us_sorted_names[default_idx] if us_sorted_names else None
            
            if pill_val and pill_val in us_sorted_names:
                st.session_state["us_select_box"] = pill_val
                st.session_state['us_pill_clicked_val'] = None
                
            st.selectbox("종목 선택 (S&P 500 목록)", us_sorted_names, key="us_select_box")
        else:
            if "us_ticker_input" not in st.session_state:
                st.session_state["us_ticker_input"] = pill_val if pill_val else "AAPL"
            elif pill_val:
                st.session_state["us_ticker_input"] = pill_val
                
            if pill_val:
                st.session_state['us_pill_clicked_val'] = None
                
            st.text_input("티커 입력 (예: AAPL, TSLA)", key="us_ticker_input")

        # --- Recent Searches (US) ---
        ls_recent_us = localS.getItem("recent_us")
        if ls_recent_us is not None and isinstance(ls_recent_us, list):
            st.session_state['recent_us'] = ls_recent_us
        elif 'recent_us' not in st.session_state:
            st.session_state['recent_us'] = []

        def clear_us_recent():
            st.session_state['recent_us'] = []
            localS.setItem("recent_us", [])

        if st.session_state['recent_us']:
            st.write("최근 검색 (Recent):")
            c_u_rec, c_u_del = st.columns([0.85, 0.15])
            with c_u_rec:
                selected_u_pill = st.pills("Recent US Stocks", st.session_state['recent_us'], selection_mode="single", key="pills_us", label_visibility="collapsed")
            with c_u_del:
                st.button("🗑️", on_click=clear_us_recent, help="기록 삭제", key="btn_clear_us")
            
            if selected_u_pill:
                 # Check current selection to avoid redundant updates
                 current_sel = st.session_state.get("us_select_box")
                 if us_name_to_ticker:
                     if selected_u_pill in us_sorted_names and selected_u_pill != current_sel:
                         st.session_state['us_pill_clicked_val'] = selected_u_pill
                         st.session_state['run_us'] = True
                         st.rerun()
                 else:
                     current_tick = st.session_state.get("us_ticker_input")
                     if selected_u_pill != current_tick:
                         st.session_state['us_pill_clicked_val'] = selected_u_pill
                         st.rerun()
    
    with col2:
        st.pills("데이터 간격 (Interval)", ["일/주/월/연봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)", "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"], default="일/주/월/연봉 종합분석", selection_mode="single", key="us_int")
    # Date Logic
    interval_us_sel = st.session_state.get("us_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    default_start = default_end - timedelta(days=365)
    
    date_selector_fragment("us", default_start, default_end, interval_us_sel)



def render_tradingview_widget(symbol, interval="D"):
    """Renders TradingView Widget"""
    components.html(
        f"""
        <div class="tradingview-widget-container" style="height:100%;width:100%">
          <div id="tradingview_{symbol.replace(':', '_')}" style="height:calc(100% - 32px);width:100%"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget(
          {{
            "autosize": true,
            "symbol": "{symbol}",
            "interval": "{interval}",
            "timezone": "Asia/Seoul",
            "theme": "dark",
            "style": "1",
            "locale": "kr",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_widget"
          }}
          );
          </script>
        </div>
        """,
        height=500,
    )

@st.fragment
def render_multi_ai_content(code, name, market, currency, dfs, news):
    prefix = "kr" if currency == "KRW" else "us"
    h_key = f"{prefix}_multi_{code}_holding"
    holding_status = st.pills(
        "💡 투자 자산 보유 상태 (Holding Status)", 
        ["보유(매도예정)", "미보유(매수예정)", "관망(중립)"], 
        selection_mode="single", 
        default=st.session_state.get(h_key, "관망(중립)"),
        key=h_key
    )
    if not holding_status:
        holding_status = "관망(중립)"
        
    avg_price = None
    if holding_status == "보유(매도예정)":
        step_val = 100.0 if currency == "KRW" else 1.0
        avg_price = st.number_input(
            f"현재 평단가 입력 ({currency}) - 선택사항", 
            min_value=0.0, 
            value=st.session_state.get(f"avg_price_{prefix}_multi_{code}", 0.0), 
            step=step_val,
            key=f"avg_price_{prefix}_multi_{code}",
            help="평단가를 입력하시면 AI가 평단가 대비 수익 실현/손실 최소화 전략을 상세히 분석합니다. (0 입력 시 미반영)"
        )
        
    # Extract actual date range from the Daily data (most granular)
    start_dt_str = "알 수 없음"
    end_dt_str = "알 수 없음"
    df_daily = dfs.get("Daily", pd.DataFrame())
    if not df_daily.empty:
        start_dt = df_daily.index.min()
        end_dt = df_daily.index.max()
        start_dt_str = start_dt.strftime('%Y-%m-%d %H:%M')
        end_dt_str = end_dt.strftime('%Y-%m-%d %H:%M')
            
        st.dataframe(df_daily)
        
    st.subheader("🤖 AI 종합 분석 리포트 (Multi-Timeframe)")
    
    # Check for API Key
    try:
        gemini_api_key = st.secrets["gemini"]["api_key"]
    except:
        gemini_api_key = None
        
    if gemini_api_key:
        if st.button("🤖 Gemini AI 자동 분석 시작 (Multi-Timeframe)", key=f"btn_gemini_multi_{prefix}_{code}"):
            with st.spinner("멀티 타임프레임 분석 중..."):
                prompt = generate_multi_timeframe_gemini_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
                response = get_gemini_response(prompt, gemini_api_key)
                st.markdown(response)
    else:
        st.warning("⚠️ Gemini API 키가 설정되지 않았습니다. Streamlit Cloud의 **Secrets** 메뉴에서 아래 형식으로 등록해 주세요:")
        st.code("[gemini]\napi_key = \"YOUR_GEMINI_API_KEY\"", language="toml")

    st.divider()
    st.subheader("📋 수동 종합 분석용 프롬프트 (Backup)")
    st.info("아래 코드를 복사하여 AI 서비스에 붙여넣으세요.")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        gpt_multi_p = generate_multi_timeframe_chatgpt_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
        st.code(gpt_multi_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        gem_multi_p = generate_multi_timeframe_gemini_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
        st.code(gem_multi_p, language=None)

    # ---- Quick-launch buttons: Copy prompt + Open link ----
    import json as _json
    def _copy_and_open_btn(label, text, url, bg_color):
        t_json = _json.dumps(text)
        return f"""
        <button onclick="(function(){{
            var txt = {t_json};
            if(navigator.clipboard && window.isSecureContext){{
                navigator.clipboard.writeText(txt).then(function(){{
                    window.open('{url}','_blank');
                }}).catch(function(){{window.open('{url}','_blank');}});
            }} else {{
                var ta=document.createElement('textarea');
                ta.value=txt;
                ta.style.position='fixed';ta.style.opacity='0';
                document.body.appendChild(ta);ta.focus();ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                window.open('{url}','_blank');
            }}
        }})();" style="background:{bg_color};color:white;border:none;padding:10px 0;
        width:100%;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;
        letter-spacing:0.3px;">
            {label}
        </button>"""

    st.divider()
    st.caption("🚀 버튼 클릭 한 번으로 프롬프트 복사 + AI 채팅 열기!")
    lb1, lb2, _ = st.columns([1, 1, 3])
    with lb1:
        components.html(_copy_and_open_btn("� 복사 후 ChatGPT 열기", gpt_multi_p, "https://chatgpt.com/", "#10a37f"), height=50)
    with lb2:
        components.html(_copy_and_open_btn("� 복사 후 Gemini 열기", gem_multi_p, "https://gemini.google.com/", "#1a73e8"), height=50)

@st.fragment
def render_ai_analysis_content(ticker, name, market, currency, interval_label, display_df, key_suffix):
    h_key = f"holding_{ticker}_{interval_label}_{key_suffix}"
    initial_holding_status = st.session_state.get(h_key, "관망(중립)")
    holding_status = st.pills(
        "💡 투자 자산 보유 상태 (Holding Status)", 
        ["보유(매도예정)", "미보유(매수예정)", "관망(중립)"], 
        selection_mode="single", 
        default=initial_holding_status,
        key=h_key
    )
    if not holding_status:
         holding_status = "관망(중립)"
         
    avg_price = None
    if holding_status == "보유(매도예정)":
        step_val = 100.0 if currency == "KRW" else 1.0
        avg_price = st.number_input(
            f"현재 평단가 입력 ({currency}) - 선택사항", 
            min_value=0.0, 
            value=st.session_state.get(f"avg_price_{ticker}_{interval_label}_{key_suffix}", 0.0), 
            step=step_val,
            key=f"avg_price_{ticker}_{interval_label}_{key_suffix}",
            help="평단가를 입력하시면 AI가 평단가 대비 수익 실현/손실 최소화 전략을 상세히 분석합니다. (0 입력 시 미반영)"
        )
         
    # Extract actual date range from the data
    start_dt_str = "알 수 없음"
    end_dt_str = "알 수 없음"
    if not display_df.empty:
        start_dt = display_df.index.min()
        end_dt = display_df.index.max()
        start_dt_str = start_dt.strftime('%Y-%m-%d %H:%M')
        end_dt_str = end_dt.strftime('%Y-%m-%d %H:%M')
        
    # Generate Prompts
    news_list = [] 
    
    gpt_p = generate_chatgpt_prompt(ticker, name, market, currency, interval_label, display_df, news_list, holding_status, avg_price, start_dt_str, end_dt_str)
    gem_p = generate_gemini_prompt(ticker, name, market, currency, interval_label, display_df, news_list, holding_status, avg_price, start_dt_str, end_dt_str)
    
    # --- Automated Gemini Analysis ---
    st.divider()
    st.subheader("⚡ Gemini AI 자동 분석 리포트")
    
    # Check for API Key in secrets
    try:
        gemini_api_key = st.secrets["gemini"]["api_key"]
    except:
        gemini_api_key = None
        
    if gemini_api_key:
        if st.button("🤖 Gemini AI 자동 분석 시작 (단일 타임프레임)", key=f"btn_gemini_{ticker}_{interval_label}_{key_suffix}"):
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Gemini가 시장 데이터를 심층 분석 중입니다..."):
                    try:
                        result_text = get_gemini_response(gem_p, gemini_api_key)
                        st.markdown(result_text)
                    except Exception as e:
                        st.error(f"Gemini 분석 중 오류: {e}")
    else:
        st.info("API 키가 설정되지 않아 자동 분석을 건너뜁니다.")
        
    st.divider()

    # Manual Prompts
    st.subheader("📋 수동 분석용 프롬프트 (Backup)")
    st.info("아래 코드를 복사하여 AI 서비스에 붙여넣으세요.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        st.code(gpt_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        st.code(gem_p, language=None)

def run_analysis_and_prompts(df, ticker, name, market, currency, interval_label, ranks=None, key_suffix="", selected_data=None):
    """Runs technical analysis, displays data table, and generates AI prompts"""
    if df is None or df.empty:
        st.error("데이터가 없습니다.")
        return

    # Technical Analysis
    with st.spinner("기술적 지표 계산 중..."):
        df = calculate_indicators(df)
    
    # Calculate duration
    start_dt = df.index.min()
    end_dt = df.index.max()
    days_diff = (end_dt - start_dt).days
    
    # Determine period string based on context or calculation
    if key_suffix.endswith("_d"):
        period_str = "최근 1년"
    elif key_suffix.endswith("_w"):
        period_str = "최근 10년"
    elif key_suffix.endswith("_m"):
         period_str = "상장일 - 현재 (최대)"
    elif "연봉" in interval_label or "Yearly" in interval_label:
         period_str = "상장일 - 현재 (최대)"
    elif key_suffix.endswith("_h"):
         period_str = "최근 1개월"
    elif "30분" in interval_label:
         period_str = "최근 2주"
    elif "10분" in interval_label:
         period_str = "최근 1주일"
    elif "5분" in interval_label:
         period_str = "최근 4일"
    elif "3분" in interval_label:
         period_str = "최근 2일"
    elif "1분" in interval_label:
         period_str = "최근 1일"
    else:
        period_str = f"{days_diff}일"
        if days_diff >= 28:
            months = round(days_diff / 30.44, 1)
            if months % 1 == 0:
                 period_str = f"{int(months)}개월"
            else:
                 period_str = f"{months}개월"
             
    st.success(f"{period_str}의 분석기간 ({start_dt.strftime('%Y-%m-%d')} - {end_dt.strftime('%Y-%m-%d')}), {len(df)}개 데이터 추출.")
    
    # Display Ranks if provided
    if ranks:
        r_cols = st.columns(len(ranks))
        for i, (label, val) in enumerate(ranks.items()):
            with r_cols[i]:
                st.metric(label, val)
    st.divider()
    
    # 1. Scrollable Data Table
    st.subheader(f"🔢 데이터 테이블 ({interval_label})")
    st.caption("아래 표를 스크롤하여 전체 데이터를 확인할 수 있습니다.")
    
    base_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    indicator_cols = ['SMA_20', 'SMA_60', 'RSI_14', 'MACD', 'BB_Upper', 'BB_Lower']
    
    display_cols = []
    
    # Default to all if not specified (backward compatibility)
    if selected_data is None:
        display_cols = base_cols + indicator_cols + [c for c in df.columns if c not in base_cols + indicator_cols]
    else:
        # Filter based on selection
        if "기본 시세 (OHLCV)" in selected_data:
            display_cols.extend(base_cols)
        
        if "기술적 지표 (Indicators)" in selected_data:
            display_cols.extend(indicator_cols)
            
        # Add extra columns (Fundamental, Investor, Market Cap) if they exist and logic implies they are selected via their own keys or just presence
        # Since we use 'selected_data' which comes from the multiselect that includes "Fundamental", "Investor", "Market Cap" strings
        # We can check specific known columns logic or just add "everything else" if specific keys are present?
        # Actually, simpler: The `selected_data` list contains strings.
        # But `df` already has the columns merged ONLY IF selected in the fetch phase (for Fund/Inv/Cap).
        # So we just need to ensure the fetched columns are displayed.
        # However, OHLCV and Indicators are ALWAYS in `df` (fetched/calculated).
        # So we explicitly gate them.
        # For the merged columns (Fund/Inv/Cap), they are already filtered by fetch logic, so we can just add remaining columns.
        
        known_base = base_cols + indicator_cols
        others = [c for c in df.columns if c not in known_base]
        display_cols.extend(others)

    # Filter to only existing columns
    final_cols = [c for c in display_cols if c in df.columns]
    
    display_df = df[final_cols].copy()
    

    # Sort descending by date for view (latest first)
    display_df_view = display_df.sort_index(ascending=False)

    st.dataframe(display_df_view.style.format("{:,.2f}"), height=300, use_container_width=True)

    render_ai_analysis_content(ticker, name, market, currency, interval_label, display_df, key_suffix)

    # Download Button
    csv = df.to_csv().encode('utf-8')
    st.download_button(
        label="📥 CSV 다운로드",
        data=csv,
        file_name=f'{ticker}_{interval_label}_analysis.csv',
        mime='text/csv',
        key=f"btn_down_{ticker}_{market}_{interval_label}_{key_suffix}"
    )

# --- KRX Tab ---
with tab_kr:
    st.header("🇰🇷 한국거래소 (KRX)")

    # Real-time Ranking (Volume Spikes) using pykrx
    krx_time_str = st.session_state.get('krx_time', now_kst().strftime('%m/%d %H:%M'))
    st.subheader(f"🔥 오늘의 거래량 TOP 10 ({krx_time_str})")

    # Get today's date in YYYYMMDD string
    today_str = datetime.today().strftime("%Y%m%d")

    @st.cache_data(ttl=86400, show_spinner="KRX 종목 마스터 로딩 중...")
    def get_krx_mapping():
        """Fetches all KRX tickers and names efficiently using FinanceDataReader with fallbacks."""
        import FinanceDataReader as fdr
        try:
            df = fdr.StockListing('KRX')
            if not df.empty and 'Code' in df.columns and 'Name' in df.columns:
                return dict(zip(df['Code'], df['Name']))
        except Exception:
            pass
            
        try:
            df = fdr.StockListing('KRX-DESC')
            if not df.empty and 'Code' in df.columns and 'Name' in df.columns:
                return dict(zip(df['Code'], df['Name']))
        except Exception:
            pass

        # Fallback to KOSPI & KOSDAQ directly if KRX is blocked
        try:
            df_kospi = fdr.StockListing('KOSPI')
            df_kosdaq = fdr.StockListing('KOSDAQ')
            
            combined = {}
            if not df_kospi.empty and 'Code' in df_kospi.columns:
                 combined.update(dict(zip(df_kospi['Code'], df_kospi['Name'])))
            if not df_kosdaq.empty and 'Code' in df_kosdaq.columns:
                 combined.update(dict(zip(df_kosdaq['Code'], df_kosdaq['Name'])))
                 
            if combined:
                 return combined
        except Exception:
            pass
        
        st.error("종목 목록을 가져오는데 실패했습니다 (KRX, KRX-DESC 수배 오류). 일시적인 접속장애일 수 있습니다.")
        return {}

    # Get Ticker Mapping
    ticker_to_name = get_krx_mapping()

    # Create Name -> Ticker mapping for search
    name_to_ticker = {}

    name_counts = {}
    for name in ticker_to_name.values():
        name_counts[name] = name_counts.get(name, 0) + 1

    for ticker, name in ticker_to_name.items():
        if name_counts[name] > 1:
            display_name = f"{name} ({ticker})"
        else:
            display_name = name
        name_to_ticker[display_name] = ticker

    sorted_names = sorted(name_to_ticker.keys())

    # Function to style price changes
    def format_price_change(val):
        """Formats price change with color and arrow."""
        if isinstance(val, (int, float)):
            if val > 0:
                return f'color: red'
            elif val < 0:
                return f'color: blue'
        return ''

    def add_arrow(val):
        """Adds arrow to price change value."""
        if isinstance(val, (int, float)):
            if val > 0:
                return f"▲ {val:,.2f}"
            elif val < 0:
                return f"▼ {abs(val):,.2f}"
            else:
                return f"- {val:,.2f}"
        return val

    def color_name(row):
        """Colors stock name based on fluctuation rate and highlights 52-week highs."""
        styles = [''] * len(row)
        rate_val = 0
        is_breakout = False

        if '등락률' in row.index:
            rate_val = row['등락률']

        if 'is_breakout' in row.index and row['is_breakout']:
            is_breakout = True

        # Text Color for Rate
        color = ''
        if isinstance(rate_val, (int, float)):
            if rate_val > 0:
                color = 'color: red'
            elif rate_val < 0:
                color = 'color: blue'

        # Apply Fluctuation Color to both 종목명 and 종가
        if color:
            if '종가' in row.index:
                idx_close = row.index.get_loc('종가')
                styles[idx_close] = color
            if '종목명' in row.index:
                idx = row.index.get_loc('종목명')
                styles[idx] = color

        # Highlight for Breakout (New Style: 2x Font Size for Name, Red for High Price)
        if is_breakout:
            # Highlight Name: Font Size 2x
            if '종목명' in row.index:
                idx = row.index.get_loc('종목명')
                # Append to existing color style if any
                existing = styles[idx]
                styles[idx] = f"{existing}; background-color: #FFF9C4; color: #D32F2F; font-weight: bold; border: 2px solid #FFD700"

            # Highlight 52-week high column: Red
            if '52주최고' in row.index:
                idx2 = row.index.get_loc('52주최고')
                styles[idx2] = f"color: #D32F2F; font-weight: bold;"

        return styles

    # ============================================================
    # RANKING DATA - format_dict and all shared variables defined
    # ============================================================

    # --- Shared formatting definitions (used by BOTH tables) ---
    numeric_cols = ['종가', '52주최고', '시가', '고가', '저가', '거래량', '거래대금']

    # Common helper to process top 10
    def process_top_10(df_subset, ticker_map, base_date_str):
        """Process Top 10 DataFrame: Add Name, 52-Week High, Breakout Flag."""
        df_subset = df_subset.copy()

        # Map Ticker to Name with Naver Finance Link
        # If the df already has a valid original name (from Naver scraper), use it. Otherwise fallback to ticker_map.
        names = []
        for t in df_subset.index:
            if '종목명' in df_subset.columns and pd.notna(df_subset.loc[t, '종목명']):
                 names.append(df_subset.loc[t, '종목명'])
            else:
                 names.append(ticker_map.get(t, t))

        df_subset['종목명'] = [f"https://finance.naver.com/item/fchart.naver?code={t}&name={n}" for t, n in zip(df_subset.index, names)]

        high_prices = []
        breakouts = []

        start_date_52 = datetime.strptime(base_date_str, "%Y%m%d") - timedelta(days=365)
        start_str_52 = start_date_52.strftime("%Y-%m-%d")

        import FinanceDataReader as fdr
        for ticker in df_subset.index:
            try:
                curr_close = df_subset.loc[ticker, '종가']
                # Get 1 year history
                df_high = fdr.DataReader(ticker, start_str_52, base_date_str)

                if not df_high.empty and 'High' in df_high.columns:
                    display_high = df_high['High'].max()
                    high_prices.append(display_high)

                    if len(df_high) > 1:
                        prev_high = df_high['High'].iloc[:-1].max()
                    else:
                        prev_high = 0

                    if prev_high > 0 and curr_close >= prev_high:
                         breakouts.append(True)
                    else:
                         breakouts.append(False)
                else:
                    high_prices.append(0)
                    breakouts.append(False)
            except:
                high_prices.append(0)
                breakouts.append(False)

        df_subset['52주최고'] = high_prices
        df_subset['is_breakout'] = breakouts
        return df_subset

    @st.cache_data(ttl=60)
    def get_naver_ranking(type="quant"):
        # type="quant" (Volume), type="amount" (Value)
        url = f'https://finance.naver.com/sise/sise_{type}.naver'
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            import requests
            import io
            from bs4 import BeautifulSoup
            r = requests.get(url, headers=headers)
            
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.select('a.tltle')
            ticker_map = {a.text: a['href'].split('code=')[-1] for a in links}
            
            dfs = pd.read_html(io.StringIO(r.text), encoding='euc-kr')
            df = dfs[1].dropna(how='all').head(10)
            
            # Map columns cleanly
            if type == "quant":
                 df = df[['N', '종목명', '현재가', '전일비', '등락률', '거래량', '거래대금', '매수호가', '매도호가', '시가총액', 'PER', 'ROE']]
            else:
                 df = df[['N', '종목명', '현재가', '전일비', '등락률', '거래대금', '거래량', '매수호가', '매도호가', '시가총액', 'PER', 'ROE']]
            
            df['Ticker'] = df['종목명'].map(ticker_map)
            
            # Convert to numeric
            for col in ['현재가', '거래량', '거래대금']:
                if col in df.columns:
                     df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
            
            if '등락률' in df.columns:
                df['등락률'] = pd.to_numeric(df['등락률'].astype(str).str.replace('%', '').str.replace('+', ''), errors='coerce')
                
            return df
        except Exception as e:
            return pd.DataFrame()

    try:
        check_date = today_kst()
        recent_valid_d_str = check_date.strftime("%Y%m%d")
        today_str = recent_valid_d_str
        krx_time_str = now_kst().strftime('%m/%d %H:%M')

        display_cols = ['종목명', '종가', '시가', '고가', '저가', '52주최고', '등락률', '거래량', '거래대금', 'is_breakout']
        numeric_cols = ['종가', '시가', '고가', '저가', '거래량', '거래대금', '52주최고']

        column_config = {
            "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]+)", help="클릭 시 네이버페이 증권 차트로 이동합니다. 배경색 있는 종목은 52주 신고가(Highlighted: 52-Week High)", max_chars=100),
            "등락률": st.column_config.TextColumn("등락률"),
            "is_breakout": st.column_config.CheckboxColumn("전고점 돌파", default=False)
        }

        @st.fragment
        def render_krx_ranking(today_str, krx_time_str, name_to_ticker_map, numeric_cols, display_cols):
            with st.spinner("네이버 증권에서 오늘의 실시간 랭킹을 가져오는 중..."):
                top_10 = get_naver_ranking("quant")
            
            if not top_10.empty:
                # Tickers are now directly in the dataframe from Naver web scraping
                top_10 = top_10.dropna(subset=['Ticker'])
                top_10 = top_10.dropna(subset=['Ticker'])
                if not top_10.empty:
                    top_10 = top_10.set_index('Ticker')
                    top_10 = process_top_10(top_10, ticker_to_name, today_str)

                    top_10_disp = top_10.copy()
                    for col in numeric_cols:
                        if col in top_10_disp.columns:
                            top_10_disp[col] = top_10_disp[col].apply(lambda x: f'{x:,.0f}')

                    avail_cols = [c for c in display_cols if c in top_10_disp.columns]
                    styler = top_10_disp[avail_cols].style

                    if '등락률' in avail_cols:
                         styler = styler.format({'등락률': add_arrow})
                         styler = styler.map(format_price_change, subset=['등락률'])

                    styler = styler.apply(color_name, axis=1)
                    st.dataframe(styler, column_config=column_config)

                # --- Top 10 Trading Value (거래대금) ---
                st.subheader(f"💰 오늘의 거래대금 TOP 10 ({krx_time_str})")
                
                with st.spinner("네이버 증권에서 오늘의 실시간 랭킹을 가져오는 중..."):
                    top_10_val = get_naver_ranking("amount")

                if not top_10_val.empty:
                    top_10_val = top_10_val.dropna(subset=['Ticker'])
                    top_10_val = top_10_val.dropna(subset=['Ticker'])
                    
                    if not top_10_val.empty:
                        top_10_val = top_10_val.set_index('Ticker')
                        top_10_val = process_top_10(top_10_val, ticker_to_name, today_str)

                        top_10_val_disp = top_10_val.copy()
                        for col in numeric_cols:
                            if col in top_10_val_disp.columns:
                                top_10_val_disp[col] = top_10_val_disp[col].apply(lambda x: f'{x:,.0f}')

                        avail_cols_val = [c for c in display_cols if c in top_10_val_disp.columns]
                        styler_val = top_10_val_disp[avail_cols_val].style

                        if '등락률' in avail_cols_val:
                             styler_val = styler_val.format({'등락률': add_arrow})
                             styler_val = styler_val.map(format_price_change, subset=['등락률'])

                        styler_val = styler_val.apply(color_name, axis=1)
                        st.dataframe(styler_val, column_config=column_config)
                else:
                    st.warning("'거래대금' 데이터를 가져올 수 없습니다.")
            else:
                st.info("장 시작 전이거나 휴장일입니다. (No Data for Ranking)")

        render_krx_ranking(today_str, krx_time_str, name_to_ticker, numeric_cols, display_cols)
    except Exception as e:
        import traceback
        st.warning(f"랭킹 데이터를 가져오는데 실패했습니다: {e}\n\n```python\n{traceback.format_exc()}\n```")    # Input (Selectbox)
    st.write("---")
    st.subheader("📊 개별 종목 분석")

    # Removed st.form to allow reactivity for Manual Date Checkbox

    # Calculate Default Index for Samsung Electronics (or similar)
    default_index = 0
    if name_to_ticker:
        samsung_exact = [k for k in sorted_names if k == "삼성전자"]
        if samsung_exact:
             default_index = sorted_names.index(samsung_exact[0])
        else:
             samsung_partial = [k for k in sorted_names if "삼성전자" in k]
             if samsung_partial:
                 default_index = sorted_names.index(samsung_partial[0])

    render_krx_inputs_fragment(sorted_names, name_to_ticker, default_index)

    # Retrieve Values from Session State
    start_date_kr = st.session_state.get("kr_start", datetime.today() - timedelta(days=365))
    end_date_kr = st.session_state.get("kr_end", datetime.today())
    interval_kr_sel = st.session_state.get("kr_int", "일/주/월/연봉 종합분석")
    default_opts = ["기본 시세 (OHLCV)", "기술적 지표 (Indicators)", "펀더멘털 (Fundamental)", "수급 (Investor)", "시가총액 (Market Cap)"]
    extra_data_sel = st.session_state.get("kr_data_sel", default_opts)

    if st.button("🚀 분석 실행 (KRX Analysis)", type="primary", use_container_width=True):
        st.session_state['run_krx'] = True

        # Retrieve inputs for Recent Logic
        if name_to_ticker:
            selected_name_val = st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else None)
        else:
            kr_code_input_val = st.session_state.get("kr_code_input", "005930")

        # Add to Recent
        if name_to_ticker and selected_name_val:
             if selected_name_val not in st.session_state['recent_kr']:
                 st.session_state['recent_kr'].insert(0, selected_name_val)
             else:
                 st.session_state['recent_kr'].remove(selected_name_val)
                 st.session_state['recent_kr'].insert(0, selected_name_val)
        elif not name_to_ticker:
             if kr_code_input_val not in st.session_state['recent_kr']:
                 st.session_state['recent_kr'].insert(0, kr_code_input_val)
             else:
                 st.session_state['recent_kr'].remove(kr_code_input_val)
                 st.session_state['recent_kr'].insert(0, kr_code_input_val)

        # Keep max 10
        if len(st.session_state['recent_kr']) > 10:
            st.session_state['recent_kr'] = st.session_state['recent_kr'][:10]
            
        # Save to LocalStorage
        localS.setItem('recent_kr', st.session_state['recent_kr'])

    if st.session_state.get('run_krx'):
        if name_to_ticker:
            # Re-retrieve in case run_krx is True but button wasn't just pressed (persistence)
            selected_name_val = st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else "")
            kr_code = name_to_ticker.get(selected_name_val)
            selected_name = selected_name_val # Ensure selected_name var exists for downstream
        else:
            kr_code = st.session_state.get("kr_code_input", "005930")
            selected_name = kr_code

        # Render TradingView Chart immediately before fetching data
        render_tradingview_widget(f"KRX:{kr_code}")

        with st.spinner('KRX 데이터 가져오는 중...'):
            start_load_time = time.time()

            # Use Local Date
            if interval_kr_sel == "1시간 (60 Minute)":
                 if (end_date_kr - start_date_kr).days > 30:
                     st.warning("1시간 봉은 최대 1개월(30일) 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=29)
            elif interval_kr_sel == "30분 (30 Minute)":
                 if (end_date_kr - start_date_kr).days > 14:
                     st.warning("30분 봉은 최대 2주(14일) 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=13)
            elif interval_kr_sel == "10분 (10 Minute)":
                 if (end_date_kr - start_date_kr).days > 7:
                     st.warning("10분 봉은 최대 1주(7일) 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=6)
            elif interval_kr_sel == "5분 (5 Minute)":
                 if (end_date_kr - start_date_kr).days > 4:
                     st.warning("5분 봉은 최대 4일 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=3)
            elif interval_kr_sel == "3분 (3 Minute)":
                 if (end_date_kr - start_date_kr).days > 2:
                     st.warning("3분 봉은 최대 2일 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=1)
            elif interval_kr_sel == "1분 (1 Minute)":
                 if (end_date_kr - start_date_kr).days > 1:
                     st.warning("1분 봉은 최대 1일 데이터만 제공됩니다. 기간을 자동 조정합니다.")
                     start_date_kr = end_date_kr - timedelta(days=0)

            start_str = start_date_kr.strftime("%Y%m%d")
            end_str = end_date_kr.strftime("%Y%m%d")

            # Call the cached function with string dates
            df_kr, market_name = fetch_krx_data(kr_code, start_str, end_str, interval_kr_sel, extra_data_sel)

            # Calculate Ranks
            ranks = None
            try:
                mt_df = st.session_state.get('krx_market_df', pd.DataFrame())
                if not mt_df.empty and kr_code in mt_df.index:
                    vol_rank = mt_df['거래량'].rank(ascending=False)[kr_code]
                    val_rank = mt_df['거래대금'].rank(ascending=False)[kr_code]
                    ranks = {
                        "📊 거래량 순위": f"{int(vol_rank)}위",
                        "💰 거래대금 순위": f"{int(val_rank)}위"
                    }
            except:
                pass

            try:
                if not df_kr.empty:
                    elapsed = time.time() - start_load_time
                    if interval_kr_sel == "일/주/월/연봉 종합분석":
                        st.success(f"'{selected_name}' 전체 구간(일/주/월/년) 입체 분석 (⏱️ 소요 시간: {elapsed:.2f}초)")

                        @st.cache_data(ttl=3600, show_spinner="멀티 타임프레임 데이터 준비 중...")
                        def get_multi_timeframe_data_kr(code, df_daily_source):
                            # Daily (Last 1 Year)
                            d_cutoff = df_daily_source.index.max() - timedelta(days=365)
                            df_d = df_daily_source.loc[d_cutoff:].sort_index()
                            df_d = calculate_indicators(df_d)

                            # Weekly (Last 10 Years)
                            w_cutoff = df_daily_source.index.max() - timedelta(days=3650)
                            df_w_all = resample_ohlcv(df_daily_source, "W")
                            df_w = df_w_all.loc[w_cutoff:]
                            df_w = calculate_indicators(df_w)

                            # Monthly (Max)
                            df_m = resample_ohlcv(df_daily_source, "M")
                            df_m = calculate_indicators(df_m)

                            # Yearly (Max)
                            df_y = resample_ohlcv(df_daily_source, "Y")
                            df_y = calculate_indicators(df_y)

                            return df_d, df_w, df_m, df_y

                        # Use the cached function
                        df_d, df_w, df_m, df_y = get_multi_timeframe_data_kr(kr_code, df_kr)

                        timeframe_dfs = {
                            "Daily": df_d,
                            "Weekly": df_w,
                            "Monthly": df_m,
                            "Yearly": df_y
                        }
                        
                        # Display Tabs
                        t1, t2, t3, t4, t5 = st.tabs(["📊 종합 리포트", "📅 일봉", "📅 주봉", "📅 월봉", "📅 연봉"])

                        with t1:
                            news_list = []
                            render_multi_ai_content(kr_code, selected_name, market_name, "KRW", timeframe_dfs, news_list)

                        with t2:
                             st.dataframe(df_d)
                             run_analysis_and_prompts(df_d, kr_code, selected_name, market_name, "KRW", "일봉", ranks, key_suffix="kr_d", selected_data=extra_data_sel)
                        with t3:
                            st.dataframe(df_w)
                            run_analysis_and_prompts(df_w, kr_code, selected_name, market_name, "KRW", "주봉", ranks, key_suffix="kr_w", selected_data=extra_data_sel)
                        with t4:
                            st.dataframe(df_m)
                            run_analysis_and_prompts(df_m, kr_code, selected_name, market_name, "KRW", "월봉", ranks, key_suffix="kr_m", selected_data=extra_data_sel)
                        with t5:
                            st.dataframe(df_y)
                            run_analysis_and_prompts(df_y, kr_code, selected_name, market_name, "KRW", "연봉", ranks, key_suffix="kr_y", selected_data=extra_data_sel)

                    else:
                        if interval_kr_sel in ["1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"]:
                            df_final = df_kr.sort_index()
                        else:
                            int_map = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "M", "연봉 (Yearly)": "Y"}
                            period_code = int_map[interval_kr_sel]

                            if period_code == "D":
                                df_final = df_kr.sort_index()
                            else:
                                df_final = resample_ohlcv(df_kr, period_code)
                                
                        # Apply indicators for single timeframes
                        df_final = calculate_indicators(df_final)

                        elapsed = time.time() - start_load_time
                        st.success(f"'{selected_name}' {interval_kr_sel} 분석 (⏱️ 소요 시간: {elapsed:.2f}초)")
                        
                        st.dataframe(df_final)
                        run_analysis_and_prompts(df_final, kr_code, selected_name, market_name, "KRW", interval_kr_sel, ranks, key_suffix="kr_single", selected_data=extra_data_sel)

                else:
                    st.error("데이터가 없습니다. 종목 코드를 확인해주세요.")
            except Exception as e:
                import traceback
                st.error(f"오류 발생: {e}\n{traceback.format_exc()}")



# --- US Tab ---
with tab_us:
    st.header("🇺🇸 미국 주식 (US Stock)")

    # --- US Ranking (Most Active) ---
    # --- US Ranking (Most Active) ---
    # Manual Refresh Header
    us_time_str = st.session_state.get('us_time', now_kst().strftime('%m/%d %H:%M'))
    st.subheader(f"🔥 거래량 상위 Top 10 (Most Active) ({us_time_str})")

    @st.cache_data(ttl=60)
    def get_us_most_active():
        try:
            url = 'https://finance.yahoo.com/most-active'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            r = requests.get(url, headers=headers)
            dfs = pd.read_html(io.StringIO(r.text))

            if dfs:
                return dfs[0].head(10)
            return pd.DataFrame()
        except Exception as e:
            st.warning(f"랭킹 데이터를 가져오는데 실패했습니다: {e}")
            return pd.DataFrame()

    if 'us_top_df' not in st.session_state:
         with st.spinner("미국 Top 10 데이터를 가져오는 중..."):
             us_top = get_us_most_active()
             st.session_state['us_top_df'] = us_top
             st.session_state['us_time'] = now_kst().strftime('%m/%d %H:%M')

    us_top_df = st.session_state.get('us_top_df', pd.DataFrame())

    if not us_top_df.empty:
        with st.spinner("미국 주식 데이터 분석 중... (52주 신고가 확인)"):
            try:
                # 1. Standardize Columns
                us_top_df = us_top_df.copy()

                # Mapping known columns
                rename_map = {
                    'Symbol': 'Symbol',
                    'Name': 'Name',
                    'Price (Intraday)': 'Price',
                    'Volume': 'Volume'
                }
                us_top_df = us_top_df.rename(columns=rename_map)

                # Handle % Change separately (variable name)
                pct_col = [c for c in us_top_df.columns if '%' in c]
                if pct_col:
                    us_top_df = us_top_df.rename(columns={pct_col[0]: 'Change_Pct'})
                else:
                    us_top_df['Change_Pct'] = 0

                # 2. Data Cleaning (String -> Numeric)
                def clean_currency(x):
                    if isinstance(x, str):
                        val_str = x.split(' ')[0].replace(',', '')
                        try:
                            return float(val_str)
                        except:
                            return 0.0
                    return float(x)

                def clean_volume(x):
                    if isinstance(x, (int, float)):
                        return float(x)
                    if isinstance(x, str):
                        x = x.replace(',', '')
                        if 'M' in x:
                            return float(x.replace('M', '')) * 1_000_000
                        if 'B' in x:
                            return float(x.replace('B', '')) * 1_000_000
                        return float(x)
                    return 0.0

                if 'Price' in us_top_df.columns:
                    us_top_df['Price'] = us_top_df['Price'].apply(clean_currency)

                if 'Volume' in us_top_df.columns:
                    us_top_df['Volume'] = us_top_df['Volume'].apply(clean_volume)

                def clean_percentage(x):
                    if isinstance(x, str):
                        x = x.replace('%', '').replace('+', '').replace(',', '')
                        try:
                            return float(x)
                        except:
                            return 0.0
                    return x

                if 'Change_Pct' in us_top_df.columns:
                    us_top_df['Change_Pct'] = us_top_df['Change_Pct'].apply(clean_percentage)

                # 3. Calculate Trading Value (Estimated)
                us_top_df['TradingValue'] = us_top_df['Price'] * us_top_df['Volume']

                # 4. Fetch 52-Week Highs (Batch)
                tickers_list = us_top_df['Symbol'].tolist()

                end_dt = datetime.today()
                start_dt = end_dt - timedelta(days=365)

                highs_map = {}
                opens = []
                day_highs = []
                day_lows = []
                breakouts = []

                try:
                    data_us_hist = yf.download(tickers_list, start=start_dt, end=end_dt, group_by='ticker', progress=False)

                    for index, row in us_top_df.iterrows():
                        ticker = row['Symbol']
                        try:
                            curr_price = row['Price']

                            # Get Hist
                            if len(tickers_list) > 1:
                                hist = data_us_hist[ticker] if ticker in data_us_hist.columns.get_level_values(0) else pd.DataFrame()
                            else:
                                hist = data_us_hist

                            if not hist.empty and 'High' in hist.columns:
                                # Exclude today's data (last row) to calculate PREVIOUS 52-week high
                                if len(hist) > 1:
                                    prev_high = hist['High'].iloc[:-1].max()
                                else:
                                    prev_high = 0

                                # Breakout Logic: If Current Price >= Previous 52W High
                                is_bk = (curr_price >= prev_high) and (prev_high > 0)
                                breakouts.append(is_bk)

                                # Display High
                                current_day_high = hist['High'].iloc[-1]
                                highs_map[ticker] = max(prev_high, current_day_high)

                                # Get OHLC from the latest available row for display
                                opens.append(hist['Open'].iloc[-1])
                                day_highs.append(hist['High'].iloc[-1])
                                day_lows.append(hist['Low'].iloc[-1])
                            else:
                                highs_map[ticker] = 0
                                breakouts.append(False)
                                opens.append(0); day_highs.append(0); day_lows.append(0)
                        except:
                            highs_map[ticker] = 0
                            breakouts.append(False)
                            opens.append(0); day_highs.append(0); day_lows.append(0)

                except Exception as e:
                    st.warning(f"52주 데이터 가져오기 실패: {e}")
                    # Fill lists with 0 if failure
                    count = len(us_top_df) # Use length of dataframe
                    if not opens:
                        opens = [0]*count; day_highs = [0]*count; day_lows = [0]*count
                        breakouts = [False]*count

                # 5. Apply Values
                us_top_df['52주최고'] = us_top_df['Symbol'].map(highs_map).fillna(0)
                us_top_df['is_breakout'] = breakouts # Use the list directly
                us_top_df['시가'] = opens
                us_top_df['고가'] = day_highs
                us_top_df['저가'] = day_lows

                # us_top_df['is_breakout'] is already set correctly above
                us_top_df.loc[us_top_df['52주최고'] == 0, 'is_breakout'] = False

                # Debug code removed

                # 6. Display Functions
                def display_us_ranking(df_sub, key_suffix):
                    # Format with Naver World Stock Mobile Link
                    df_disp = pd.DataFrame()
                    # Append name parameter for display text parsing
                    df_disp['종목명'] = [f"https://m.stock.naver.com/worldstock/stock/{t}/total?name={n} ({t})" for t, n in zip(df_sub['Symbol'], df_sub['Name'])]
                    df_disp['종가'] = df_sub['Price']
                    df_disp['시가'] = df_sub['시가']
                    df_disp['고가'] = df_sub['고가']
                    df_disp['저가'] = df_sub['저가']
                    df_disp['52주최고'] = df_sub['52주최고']
                    df_disp['등락률'] = df_sub['Change_Pct']
                    df_disp['거래량'] = df_sub['Volume']
                    df_disp['거래대금'] = df_sub['TradingValue']
                    df_disp['is_breakout'] = df_sub['is_breakout']

                    # Numeric Formatting
                    for c in ['시가', '고가', '저가', '종가', '52주최고']:
                        df_disp[c] = df_disp[c].apply(lambda x: f"{x:,.2f}")

                    for c in ['거래량', '거래대금']:
                         df_disp[c] = df_disp[c].apply(lambda x: f"{x:,.0f}")

                    # Styled
                    styler = df_disp.style

                    # Apply Arrows & Colors (Using global functions)
                    if '등락률' in df_disp.columns:
                        styler = styler.format({'등락률': add_arrow})
                        styler = styler.map(format_price_change, subset=['등락률'])

                    styler = styler.apply(color_name, axis=1)
                    # styler = styler.hide(subset=['is_breakout'], axis="columns")

                    use_usd_candle = st.toggle("📊 가로 캔들 차트로 보기", key=f"toggle_us_{key_suffix}")
                    if use_usd_candle:
                        df_numeric = pd.DataFrame(index=df_sub['Symbol'])
                        df_numeric['종가'] = df_sub['Price'].values
                        df_numeric['시가'] = df_sub['시가'].values
                        df_numeric['고가'] = df_sub['고가'].values
                        df_numeric['저가'] = df_sub['저가'].values
                        df_numeric['등락률'] = df_sub['Change_Pct'].values
                        max_scale = max(10.0, float(df_numeric['등락률'].abs().max() * 1.2))
                        t_map = {t: n for t, n in zip(df_sub['Symbol'], df_sub['Name'])}
                        html_us = render_horizontal_candles(df_numeric, t_map, max_pct=max_scale)
                        components.html(html_us, height=900, scrolling=True)
                    else:
                        st.dataframe(styler, column_config={
                            "종목명": st.column_config.LinkColumn("종목명 (Name)", display_text=r"name=([^&]+)", help="클릭 시 네이버페이 증권(모바일)으로 이동합니다."),
                            "시가": st.column_config.TextColumn("시가 (Open)"),
                            "고가": st.column_config.TextColumn("고가 (High)"),
                            "저가": st.column_config.TextColumn("저가 (Low)"),
                            "종가": st.column_config.TextColumn("현재가 (Price)"),
                            "52주최고": st.column_config.TextColumn("52주 최고 (High)"),
                            "등락률": st.column_config.TextColumn("등락률 (Change)"),
                            "거래량": st.column_config.TextColumn("거래량 (Vol)"),
                            "거래대금": st.column_config.TextColumn("거래대금 (Val)"),
                            "is_breakout": st.column_config.CheckboxColumn("전고점 돌파", default=False)
                        }, hide_index=True)

                # --- Volume Ranking ---
                display_us_ranking(us_top_df.head(10), "vol")

                # --- Value Ranking ---
                st.subheader(f"💰 거래대금 상위 Top 10 (Trading Value) ({us_time_str})")
                us_val_df = us_top_df.sort_values(by='TradingValue', ascending=False).head(10)
                display_us_ranking(us_val_df, "val")

            except Exception as e:
                st.error(f"데이터 처리 중 오류: {e}")
    else:
        st.info("랭킹 데이터를 불러올 수 없습니다.")

    st.write("---")

    @st.cache_data(show_spinner="미국 S&P 500 종목 리스트를 불러오는 중입니다...")
    def get_sp500_mapping():
        """Fetches S&P 500 tickers and names from Wikipedia."""
        try:
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            r = requests.get(url, headers=headers)
            r.raise_for_status()

            dfs = pd.read_html(io.StringIO(r.text))
            df = dfs[0]

            mapping = dict(zip(df['Symbol'], df['Security']))
            return mapping
        except Exception as e:
            st.error(f"S&P 500 목록을 가져오는데 실패했습니다: {e}")
            return {}

    us_ticker_map = get_sp500_mapping()

    us_name_to_ticker = {f"{name} ({ticker})": ticker for ticker, name in us_ticker_map.items()}
    us_sorted_names = sorted(us_name_to_ticker.keys())

    # Removed st.form for US Tab

    # Calculate Default Index for "Apple"
    default_idx = 0
    if us_name_to_ticker:
        apple_match = [k for k in us_sorted_names if "Apple" in k]
        if apple_match:
             default_idx = us_sorted_names.index(apple_match[0])

    render_us_inputs_fragment(us_sorted_names, us_name_to_ticker, default_idx)

    # Retrieve Values from Session State
    start_date_us = st.session_state.get("us_start", datetime.today() - timedelta(days=365))
    end_date_us = st.session_state.get("us_end", datetime.today())
    interval_us_sel = st.session_state.get("us_int", "전체 (All)")
    if st.button("🚀 분석 실행 (US Analysis)", type="primary", use_container_width=True):
        st.session_state['run_us'] = True

        # Retrieve inputs for Recent Logic
        if us_name_to_ticker:
            selected_us_name_val = st.session_state.get("us_select_box", us_sorted_names[default_idx] if us_sorted_names else None)
        else:
            us_ticker_input_val = st.session_state.get("us_ticker_input", "AAPL")

        # Add to Recent
        if us_name_to_ticker and selected_us_name_val:
             if selected_us_name_val not in st.session_state['recent_us']:
                 st.session_state['recent_us'].insert(0, selected_us_name_val)
             else:
                 st.session_state['recent_us'].remove(selected_us_name_val)
                 st.session_state['recent_us'].insert(0, selected_us_name_val)
        elif not us_name_to_ticker:
             if us_ticker_input_val not in st.session_state['recent_us']:
                 st.session_state['recent_us'].insert(0, us_ticker_input_val)
             else:
                 st.session_state['recent_us'].remove(us_ticker_input_val)
                 st.session_state['recent_us'].insert(0, us_ticker_input_val)

        if len(st.session_state['recent_us']) > 10:
            st.session_state['recent_us'] = st.session_state['recent_us'][:10]
            
        localS.setItem('recent_us', st.session_state['recent_us'])

    if st.session_state.get('run_us'):
        if us_name_to_ticker:
            selected_us_name = st.session_state.get("us_select_box", us_sorted_names[default_idx] if us_sorted_names else "")
            us_ticker = us_name_to_ticker.get(selected_us_name)
        else:
            us_ticker = st.session_state.get("us_code_input", "AAPL").upper()
            selected_us_name = us_ticker

        int_map = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "M", "연봉 (Yearly)": "Y"}
        period_code_us = int_map.get(interval_us_sel, "D")
        
        # Render TradingView Chart immediately before fetching data
        render_tradingview_widget(us_ticker, period_code_us)

        with st.spinner('미국 주식 데이터 가져오는 중...'):
            start_load_time = time.time()

            start_str_us = start_date_us.strftime("%Y%m%d")
            end_str_us = end_date_us.strftime("%Y%m%d")

            # Use Local Dates

            # Call cached function with string dates
            df_us = fetch_us_data(us_ticker, start_str_us, end_str_us, interval_us_sel)

            if not df_us.empty:
                if interval_us_sel == "일/주/월/연봉 종합분석":
                    st.success(f"'{us_ticker}' 전체 구간(일/주/월/년) 입체 분석")

                     # Slicing
                    @st.cache_data(ttl=3600, show_spinner="멀티 타임프레임 데이터 준비 중...")
                    def get_multi_timeframe_data_us(ticker, df_us_source):
                        # Daily (Last 1 Year)
                        if df_us_source.empty:
                            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

                        d_cutoff = df_us_source.index.max() - timedelta(days=365)
                        df_d = df_us_source.loc[d_cutoff:].sort_index()
                        df_d = calculate_indicators(df_d)

                        # Weekly (Last 10 Years)
                        w_cutoff = df_us_source.index.max() - timedelta(days=365*10)
                        df_w_all = resample_ohlcv(df_us_source, "W")
                        df_w = df_w_all.loc[w_cutoff:]
                        df_w = calculate_indicators(df_w)

                        # Monthly (Max)
                        df_m = resample_ohlcv(df_us_source, "M")
                        df_m = calculate_indicators(df_m)

                        # Yearly: Max (New)
                        df_y = resample_ohlcv(df_us_source, "Y")
                        df_y = calculate_indicators(df_y)

                        return df_d, df_w, df_m, df_y

                    # Use cached function
                    df_d, df_w, df_m, df_y = get_multi_timeframe_data_us(us_ticker, df_us)

                    # Fetch Hourly (Max 30 days)
                    df_h_us = pd.DataFrame()
                    try:
                        end_h = datetime.today()
                        start_h = end_h - timedelta(days=29)

                        df_h_raw = yf.download(us_ticker, start=start_h, end=end_h + timedelta(days=1), interval="60m", progress=False)

                        if not df_h_raw.empty:
                            if isinstance(df_h_raw.columns, pd.MultiIndex):
                                df_h_us = df_h_raw.copy()
                                df_h_us.columns = df_h_us.columns.droplevel(0)
                            else:
                                df_h_us = df_h_raw
                            if df_h_us.index.tzinfo is not None:
                                df_h_us.index = df_h_us.index.tz_convert('Asia/Seoul').tz_localize(None)
                    except:
                        pass

                    timeframe_dfs = {
                        "Daily": df_d,
                        "Weekly": df_w,
                        "Monthly": df_m,
                        "Yearly": df_y
                    }

                    t1, t2, t3, t4, t5 = st.tabs([" 종합 리포트", "📅 일봉", "📅 주봉", "📅 월봉", "📅 연봉"])

                    name_diplay = selected_us_name if us_name_to_ticker else us_ticker
                    with t1:
                        news_list = []
                        render_multi_ai_content(us_ticker, name_diplay, "US", "USD", timeframe_dfs, news_list)

                    with t2:
                        st.dataframe(df_d)
                        run_analysis_and_prompts(df_d, us_ticker, name_diplay, "US", "USD", "일봉", key_suffix="us_d")
                    with t3:
                        st.dataframe(df_w)
                        run_analysis_and_prompts(df_w, us_ticker, name_diplay, "US", "USD", "주봉", key_suffix="us_w")
                    with t4:
                        st.dataframe(df_m)
                        run_analysis_and_prompts(df_m, us_ticker, name_diplay, "US", "USD", "월봉", key_suffix="us_m")
                    with t5:
                        st.dataframe(df_y)
                        run_analysis_and_prompts(df_y, us_ticker, name_diplay, "US", "USD", "연봉", key_suffix="us_y")

                else:
                    if interval_us_sel in ["1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"]:
                        df_final = df_us.sort_index()
                    else:
                        int_map = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "M", "연봉 (Yearly)": "Y"}
                        period_code = int_map[interval_us_sel]
                        
                        if period_code == "D":
                            df_final = df_us.sort_index()
                        else:
                            df_final = resample_ohlcv(df_us, period_code)
                            
                    df_final = calculate_indicators(df_final)
                        
                    elapsed = time.time() - start_load_time
                    st.success(f"'{selected_us_name if us_name_to_ticker else us_ticker}' {interval_us_sel} 분석 (⏱️ 소요 시간: {elapsed:.2f}초)")
                    
                    st.dataframe(df_final)
                    name_diplay = selected_us_name if us_name_to_ticker else us_ticker
                    run_analysis_and_prompts(df_final, us_ticker, name_diplay, "US", "USD", interval_us_sel, key_suffix="us_single")
            else:
                st.error("데이터를 찾을 수 없습니다.")
