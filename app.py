"""app.py — 주식 기술적 분석 앱 (오케스트레이터)

이 파일은 앱의 진입점입니다. UI 레이아웃, 탭, 사이드바 배치만 담당하며
실제 로직은 각 모듈(krx_data, us_data, kr_ui, utils 등)에 위임합니다.
"""
import io
import time
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from streamlit_local_storage import LocalStorage

from ai_client import get_gemini_response
from date_fragment import date_selector_fragment
from kr_ui import render_krx_ranking
from krx_data import build_name_to_ticker, clamp_intraday_dates, fetch_krx_data, get_krx_mapping
from prompts import (
    generate_chatgpt_prompt,
    generate_gemini_prompt,
    generate_multi_timeframe_chatgpt_prompt,
    generate_multi_timeframe_gemini_prompt,
)
from us_data import fetch_us_data, get_sp500_mapping, get_us_most_active, prepare_us_ranking_df
from utils import calculate_indicators, resample_ohlcv

# ─── Korean Standard Time ─────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(tz=_KST)


def today_kst() -> datetime:
    return datetime.now(tz=_KST).replace(tzinfo=None)


# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Stock Technical Analysis")

localS = LocalStorage()

st.markdown(
    """
    <style>
    @media (max-width: 768px) {
        .block-container { padding-top: 2rem; padding-left: 1rem; padding-right: 1rem; }
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.2rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        div[data-testid="stDataFrame"] { overflow-x: auto; }
        .stButton>button { width: 100%; }
        .stSelectbox>div[data-baseweb="select"] { width: 100%; }
        .stTextInput>div[data-baseweb="input"] { width: 100%; }
        .modebar-container { display: none !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Korean HTML lang tag to prevent browser auto-translation
st.markdown(
    """<script>
        window.parent.document.getElementsByTagName('html')[0].setAttribute('lang', 'ko');
    </script>""",
    unsafe_allow_html=True,
)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1)
def get_major_indices() -> dict:
    indices = {
        "🇺🇸 S&P 500": "^GSPC",
        "🇺🇸 NASDAQ": "^IXIC",
        "🇰🇷 KOSPI": "^KS11",
        "🇰🇷 KOSDAQ": "^KQ11",
        "💵 USD/KRW": "KRW=X",
    }
    commodities = {
        "🥇 Gold": ("GC=F", "/oz"),
        "🥈 Silver": ("SI=F", "/oz"),
        "🥉 Copper": ("HG=F", "/lb"),
        "💰 Bitcoin": ("BTC-USD", ""),
        "💎 Ethereum": ("ETH-USD", ""),
    }

    results: dict = {"indices": {}, "commodities": {}}
    try:
        all_tickers = list(indices.values()) + [v[0] for v in commodities.values()]
        df = yf.download(all_tickers, period="5d", progress=False)
        if df.empty or "Close" not in df.columns:
            return results

        closes = df["Close"]

        def _get(ticker: str):
            s = closes[ticker] if isinstance(closes, pd.DataFrame) and ticker in closes.columns else closes
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s = s.dropna()
            if len(s) >= 2:
                val = float(s.iloc[-1])
                diff = float(s.iloc[-1] - s.iloc[-2])
                pct = diff / float(s.iloc[-2]) * 100
                return val, diff, pct
            return None

        for name, ticker in indices.items():
            data = _get(ticker)
            if data:
                results["indices"][name] = data

        krw_data = _get("KRW=X")
        krw_rate = krw_data[0] if krw_data else 1350.0
        for name, (ticker, unit) in commodities.items():
            data = _get(ticker)
            if data:
                usd, diff, pct = data
                results["commodities"][name] = (usd, diff, pct, usd * krw_rate, unit)
    except Exception:
        pass
    return results


_SIDEBAR_URLS = {
    "🇺🇸 S&P 500": "https://finance.naver.com/world/sise.naver?symbol=SPI@SPX",
    "🇺🇸 NASDAQ": "https://finance.naver.com/world/sise.naver?symbol=NAS@IXIC",
    "🇰🇷 KOSPI": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "🇰🇷 KOSDAQ": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
    "💵 USD/KRW": "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW",
    "🥇 Gold": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_GC",
    "🥈 Silver": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_SI",
    "🥉 Copper": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_HG",
    "💰 Bitcoin": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-BTC",
    "💎 Ethereum": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-ETH",
}


def _render_sidebar() -> None:
    if st.sidebar.button("새로고침 (Refresh)"):
        st.cache_data.clear()
        for key in ("krx_market_df", "krx_time", "us_top_df", "us_time"):
            st.session_state.pop(key, None)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🌍 주요 시장 지수")
    data = get_major_indices()

    if not data:
        st.sidebar.caption("지수 데이터 로딩 실패")
        return

    st.sidebar.caption(f"기준: {now_kst().strftime('%m/%d %H:%M')} (KST)")

    for name, (val, diff, pct) in data.get("indices", {}).items():
        url = _SIDEBAR_URLS.get(name, "#")
        val_fmt = f"{val:,.2f}" + (" 원" if "USD/KRW" in name else "")
        st.sidebar.markdown(f"**[{name}]({url})**")
        st.sidebar.metric(" ", val_fmt, f"{diff:,.2f} ({pct:+.2f}%)", label_visibility="collapsed")

    st.sidebar.markdown("---")
    with st.sidebar.expander("⚙️ KRX 세션 (쿠키) 관리", expanded=False):
        st.write("KRX 데이터 조회가 안 될 경우 쿠키를 갱신하세요.")
        if st.button("🚀 로컬 브라우저에서 쿠키 자동 추출", help="Antigravity 브라우저가 data.krx.co.kr에 로그인된 상태여야 합니다."):
            import subprocess
            with st.spinner("쿠키 추출 중..."):
                try:
                    res = subprocess.run(["python", "get_browser_cookies.py"], capture_output=True, text=True)
                    if "쿠키 저장 완료" in res.stdout:
                        st.success("✅ 로컬 쿠키 갱신 성공!")
                        st.cache_data.clear()
                        st.cache_resource.clear()
                    else:
                        st.error("❌ 추출 실패. 브라우저 창을 확인하세요.")
                        st.code(res.stdout)
                except Exception as e:
                    st.error(f"오류: {e}")
                    
        st.markdown("---")
        st.markdown("💡 **JSESSIONID 수동 복사하는 법** (PC 브라우저)")
        st.info(
            "1. PC에서 [KRX 웹사이트](https://data.krx.co.kr) 접속 후 로그인합니다.\n"
            "2. 키보드 `F12`를 눌러 개발자 도구를 열고 상단의 **Application (애플리케이션)** 탭으로 이동합니다.\n"
            "3. 좌측 메뉴에서 **Storage > Cookies > https://data.krx.co.kr** 를 클릭합니다.\n"
            "4. 우측 표에서 이름이 **`JSESSIONID`** 인 항목을 찾아 **Value(값)** 부분을 더블클릭 후 복사(Ctrl+C)합니다."
        )
        
        new_jsid = st.text_input("복사한 JSESSIONID 붙여넣기")
        if st.button("수동 쿠키 저장"):
            if new_jsid:
                import json
                from pathlib import Path
                cookie_file = Path("krx_cookies.json")
                try:
                    if cookie_file.exists():
                        cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
                    else:
                        cookies = {}
                except Exception:
                    cookies = {}
                cookies["JSESSIONID"] = new_jsid
                cookie_file.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
                st.success("✅ JSESSIONID 수동 저장 완료!")
                st.cache_data.clear()
                st.cache_resource.clear()
            else:
                st.warning("JSESSIONID 값을 입력하세요.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("💎 원자재 & 코인")
    for name, (usd, diff, pct, krw, unit) in data.get("commodities", {}).items():
        label = f"{name} {unit}".strip()
        url = _SIDEBAR_URLS.get(name, "#")
        st.sidebar.markdown(f"**[{label}]({url})**")
        st.sidebar.metric(" ", f"${usd:,.2f}", f"{pct:+.2f}%", label_visibility="collapsed")
        st.sidebar.markdown(
            f"<div style='color:gray;font-size:1.1em;margin-top:-10px;margin-bottom:10px;'>약 {krw:,.0f} 원</div>",
            unsafe_allow_html=True,
        )


_render_sidebar()

# ─── Title & Tabs ─────────────────────────────────────────────────────────────
st.title("📈 AI 주식 기술적 분석 (v2.3)")
tab_kr_indie, tab_us_indie, tab_kr_market, tab_us_market = st.tabs([
    "KR 국내 주식 개별 분석",
    "US 해외 주식 개별 분석",
    "🇰🇷 국내 주식 (KRX)",
    "🇺🇸 해외 주식 (US)"
])


# ─── Shared UI Components ─────────────────────────────────────────────────────

def render_tradingview_widget(symbol: str, interval: str = "D") -> None:
    """TradingView 위젯을 렌더링합니다."""
    container_id = f"tv_{symbol.replace(':', '_')}"
    components.html(
        f"""
        <div class="tradingview-widget-container" style="height:100%;width:100%">
          <div id="{container_id}" style="height:calc(100% - 32px);width:100%"></div>
          <script src="https://s3.tradingview.com/tv.js"></script>
          <script>
          new TradingView.widget({{
            "autosize": true, "symbol": "{symbol}", "interval": "{interval}",
            "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "kr",
            "enable_publishing": false, "allow_symbol_change": true,
            "container_id": "{container_id}"
          }});
          </script>
        </div>
        """,
        height=500,
    )

import json as _json

def render_copy_buttons(gpt_prompt: str, gem_prompt: str, suffix: str) -> None:
    st.caption("🚀 버튼 클릭 한 번으로 프롬프트 복사 + AI 채팅 열기!")
    
    def _copy_btn(label: str, text: str, url: str, bg: str, btn_id: str) -> str:
        t_json = _json.dumps(text)
        return f"""
        <button id="{btn_id}" style="background:{bg};color:white;border:none;padding:10px 0;width:100%;
        border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;">{label}</button>
        <script>
        document.getElementById('{btn_id}').addEventListener('click', function() {{
            var txt = {t_json};
            if(navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(txt).then(()=>window.open('{url}','_blank')).catch(()=>window.open('{url}','_blank'));
            }} else {{
                var ta = document.createElement('textarea');
                ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
                document.body.appendChild(ta); ta.focus(); ta.select();
                try {{ document.execCommand('copy'); }} catch(e) {{}}
                document.body.removeChild(ta);
                window.open('{url}','_blank');
            }}
        }});
        </script>
        """

    lb1, lb2, _ = st.columns([1, 1, 3])
    with lb1:
        components.html(_copy_btn("📋 복사 후 ChatGPT 열기", gpt_prompt, "https://chatgpt.com/", "#10a37f", f"bgpt_{suffix}"), height=50)
    with lb2:
        components.html(_copy_btn("📋 복사 후 Gemini 열기", gem_prompt, "https://gemini.google.com/", "#1a73e8", f"bgem_{suffix}"), height=50)


@st.fragment
def render_ai_analysis_content(ticker, name, market, currency, interval_label, display_df, key_suffix):
    """보유 상태 선택 → Gemini 자동 분석 리포트 → 수동 프롬프트를 렌더링합니다."""
    h_key = f"holding_{ticker}_{interval_label}_{key_suffix}"
    holding_status = st.pills(
        "💡 투자 자산 보유 상태 (Holding Status)",
        ["보유(매도예정)", "미보유(매수예정)", "관망(중립)"],
        selection_mode="single",
        default=st.session_state.get(h_key, "관망(중립)"),
        key=h_key,
    ) or "관망(중립)"

    avg_price = None
    if holding_status == "보유(매도예정)":
        avg_key = f"avg_price_{ticker}_{interval_label}_{key_suffix}"
        avg_price = st.number_input(
            f"현재 평단가 입력 ({currency}) - 선택사항",
            min_value=0.0,
            value=st.session_state.get(avg_key, 0.0),
            step=100.0 if currency == "KRW" else 1.0,
            key=avg_key,
            help="평단가를 입력하시면 AI가 평단가 대비 수익 실현/손실 최소화 전략을 상세히 분석합니다.",
        )

    start_dt_str = end_dt_str = "알 수 없음"
    if not display_df.empty:
        start_dt_str = display_df.index.min().strftime("%Y-%m-%d %H:%M")
        end_dt_str = display_df.index.max().strftime("%Y-%m-%d %H:%M")

    gpt_p = generate_chatgpt_prompt(ticker, name, market, currency, interval_label, display_df, [], holding_status, avg_price, start_dt_str, end_dt_str)
    gem_p = generate_gemini_prompt(ticker, name, market, currency, interval_label, display_df, [], holding_status, avg_price, start_dt_str, end_dt_str)

    st.divider()
    st.subheader("⚡ Gemini AI 자동 분석 리포트")
    try:
        gemini_api_key = st.secrets["gemini"]["api_key"]
    except Exception:
        gemini_api_key = None

    if gemini_api_key:
        if st.button("🤖 Gemini AI 자동 분석 시작 (단일 타임프레임)", key=f"btn_gemini_{ticker}_{interval_label}_{key_suffix}"):
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Gemini가 시장 데이터를 심층 분석 중입니다..."):
                    try:
                        st.markdown(get_gemini_response(gem_p, gemini_api_key))
                    except Exception as e:
                        st.error(f"Gemini 분석 중 오류: {e}")
    else:
        st.info("API 키가 설정되지 않아 자동 분석을 건너뜁니다.")

    st.divider()
    st.subheader("📋 수동 분석용 프롬프트 (Backup)")
    render_copy_buttons(gpt_p, gem_p, f"single_{ticker}_{key_suffix}")
    st.info("아래 코드를 복사하여 AI 서비스에 직접 붙여넣으셔도 됩니다.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        st.code(gpt_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        st.code(gem_p, language=None)


@st.fragment
def render_multi_ai_content(code, name, market, currency, dfs, news):
    """멀티 타임프레임 AI 분석 리포트를 렌더링합니다."""

    prefix = "kr" if currency == "KRW" else "us"
    h_key = f"{prefix}_multi_{code}_holding"
    holding_status = st.pills(
        "💡 투자 자산 보유 상태 (Holding Status)",
        ["보유(매도예정)", "미보유(매수예정)", "관망(중립)"],
        selection_mode="single",
        default=st.session_state.get(h_key, "관망(중립)"),
        key=h_key,
    ) or "관망(중립)"

    avg_price = None
    if holding_status == "보유(매도예정)":
        avg_key = f"avg_price_{prefix}_multi_{code}"
        avg_price = st.number_input(
            f"현재 평단가 입력 ({currency}) - 선택사항",
            min_value=0.0,
            value=st.session_state.get(avg_key, 0.0),
            step=100.0 if currency == "KRW" else 1.0,
            key=avg_key,
        )

    start_dt_str = end_dt_str = "알 수 없음"
    df_daily = dfs.get("Daily", pd.DataFrame())
    if not df_daily.empty:
        start_dt_str = df_daily.index.min().strftime("%Y-%m-%d %H:%M")
        end_dt_str = df_daily.index.max().strftime("%Y-%m-%d %H:%M")
        st.dataframe(df_daily)

    st.subheader("🤖 AI 종합 분석 리포트 (Multi-Timeframe)")
    try:
        gemini_api_key = st.secrets["gemini"]["api_key"]
    except Exception:
        gemini_api_key = None

    gpt_multi_p = generate_multi_timeframe_chatgpt_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
    gem_multi_p = generate_multi_timeframe_gemini_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)

    if gemini_api_key:
        if st.button("🤖 Gemini AI 자동 분석 시작 (Multi-Timeframe)", key=f"btn_gemini_multi_{prefix}_{code}"):
            with st.spinner("멀티 타임프레임 분석 중..."):
                st.markdown(get_gemini_response(gem_multi_p, gemini_api_key))
    else:
        st.warning("⚠️ Gemini API 키가 설정되지 않았습니다.")
        st.code('[gemini]\napi_key = "YOUR_GEMINI_API_KEY"', language="toml")

    st.divider()
    st.subheader("📋 수동 종합 분석용 프롬프트 (Backup)")
    render_copy_buttons(gpt_multi_p, gem_multi_p, f"multi_{code}")
    st.info("아래 코드를 복사하여 AI 서비스에 직접 붙여넣으셔도 됩니다.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        st.code(gpt_multi_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        st.code(gem_multi_p, language=None)


def run_analysis_and_prompts(df, ticker, name, market, currency, interval_label, ranks=None, key_suffix="", selected_data=None):
    """기술적 지표 계산 → 데이터 테이블 → AI 프롬프트를 한 번에 렌더링합니다."""
    if df is None or df.empty:
        st.error("데이터가 없습니다.")
        return

    with st.spinner("기술적 지표 계산 중..."):
        df = calculate_indicators(df)

    start_dt, end_dt = df.index.min(), df.index.max()
    days_diff = (end_dt - start_dt).days

    _period_map = {
        "_d": "최근 1년", "_w": "최근 10년", "_m": "상장일 - 현재 (최대)", "_h": "최근 1개월",
    }
    period_str = next(
        (v for k, v in _period_map.items() if key_suffix.endswith(k)),
        None,
    )
    if period_str is None:
        if "연봉" in interval_label or "Yearly" in interval_label:
            period_str = "상장일 - 현재 (최대)"
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
            months = round(days_diff / 30.44, 1)
            period_str = f"{int(months)}개월" if months % 1 == 0 else f"{months}개월"
            if days_diff < 28:
                period_str = f"{days_diff}일"

    st.success(f"{period_str}의 분석기간 ({start_dt.strftime('%Y-%m-%d')} - {end_dt.strftime('%Y-%m-%d')}), {len(df)}개 데이터 추출.")

    if ranks:
        r_cols = st.columns(len(ranks))
        for i, (label, val) in enumerate(ranks.items()):
            with r_cols[i]:
                st.metric(label, val)
    st.divider()

    base_cols = ["Open", "High", "Low", "Close", "Volume"]
    indicator_cols = ["SMA_5", "SMA_20", "SMA_60", "RSI_14", "MACD", "BB_Upper", "BB_Lower"]

    if selected_data is None:
        display_cols = base_cols + indicator_cols + [c for c in df.columns if c not in base_cols + indicator_cols]
    else:
        display_cols = []
        if "기본 시세 (OHLCV)" in selected_data:
            display_cols.extend(base_cols)
        if "기술적 지표 (Indicators)" in selected_data:
            display_cols.extend(indicator_cols)
        known = set(base_cols + indicator_cols)
        display_cols.extend(c for c in df.columns if c not in known)

    final_cols = [c for c in display_cols if c in df.columns]
    display_df = df[final_cols].sort_index(ascending=False)

    st.subheader(f"🔢 데이터 테이블 ({interval_label})")
    st.caption("아래 표를 스크롤하여 전체 데이터를 확인할 수 있습니다.")
    st.dataframe(display_df.style.format("{:,.2f}"), height=300, width="stretch")

    render_ai_analysis_content(ticker, name, market, currency, interval_label, df[final_cols], key_suffix)

    csv = df.to_csv().encode("utf-8")
    st.download_button(
        "📥 CSV 다운로드",
        data=csv,
        file_name=f"{ticker}_{interval_label}_analysis.csv",
        mime="text/csv",
        key=f"btn_down_{ticker}_{market}_{interval_label}_{key_suffix}",
    )


# ─── Input Fragments ──────────────────────────────────────────────────────────

@st.fragment
def render_krx_inputs_fragment(sorted_names, name_to_ticker, default_index):
    col1, col2 = st.columns([2, 1])
    with col1:
        pill_val = st.session_state.get("kr_pill_clicked_val")

        if name_to_ticker:
            if "kr_select_box" not in st.session_state:
                st.session_state["kr_select_box"] = sorted_names[default_index] if sorted_names else None
            if pill_val and pill_val in sorted_names:
                st.session_state["kr_select_box"] = pill_val
                st.session_state["kr_pill_clicked_val"] = None
            st.selectbox("종목 선택 (이름으로 검색)", sorted_names, key="kr_select_box")
        else:
            if "kr_code_input" not in st.session_state:
                st.session_state["kr_code_input"] = pill_val or "005930"
            elif pill_val:
                st.session_state["kr_code_input"] = pill_val
                st.session_state["kr_pill_clicked_val"] = None
            st.text_input("종목 코드 입력 (예: 005930)", key="kr_code_input")

        ls_kr = localS.getItem("recent_kr")
        if ls_kr is not None and isinstance(ls_kr, list):
            st.session_state["recent_kr"] = ls_kr
        elif "recent_kr" not in st.session_state:
            st.session_state["recent_kr"] = []

        def _clear_kr():
            st.session_state["recent_kr"] = []
            localS.setItem("recent_kr", [])

        if st.session_state["recent_kr"]:
            st.write("최근 검색 (Recent):")
            c_rec, c_del = st.columns([0.85, 0.15])
            with c_rec:
                sel_pill = st.pills("Recent KRX", st.session_state["recent_kr"], selection_mode="single", key="pills_kr", label_visibility="collapsed")
            with c_del:
                st.button("🗑️", on_click=_clear_kr, help="기록 삭제", key="btn_clear_kr")
            if sel_pill:
                if name_to_ticker and sel_pill in sorted_names and sel_pill != st.session_state.get("kr_select_box"):
                    st.session_state["kr_pill_clicked_val"] = sel_pill
                    st.session_state["run_krx"] = True
                    st.rerun()
                elif not name_to_ticker and sel_pill != st.session_state.get("kr_code_input"):
                    st.session_state["kr_pill_clicked_val"] = sel_pill
                    st.rerun()

    with col2:
        st.pills(
            "분석간격",
            ["일/주/월/연봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)",
             "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"],
            default="일/주/월/연봉 종합분석",
            selection_mode="single",
            key="kr_int",
        )
        extra_opts = ["기본 시세 (OHLCV)", "기술적 지표 (Indicators)", "펀더멘털 (Fundamental)", "수급 (Investor)", "시가총액 (Market Cap)"]
        st.multiselect("데이터 항목 선택 (Data Selection)", extra_opts, default=extra_opts, key="kr_data_sel")

    interval_kr_sel = st.session_state.get("kr_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    date_selector_fragment("kr", default_end - timedelta(days=365), default_end, interval_kr_sel)


@st.fragment
def render_us_inputs_fragment(us_sorted_names, us_name_to_ticker, default_idx):
    col1, col2 = st.columns([2, 1])
    with col1:
        pill_val = st.session_state.get("us_pill_clicked_val")

        if us_name_to_ticker:
            if "us_select_box" not in st.session_state:
                st.session_state["us_select_box"] = us_sorted_names[default_idx] if us_sorted_names else None
            if pill_val and pill_val in us_sorted_names:
                st.session_state["us_select_box"] = pill_val
                st.session_state["us_pill_clicked_val"] = None
            st.selectbox("종목 선택 (S&P 500 목록)", us_sorted_names, key="us_select_box")
        else:
            if "us_ticker_input" not in st.session_state:
                st.session_state["us_ticker_input"] = pill_val or "AAPL"
            elif pill_val:
                st.session_state["us_ticker_input"] = pill_val
                st.session_state["us_pill_clicked_val"] = None
            st.text_input("티커 입력 (예: AAPL, TSLA)", key="us_ticker_input")

        ls_us = localS.getItem("recent_us")
        if ls_us is not None and isinstance(ls_us, list):
            st.session_state["recent_us"] = ls_us
        elif "recent_us" not in st.session_state:
            st.session_state["recent_us"] = []

        def _clear_us():
            st.session_state["recent_us"] = []
            localS.setItem("recent_us", [])

        if st.session_state["recent_us"]:
            st.write("최근 검색 (Recent):")
            c_rec, c_del = st.columns([0.85, 0.15])
            with c_rec:
                sel_pill = st.pills("Recent US", st.session_state["recent_us"], selection_mode="single", key="pills_us", label_visibility="collapsed")
            with c_del:
                st.button("🗑️", on_click=_clear_us, help="기록 삭제", key="btn_clear_us")
            if sel_pill:
                if us_name_to_ticker and sel_pill in us_sorted_names and sel_pill != st.session_state.get("us_select_box"):
                    st.session_state["us_pill_clicked_val"] = sel_pill
                    st.session_state["run_us"] = True
                    st.rerun()
                elif not us_name_to_ticker and sel_pill != st.session_state.get("us_ticker_input"):
                    st.session_state["us_pill_clicked_val"] = sel_pill
                    st.rerun()

    with col2:
        st.pills(
            "데이터 간격 (Interval)",
            ["일/주/월/연봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)",
             "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"],
            default="일/주/월/연봉 종합분석",
            selection_mode="single",
            key="us_int",
        )

    interval_us_sel = st.session_state.get("us_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    date_selector_fragment("us", default_end - timedelta(days=365), default_end, interval_us_sel)


# ─── Multi-Timeframe Helper ───────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner="멀티 타임프레임 데이터 준비 중...")
def _get_multi_timeframe(code: str, df_daily: pd.DataFrame):
    d_cutoff = df_daily.index.max() - timedelta(days=365)
    # 지표를 원본 전체 데이터에 먼저 계산한 후, 필요한 기간(1년)만 잘라냅니다.
    df_d = calculate_indicators(df_daily.sort_index()).loc[d_cutoff:]

    w_cutoff = df_daily.index.max() - timedelta(days=3650)
    # 주봉도 전체로 리샘플링 후 계산하고 10년치만 잘라냅니다.
    df_w = calculate_indicators(resample_ohlcv(df_daily, "W")).loc[w_cutoff:]
    df_m = calculate_indicators(resample_ohlcv(df_daily, "ME"))
    df_y = calculate_indicators(resample_ohlcv(df_daily, "YE"))

    return df_d, df_w, df_m, df_y


def _push_recent(key: str, value: str, storage_key: str) -> None:
    lst = st.session_state.setdefault(key, [])
    if value in lst:
        lst.remove(value)
    lst.insert(0, value)
    st.session_state[key] = lst[:10]
    localS.setItem(storage_key, st.session_state[key])


# ─── KRX Tabs ─────────────────────────────────────────────────────────────────

# Ticker mapping
ticker_to_name = get_krx_mapping()
name_to_ticker, sorted_names = build_name_to_ticker(ticker_to_name)

with tab_kr_market:
    st.header("🇰🇷 한국거래소 (KRX) 시장 동향")

    krx_time_str = st.session_state.get("krx_time", now_kst().strftime("%m/%d %H:%M"))
    st.subheader(f"🔥 오늘의 거래량 TOP 10 ({krx_time_str})")

    today_str = today_kst().strftime("%Y%m%d")

    # Ranking section
    DISPLAY_COLS = ["종목명", "종가", "시가", "고가", "저가", "52주최고", "등락률", "거래량", "거래대금", "is_breakout"]
    NUMERIC_COLS = ["종가", "시가", "고가", "저가", "거래량", "거래대금", "52주최고"]

    try:
        render_krx_ranking(today_str, krx_time_str, name_to_ticker, NUMERIC_COLS, DISPLAY_COLS)
    except Exception as e:
        st.warning(f"랭킹 데이터를 가져오는데 실패했습니다: {e}\n\n```\n{traceback.format_exc()}\n```")


with tab_kr_indie:
    st.header("KR 국내 주식 개별 분석")

    default_index = 0
    if name_to_ticker:
        samsung = [k for k in sorted_names if k == "삼성전자"] or [k for k in sorted_names if "삼성전자" in k]
        if samsung:
            default_index = sorted_names.index(samsung[0])

    render_krx_inputs_fragment(sorted_names, name_to_ticker, default_index)

    start_date_kr = st.session_state.get("kr_start", datetime.today() - timedelta(days=365))
    end_date_kr = st.session_state.get("kr_end", datetime.today())
    interval_kr_sel = st.session_state.get("kr_int", "일/주/월/연봉 종합분석")
    extra_data_sel = st.session_state.get("kr_data_sel", ["기본 시세 (OHLCV)", "기술적 지표 (Indicators)", "펀더멘털 (Fundamental)", "수급 (Investor)", "시가총액 (Market Cap)"])

    if st.button("🚀 분석 실행 (KRX Analysis)", type="primary", width="stretch"):
        symbol = (
            st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else None)
            if name_to_ticker
            else st.session_state.get("kr_code_input", "005930")
        )
        if not symbol:
            st.warning("종목 또는 코드를 입력/선택해주세요.")
        else:
            st.session_state["run_krx"] = True
            _push_recent("recent_kr", symbol, "recent_kr")

    if st.session_state.get("run_krx"):
        if name_to_ticker:
            selected_name = st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else "")
            kr_code = name_to_ticker.get(selected_name)
        else:
            kr_code = st.session_state.get("kr_code_input", "005930")
            selected_name = kr_code

        render_tradingview_widget(f"KRX:{kr_code}")

        with st.spinner("KRX 데이터 가져오는 중..."):
            t0 = time.time()
            start_date_kr = clamp_intraday_dates(interval_kr_sel, start_date_kr, end_date_kr)
            s_str = start_date_kr.strftime("%Y%m%d")
            e_str = end_date_kr.strftime("%Y%m%d")
            df_kr, market_name = fetch_krx_data(kr_code, s_str, e_str, interval_kr_sel, extra_data_sel)

        try:
            if df_kr.empty:
                st.error("데이터가 없습니다. 종목 코드를 확인해주세요.")
            elif interval_kr_sel == "일/주/월/연봉 종합분석":
                elapsed = time.time() - t0
                st.success(f"'{selected_name}' 전체 구간(일/주/월/년) 입체 분석 (⏱️ {elapsed:.2f}초)")
                df_d, df_w, df_m, df_y = _get_multi_timeframe(kr_code, df_kr)
                t1, t2, t3, t4, t5 = st.tabs(["📊 종합 리포트", "📅 일봉", "📅 주봉", "📅 월봉", "📅 연봉"])
                with t1:
                    render_multi_ai_content(kr_code, selected_name, market_name, "KRW", {"Daily": df_d, "Weekly": df_w, "Monthly": df_m, "Yearly": df_y}, [])
                with t2:
                    run_analysis_and_prompts(df_d, kr_code, selected_name, market_name, "KRW", "일봉", key_suffix="kr_d", selected_data=extra_data_sel)
                with t3:
                    run_analysis_and_prompts(df_w, kr_code, selected_name, market_name, "KRW", "주봉", key_suffix="kr_w", selected_data=extra_data_sel)
                with t4:
                    run_analysis_and_prompts(df_m, kr_code, selected_name, market_name, "KRW", "월봉", key_suffix="kr_m", selected_data=extra_data_sel)
                with t5:
                    run_analysis_and_prompts(df_y, kr_code, selected_name, market_name, "KRW", "연봉", key_suffix="kr_y", selected_data=extra_data_sel)
            else:
                _period_codes = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "ME", "연봉 (Yearly)": "YE"}
                if interval_kr_sel in _period_codes:
                    p = _period_codes[interval_kr_sel]
                    df_final = df_kr.sort_index() if p == "D" else resample_ohlcv(df_kr, p)
                else:
                    df_final = df_kr.sort_index()
                df_final = calculate_indicators(df_final)
                elapsed = time.time() - t0
                st.success(f"'{selected_name}' {interval_kr_sel} 분석 (⏱️ {elapsed:.2f}초)")
                run_analysis_and_prompts(df_final, kr_code, selected_name, market_name, "KRW", interval_kr_sel, key_suffix="kr_single", selected_data=extra_data_sel)
        except Exception as e:
            st.error(f"오류 발생: {e}\n```\n{traceback.format_exc()}\n```")


# ─── US Tabs ────────────────────────────────────────────────────────────────────

us_ticker_map = get_sp500_mapping()
us_name_to_ticker = {f"{n} ({t})": t for t, n in us_ticker_map.items()}
us_sorted_names = sorted(us_name_to_ticker.keys())

with tab_us_market:
    st.header("🇺🇸 미국 주식 (US Stock) 시장 동향")

    us_time_str = st.session_state.get("us_time", now_kst().strftime("%m/%d %H:%M"))
    st.subheader(f"🔥 거래량 상위 Top 10 (Most Active) ({us_time_str})")

    if "us_top_df" not in st.session_state:
        with st.spinner("미국 Top 10 데이터를 가져오는 중..."):
            st.session_state["us_top_df"] = get_us_most_active()
            st.session_state["us_time"] = now_kst().strftime("%m/%d %H:%M")

    us_top_raw = st.session_state.get("us_top_df", pd.DataFrame())

    if not us_top_raw.empty:
        with st.spinner("미국 주식 데이터 분석 중... (52주 신고가 확인)"):
            try:
                us_top_df = prepare_us_ranking_df(us_top_raw)

                def _display_us(df_sub: pd.DataFrame, key_sfx: str) -> None:
                    from kr_ui import add_arrow, color_name, format_price_change

                    df_disp = pd.DataFrame()
                    df_disp["종목명"] = [
                        f"https://m.stock.naver.com/worldstock/stock/{t}/total?name={n} ({t})"
                        for t, n in zip(df_sub["Symbol"], df_sub["Name"])
                    ]
                    for ko, en in [("종가", "Price"), ("시가", "시가"), ("고가", "고가"), ("저가", "저가"), ("52주최고", "52주최고")]:
                        df_disp[ko] = df_sub[en].apply(lambda x: f"{x:,.2f}")
                    df_disp["등락률"] = df_sub["Change_Pct"]
                    df_disp["거래량"] = df_sub["Volume"].apply(lambda x: f"{x:,.0f}")
                    df_disp["거래대금"] = df_sub["TradingValue"].apply(lambda x: f"{x:,.0f}")
                    df_disp["is_breakout"] = df_sub["is_breakout"]

                    styler = df_disp.style
                    if "등락률" in df_disp.columns:
                        styler = styler.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
                    styler = styler.apply(color_name, axis=1)

                    use_candle = st.toggle("📈 가로 캔들 차트로 보기", key=f"toggle_us_{key_sfx}")
                    if use_candle:
                        from kr_ui import render_horizontal_candles
                        t_map = dict(zip(df_sub["Symbol"], df_sub["Name"]))
                        df_num = df_sub.set_index("Symbol")[["Price", "시가", "고가", "저가", "Change_Pct"]].rename(
                            columns={"Price": "현재가", "Change_Pct": "등락률"}
                        )
                        components.html(render_horizontal_candles(df_num, t_map, max_pct=max(10.0, float(df_num["등락률"].abs().max() * 1.2))), height=900, scrolling=True)
                    else:
                        st.dataframe(styler, column_config={
                            "종목명": st.column_config.LinkColumn("종목명(Name)", display_text=r"name=([^&]+)", help="클릭 시 네이버 세계 주식 차트로 이동"),
                            "is_breakout": st.column_config.CheckboxColumn("전고점 돌파", default=False),
                        }, hide_index=True)

                _display_us(us_top_df.head(10), "vol")
                st.subheader(f"💰 거래대금 상위 Top 10 (Trading Value) ({us_time_str})")
                _display_us(us_top_df.sort_values("TradingValue", ascending=False).head(10), "val")

            except Exception as e:
                st.error(f"데이터 처리 중 오류: {e}")
    else:
        st.info("랭킹 데이터를 불러올 수 없습니다.")

with tab_us_indie:
    st.header("US 해외 주식 개별 분석")

    default_idx = 0
    apple = [k for k in us_sorted_names if "Apple" in k]
    if apple:
        default_idx = us_sorted_names.index(apple[0])

    render_us_inputs_fragment(us_sorted_names, us_name_to_ticker, default_idx)

    start_date_us = st.session_state.get("us_start", datetime.today() - timedelta(days=365))
    end_date_us = st.session_state.get("us_end", datetime.today())
    interval_us_sel = st.session_state.get("us_int", "일/주/월/연봉 종합분석")

    if st.button("🚀 분석 실행 (US Analysis)", type="primary", width="stretch"):
        symbol = (
            st.session_state.get("us_select_box", us_sorted_names[default_idx] if us_sorted_names else None)
            if us_name_to_ticker
            else st.session_state.get("us_ticker_input", "AAPL")
        )
        if not symbol:
            st.warning("종목코드(티커)를 입력/선택해주세요.")
        else:
            st.session_state["run_us"] = True
            _push_recent("recent_us", symbol, "recent_us")

    if st.session_state.get("run_us"):
        if us_name_to_ticker:
            selected_us_name = st.session_state.get("us_select_box", us_sorted_names[default_idx] if us_sorted_names else "")
            us_ticker = us_name_to_ticker.get(selected_us_name)
        else:
            us_ticker = st.session_state.get("us_ticker_input", "AAPL").upper()
            selected_us_name = us_ticker

        _period_codes_us = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "M", "연봉 (Yearly)": "Y"}
        period_code_us = _period_codes_us.get(interval_us_sel, "D")

        # TradingView chart
        components.html(
            f"""
            <div class="tradingview-widget-container" style="margin-bottom:20px">
              <div id="tv_{us_ticker}"></div>
              <script src="https://s3.tradingview.com/tv.js"></script>
              <script>
              new TradingView.widget({{
                "width":"100%","height":1180,"symbol":"{us_ticker}","interval":"{period_code_us}",
                "timezone":"Asia/Seoul","theme":"light","style":"1","locale":"kr",
                "enable_publishing":false,"allow_symbol_change":true,"container_id":"tv_{us_ticker}"
              }});
              </script>
            </div>""",
            height=1200,
        )

        with st.spinner("미국 주식 데이터 가져오는 중..."):
            t0 = time.time()
            df_us = fetch_us_data(us_ticker, start_date_us.strftime("%Y%m%d"), end_date_us.strftime("%Y%m%d"), interval_us_sel)

        if df_us.empty:
            st.error("데이터를 찾을 수 없습니다.")
        elif interval_us_sel == "일/주/월/연봉 종합분석":
            st.success(f"'{us_ticker}' 전체 구간(일/주/월/년) 입체 분석")
            df_d, df_w, df_m, df_y = _get_multi_timeframe(us_ticker, df_us)
            t1, t2, t3, t4, t5 = st.tabs([" 종합 리포트", "📅 일봉", "📅 주봉", "📅 월봉", "📅 연봉"])
            name_display = selected_us_name if us_name_to_ticker else us_ticker
            with t1:
                render_multi_ai_content(us_ticker, name_display, "US", "USD", {"Daily": df_d, "Weekly": df_w, "Monthly": df_m, "Yearly": df_y}, [])
            with t2:
                run_analysis_and_prompts(df_d, us_ticker, name_display, "US", "USD", "일봉", key_suffix="us_d")
            with t3:
                run_analysis_and_prompts(df_w, us_ticker, name_display, "US", "USD", "주봉", key_suffix="us_w")
            with t4:
                run_analysis_and_prompts(df_m, us_ticker, name_display, "US", "USD", "월봉", key_suffix="us_m")
            with t5:
                run_analysis_and_prompts(df_y, us_ticker, name_display, "US", "USD", "연봉", key_suffix="us_y")
        else:
            if interval_us_sel in _period_codes_us:
                p = _period_codes_us[interval_us_sel]
                df_final = df_us.sort_index() if p == "D" else resample_ohlcv(df_us, p)
            else:
                df_final = df_us.sort_index()
            df_final = calculate_indicators(df_final)
            elapsed = time.time() - t0
            name_display = selected_us_name if us_name_to_ticker else us_ticker
            st.success(f"'{name_display}' {interval_us_sel} 분석 (⏱️ {elapsed:.2f}초)")
            run_analysis_and_prompts(df_final, us_ticker, name_display, "US", "USD", interval_us_sel, key_suffix="us_single")
