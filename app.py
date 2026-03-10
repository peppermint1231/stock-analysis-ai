"""app.py — 주식 기술적 분석 앱 (오케스트레이터)

이 파일은 앱의 진입점입니다. UI 레이아웃, 탭, 사이드바 배치만 담당하며
실제 로직은 각 모듈(krx_data, us_data, kr_ui, utils 등)에 위임합니다.
"""
import concurrent.futures
import io
import json
import os
import subprocess
import time
import traceback
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from bs4 import BeautifulSoup
from streamlit_local_storage import LocalStorage

from ai_client import get_gemini_response
from date_fragment import date_selector_fragment
from kis_ws import get_kis_client, get_kis_config
from kr_ui import render_krx_nxt_ranking, render_krx_ranking, render_stock_nxt_card
from krx_data import build_name_to_ticker, clamp_intraday_dates, fetch_krx_data, get_krx_mapping, get_krx_mapping_instant
from prompts import (
    generate_chatgpt_prompt,
    generate_claude_prompt,
    generate_gemini_prompt,
    generate_multi_timeframe_chatgpt_prompt,
    generate_multi_timeframe_claude_prompt,
    generate_multi_timeframe_gemini_prompt,
)
from us_data import fetch_us_data, get_sp500_mapping, get_us_most_active, prepare_us_ranking_df
from utils import calculate_indicators, resample_ohlcv, stamp_today_current_time

# ─── NXT 5분봉 백그라운드 저장 시작 ──────────────────────────────────────────
try:
    from krx_data import get_nxt_ranking as _nxt_fetch_for_store
    from nxt_store import start_nxt_scheduler
    start_nxt_scheduler(_nxt_fetch_for_store, interval_minutes=5)
except Exception as _e:
    print(f"[app] NXT 스케줄러 시작 실패: {_e}")

# ─── Korean Standard Time ─────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(tz=_KST)


def today_kst() -> datetime:
    return datetime.now(tz=_KST).replace(tzinfo=None)


# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Stock Technical Analysis", initial_sidebar_state="expanded")

localS = LocalStorage()

st.markdown(
    """
    <style>
    /* ── Mobile-first responsive styles ─────────────────────────────────── */
    @media (max-width: 768px) {
        /* Layout & spacing */
        .block-container { padding-top: 1rem; padding-left: 0.5rem; padding-right: 0.5rem; }
        section[data-testid="stSidebar"] { width: 260px !important; }
        section[data-testid="stSidebar"] .block-container { padding: 0.5rem 0.8rem; }

        /* Typography */
        h1 { font-size: 1.4rem !important; line-height: 1.3 !important; }
        h2 { font-size: 1.2rem !important; }
        h3 { font-size: 1.05rem !important; }

        /* Metrics — compact on small screens */
        div[data-testid="stMetricValue"] { font-size: 1rem !important; }
        div[data-testid="stMetricLabel"] { font-size: 0.75rem !important; word-wrap: break-word; white-space: normal !important; }
        div[data-testid="stMetricDelta"] { font-size: 0.75rem !important; }

        /* DataFrames */
        div[data-testid="stDataFrame"] { font-size: 0.8rem !important; overflow-x: auto !important; }
        div[data-testid="stDataFrame"] table { min-width: 500px; }

        /* Expander */
        div[data-testid="stExpander"] details summary p { font-size: 0.85rem !important; }

        /* Pills — wrap & shrink */
        div[data-testid="stPills"] { overflow-x: auto !important; flex-wrap: nowrap !important; }
        div[data-testid="stPills"] button { padding: 0.25rem 0.5rem !important; font-size: 0.75rem !important; white-space: nowrap; }

        /* Buttons — full width on mobile, prevent icon text overflow */
        .stButton>button { width: 100%; padding: 0.5rem !important; font-size: 0.85rem !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .stDownloadButton>button { width: 100%; font-size: 0.8rem !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        /* Hide Material Symbols icon text on mobile — clip to 0 */
        span.material-symbols-rounded,
        [data-testid="stIconMaterial"] {
            font-size: 0 !important;
            width: 0 !important;
            max-width: 0 !important;
            overflow: hidden !important;
            padding: 0 !important;
            margin: 0 !important;
        }

        /* Inputs */
        .stSelectbox>div[data-baseweb="select"] { width: 100%; }
        .stTextInput>div[data-baseweb="input"] { width: 100%; }
        .stNumberInput>div { width: 100%; }

        /* Tabs — horizontal scroll instead of wrapping */
        div[data-testid="stTabs"] [role="tablist"] { overflow-x: auto; -webkit-overflow-scrolling: touch; flex-wrap: nowrap !important; gap: 0 !important; }
        div[data-testid="stTabs"] button[role="tab"] { padding: 0.3rem 0.5rem !important; font-size: 0.75rem !important; white-space: nowrap; flex-shrink: 0; }

        /* Columns — stack vertically on narrow screens */
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.3rem !important; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] { min-width: 100% !important; flex-basis: 100% !important; }

        /* Plotly toolbar hidden on mobile */
        .modebar-container { display: none !important; }

        /* Code blocks — scrollable */
        .stCode, pre { font-size: 0.75rem !important; overflow-x: auto !important; }

        /* Markdown text */
        .stMarkdown p { font-size: 0.9rem !important; }

        /* Slider — larger touch target */
        div[data-testid="stSlider"] { padding: 0.3rem 0 !important; }
    }

    /* ── Global Material Symbols icon fix (all viewports) ────────────── */
    span.material-symbols-rounded,
    [data-testid="stIconMaterial"] {
        overflow: hidden !important;
        display: inline-block !important;
        vertical-align: middle !important;
        text-overflow: clip !important;
        max-width: 1.5em !important;
        width: 1.5em !important;
        line-height: 1 !important;
    }

    /* ── Tablet breakpoint ──────────────────────────────────────────────── */
    @media (min-width: 769px) and (max-width: 1024px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        div[data-testid="stTabs"] button[role="tab"] { font-size: 0.85rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Korean HTML lang tag + mobile sidebar toggle button
st.markdown(
    """<script>
        window.parent.document.getElementsByTagName('html')[0].setAttribute('lang', 'ko');
    </script>""",
    unsafe_allow_html=True,
)

# Mobile: floating sidebar toggle button (visible only on small screens)
st.markdown(
    """
    <style>
    @media (max-width: 768px) {
        #mobile-sidebar-btn {
            display: block !important;
            position: fixed; top: 0.6rem; left: 0.6rem; z-index: 999999;
            background: #fff; border: 1px solid #ddd; border-radius: 8px;
            padding: 0.3rem 0.6rem; font-size: 1.3rem; cursor: pointer;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15); line-height: 1;
        }
    }
    @media (min-width: 769px) {
        #mobile-sidebar-btn { display: none !important; }
    }
    </style>
    <div id="mobile-sidebar-btn" onclick="
        var btn = window.parent.document.querySelector('[data-testid=stSidebarCollapsedControl] button')
            || window.parent.document.querySelector('button[data-testid=stBaseButton-headerNoPadding]');
        if(btn) btn.click();
    ">☰</div>
    """,
    unsafe_allow_html=True,
)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
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

    def _parse(closes, ticker: str):
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

    # 지수 다운로드 (별도)
    try:
        idx_tickers = list(indices.values())
        df_idx = yf.download(idx_tickers, period="5d", progress=False)
        if not df_idx.empty and "Close" in df_idx.columns:
            for name, ticker in indices.items():
                data = _parse(df_idx["Close"], ticker)
                if data:
                    results["indices"][name] = data
    except Exception:
        pass

    # 원자재/코인 다운로드 (별도 — 하나 실패해도 지수는 표시)
    try:
        cmd_tickers = [v[0] for v in commodities.values()]
        df_cmd = yf.download(cmd_tickers, period="5d", progress=False)
        if not df_cmd.empty and "Close" in df_cmd.columns:
            krw_data = results["indices"].get("💵 USD/KRW")
            krw_rate = krw_data[0] if krw_data else 1350.0
            for name, (ticker, unit) in commodities.items():
                data = _parse(df_cmd["Close"], ticker)
                if data:
                    usd, diff, pct = data
                    results["commodities"][name] = (usd, diff, pct, usd * krw_rate, unit)
    except Exception:
        pass

    return results


@st.cache_data(ttl=60)
def get_kospi_night_futures() -> dict | None:
    """eSignal (https://esignal.co.kr/kospi200-futures-night/) 소켓 API를 폴링하여 KOSPI200 야간선물 데이터를 반환합니다."""
    try:
        import re as _re

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://esignal.co.kr",
            "Origin": "https://esignal.co.kr",
        }

        # 1. sid 발급
        res1 = requests.get(
            "https://esignal.co.kr/proxy/8888/socket.io/?EIO=3&transport=polling",
            headers=headers, timeout=5,
        )
        text = res1.text
        if "{" not in text:
            return None
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
        sid = data.get("sid")
        if not sid:
            return None

        # 2. 데이터 폴링
        res2 = requests.get(
            f"https://esignal.co.kr/proxy/8888/socket.io/?EIO=3&transport=polling&sid={sid}",
            headers=headers, timeout=5,
        )

        match = _re.search(r'42\["populate","(.*?)"\]', res2.text.replace("\n", ""))
        payload_str = None
        if match:
            payload_str = match.group(1).replace('\\"', '"')
        else:
            messages = res2.text.split("\x1e") if "\x1e" in res2.text else [res2.text]
            for m in messages:
                if "populate" in m:
                    parts = m.split('["populate","', 1)
                    if len(parts) > 1:
                        payload_str = parts[1].rsplit('"]')[0].replace('\\"', '"')
                        break

        if not payload_str:
            return None

        info = json.loads(payload_str)
        price = float(info.get("value", 0))
        diff = float(info.get("value_diff", 0))
        value_day = float(info.get("value_day", 1))

        if price == 0 or value_day == 0:
            return None

        pct = (diff / value_day) * 100

        # tstamp(UTC ISO) → KST / 시카고(CT) 시간 변환
        tstamp = info.get("tstamp", "")
        kst_str = ""
        ct_str = ""
        if tstamp:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            try:
                utc_dt = _dt.fromisoformat(tstamp.replace("Z", "+00:00"))
                kst_dt = utc_dt.astimezone(_tz(_td(hours=9)))
                # 시카고: UTC-6(CST) / UTC-5(CDT) — 간이 DST 판정 (3월 둘째 일요일 ~ 11월 첫째 일요일)
                year = utc_dt.year
                # 3월 둘째 일요일
                mar1 = _dt(year, 3, 1, tzinfo=_tz.utc)
                dst_start = mar1 + _td(days=(6 - mar1.weekday()) % 7 + 7)
                # 11월 첫째 일요일
                nov1 = _dt(year, 11, 1, tzinfo=_tz.utc)
                dst_end = nov1 + _td(days=(6 - nov1.weekday()) % 7)
                ct_hours = -5 if dst_start <= utc_dt.replace(hour=2) < dst_end else -6
                ct_dt = utc_dt.astimezone(_tz(_td(hours=ct_hours)))
                kst_str = kst_dt.strftime("%m/%d %H:%M:%S")
                ct_str = ct_dt.strftime("%m/%d %H:%M:%S")
                ct_utc_label = f"UTC{ct_hours}"
            except Exception:
                pass

        return {"price": price, "diff": diff, "pct": pct, "kst_time": kst_str, "ct_time": ct_str, "ct_utc": ct_utc_label if tstamp else ""}

    except Exception:
        return None


@st.cache_data(ttl=300)
def get_kospi_futures_last() -> dict | None:
    """yfinance ^KS200 (KOSPI200 지수)로 최종 체결 데이터를 가져옵니다 (야간선물 미체결 시 fallback)."""
    try:
        t = yf.Ticker("^KS200")
        info = t.fast_info
        price = float(info.last_price)
        prev = float(info.previous_close)
        if price == 0:
            return None
        diff = price - prev
        pct = (diff / prev * 100) if prev != 0 else 0.0
        return {"price": price, "diff": diff, "pct": pct, "time": "KOSPI200 지수 (yfinance)"}
    except Exception as e:
        print(f"Error fetching KOSPI200 from yfinance: {e}")
        return None


_SIDEBAR_URLS = {
    "🇺🇸 S&P 500": "https://finance.naver.com/world/sise.naver?symbol=SPI@SPX",
    "🇺🇸 NASDAQ": "https://finance.naver.com/world/sise.naver?symbol=NAS@IXIC",
    "🇰🇷 KOSPI": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "🇰🇷 KOSDAQ": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
    "🌙 KOSPI 야간선물": "https://esignal.co.kr/kospi200-futures-night/",
    "💵 USD/KRW": "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW",
    "🥇 Gold": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_GC",
    "🥈 Silver": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_SI",
    "🥉 Copper": "https://finance.naver.com/marketindex/materialDetail.naver?marketindexCd=CMDT_HG",
    "💰 Bitcoin": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-BTC",
    "💎 Ethereum": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-ETH",
}


def _render_sidebar() -> None:
    if st.sidebar.button("새로고침 (Refresh)"):
        from krx_data import fetch_krx_data  # noqa: PLC0415 — 순환 import 방지
        from us_data import fetch_us_data, get_us_most_active  # noqa: PLC0415
        get_major_indices.clear()
        get_kospi_night_futures.clear()
        get_kospi_futures_last.clear()
        fetch_krx_data.clear()
        fetch_us_data.clear()
        get_us_most_active.clear()
        for key in ("krx_market_df", "krx_time", "us_top_df", "us_time",
                    "krx_market_loaded", "us_market_loaded"):
            st.session_state.pop(key, None)

    st.sidebar.markdown("---")

    data = get_major_indices()

    if not data:
        st.sidebar.caption("지수 데이터 로딩 실패")
        return

    # ── 블록 1: 주요 시장 지수 ─────────────────────────────────────────────────
    with st.sidebar.container(border=True):
        st.subheader("🌍 주요 시장 지수")
        st.caption(f"기준: {now_kst().strftime('%m/%d %H:%M:%S')} (KST)")
        for name, (val, diff, pct) in data.get("indices", {}).items():
            url = _SIDEBAR_URLS.get(name, "#")
            val_fmt = f"{val:,.2f}" + (" 원" if "USD/KRW" in name else "")
            st.markdown(f"<a href='{url}' style='font-size:1.4rem;font-weight:bold;text-decoration:none;'>{name}</a>", unsafe_allow_html=True)
            st.metric(" ", val_fmt, f"{diff:,.2f} ({pct:+.2f}%)", label_visibility="collapsed")

    # ── 블록 2: KOSPI 야간선물 ─────────────────────────────────────────────────
    with st.sidebar.container(border=True):
        night_url = _SIDEBAR_URLS["🌙 KOSPI 야간선물"]
        night = get_kospi_night_futures()
        st.markdown(f"<a href='{night_url}' style='font-size:1.4rem;font-weight:bold;text-decoration:none;'>🌙 KOSPI 야간선물</a>", unsafe_allow_html=True)
        if night:
            kst_t = night.get("kst_time", "")
            ct_t = night.get("ct_time", "")
            ct_utc = night.get("ct_utc", "UTC-6")
            lines = []
            if kst_t:
                lines.append(f"기준(KST) {kst_t} (UTC+9)")
            if ct_t:
                lines.append(f"기준(CT) {ct_t} ({ct_utc})")
            st.caption("\n".join(lines) if lines else "")
            pct_sign = "+" if night["pct"] >= 0 else ""
            diff_sign = "+" if night["diff"] >= 0 else ""
            st.metric(
                " ",
                f"{night['price']:,.2f}",
                f"{diff_sign}{night['diff']:,.2f} ({pct_sign}{night['pct']:.2f}%)",
                label_visibility="collapsed",
            )
        else:
            fallback = get_kospi_futures_last()
            if fallback:
                fb_time = fallback.get("time", "")
                st.caption(f"야간장 미체결 · 최종 선물 데이터 ({fb_time})" if fb_time else "야간장 미체결 · 최종 선물 데이터")
                pct_sign = "+" if fallback["pct"] >= 0 else ""
                diff_sign = "+" if fallback["diff"] >= 0 else ""
                st.metric(
                    " ",
                    f"{fallback['price']:,.2f}",
                    f"{diff_sign}{fallback['diff']:,.2f} ({pct_sign}{fallback['pct']:.2f}%)",
                    label_visibility="collapsed",
                )
            else:
                st.caption("데이터 없음")

    # ── 블록 3: 원자재 & 코인 ──────────────────────────────────────────────────
    with st.sidebar.container(border=True):
        st.subheader("💎 원자재 & 코인")
        for name, (usd, diff, pct, krw, unit) in data.get("commodities", {}).items():
            label = f"{name} {unit}".strip()
            url = _SIDEBAR_URLS.get(name, "#")
            st.markdown(f"<a href='{url}' style='font-size:1.4rem;font-weight:bold;text-decoration:none;'>{label}</a>", unsafe_allow_html=True)
            st.metric(" ", f"${usd:,.2f}", f"{pct:+.2f}%", label_visibility="collapsed")
            st.markdown(
                f"<div style='color:gray;font-size:1.1em;margin-top:-10px;margin-bottom:10px;'>약 {krw:,.0f} 원</div>",
                unsafe_allow_html=True,
            )

    st.sidebar.markdown("---")
    with st.sidebar.expander("⚙️ KRX 세션 (쿠키) 관리", expanded=False):
        st.write("KRX 데이터 조회가 안 될 경우 쿠키를 갱신하세요.")
        if st.button("🚀 로컬 브라우저에서 쿠키 자동 추출", help="Antigravity 브라우저가 data.krx.co.kr에 로그인된 상태여야 합니다."):
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



_render_sidebar()

# ─── Title & Tabs ─────────────────────────────────────────────────────────────
_APP_VERSION = "v3.1"

_CHANGELOG = {
    "v3.1": [
        "KRX+NXT 현황 체결시간/조회시간 초 단위 표시",
        "야간선물 KST/CT 이중 시간 표시 (DST 자동 판별)",
        "yfinance 속도 제한 대응 (지수/원자재 분리 다운로드)",
    ],
    "v3.0": [
        "NXT 전 종목 5분봉 스냅샷 → Google Sheets 자동 저장 (28일 보관)",
        "과거 NXT 장외시간 데이터를 KRX+NXT 분석에 자동 보충",
        "Claude (Opus) 전용 프롬프트 추가 (XML 태그, 시나리오 분석, 확신도)",
        "수동 프롬프트 UI 3열 (ChatGPT / Gemini / Claude)",
        "월봉 리샘플 미래 날짜(3/31) 버그 수정",
    ],
    "v2.3": [
        "NXT 캔들을 장외시간 별도 바로 추가",
        "NXT 시가/고가/저가/시간 데이터 확장",
        "인트라데이 분봉 기간 조정 (60m=4주, 30m=2주, 15m=1주, 5m=3일, 1m=1일)",
    ],
    "v2.2": [
        "하이브리드 인트라데이: yfinance 과거 + KIS 당일 실시간",
        "yfinance interval → pandas freq 매핑 버그 수정",
        "미래/장외 시간 데이터 필터링 강화",
    ],
    "v2.1": [
        "실시간 현재가 반영 (KIS API) — 일봉 포함 모든 분석",
        "eSignal socket.io 복원 (KOSPI 야간선물)",
        "KOSPI200 yfinance 폴백",
    ],
    "v2.0": [
        "모바일 반응형 CSS 최적화",
        "Material Symbols 아이콘 오버플로 수정",
        "DataFrame 숫자 포맷 에러 수정",
    ],
    "v1.0": [
        "KRX/US 주식 기술적 분석 기본 기능",
        "Gemini AI 자동 분석 리포트",
        "ChatGPT/Gemini 수동 프롬프트 생성",
        "멀티 타임프레임 (일/주/월/연봉) 통합 분석",
    ],
}

_title_col, _ver_col = st.columns([8, 1])
with _title_col:
    st.title(f"📈 AI 주식 기술적 분석 ({_APP_VERSION})")
with _ver_col:
    st.write("")  # 세로 정렬 여백
    if st.button("📋", key="btn_changelog", help="업데이트 내역 보기"):
        st.session_state["show_changelog"] = True

if st.session_state.get("show_changelog", False):
    @st.dialog(f"업데이트 내역")
    def _show_changelog():
        for ver, changes in _CHANGELOG.items():
            st.markdown(f"### {ver}")
            for c in changes:
                st.markdown(f"- {c}")
            st.divider()
        if st.button("닫기", key="btn_close_changelog", use_container_width=True):
            st.session_state["show_changelog"] = False
            st.rerun()
    _show_changelog()

tab_kr_indie, tab_us_indie, tab_kr_market, tab_us_market = st.tabs([
    "KR 국내 주식 개별 분석",
    "US 해외 주식 개별 분석",
    "🇰🇷 국내 주식 (KRX)",
    "🇺🇸 해외 주식 (US)"
])


# ─── Shared UI Components ─────────────────────────────────────────────────────

# ─── Real-Time Chart (TradingView Lightweight Charts) ─────────────────────────

_LTWC_JS = "https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"


def _bars_to_js(bars: list) -> str:
    """OHLCV bar list를 TradingView Lightweight Charts JS 배열 문자열로 변환합니다."""
    return json.dumps(bars)


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_yf_1m(ticker_yf: str) -> list:
    """yfinance로 1분봉 데이터를 가져와서 TradingView Lightweight 형식으로 반환합니다."""
    df = yf.download(ticker_yf, period="1d", interval="1m", progress=False)
    if df.empty:
        return []
    # MultiIndex 평탄화
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # timezone KST
    if df.index.tzinfo is not None:
        df.index = df.index.tz_convert("Asia/Seoul").tz_localize(None)
    bars = []
    for ts, row in df.iterrows():
        epoch = int(ts.timestamp())
        bars.append({
            "time": epoch,
            "open": round(float(row.get("Open", 0)), 4),
            "high": round(float(row.get("High", 0)), 4),
            "low": round(float(row.get("Low", 0)), 4),
            "close": round(float(row.get("Close", 0)), 4),
        })
    return bars


def _render_ltwc_chart(bars: list, ticker: str, is_realtime: bool = False, currency: str = "KRW") -> None:
    """TradingView Lightweight Charts로 캨들스틱 차트를 렌더링합니다."""
    bars_json = _bars_to_js(bars)
    price_format = '{type: "price", precision: 0, minMove: 1}' if currency == "KRW" else '{type: "price", precision: 2, minMove: 0.01}'
    badge = (
        '<span style="background:#00c853;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700;">'
        '📡 LIVE</span>'
        if is_realtime else
        '<span style="background:#1565c0;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700;">'
        '⏰ 30초 polling</span>'
    )
    html = f"""
    <!DOCTYPE html><html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="{_LTWC_JS}"></script>
    <style>
      body{{margin:0;background:#131722;color:#d1d4dc;font-family:sans-serif;}}
      #chart-header{{display:flex;align-items:center;gap:8px;padding:6px 10px;
                     background:#1e2230;border-bottom:1px solid #2a2d3a;flex-wrap:wrap;}}
      #chart-header .ticker{{font-size:14px;font-weight:700;color:#ffffff;}}
      #chart-header .ohlcv{{font-size:12px;color:#848e9c;}}
      #chart{{width:100%;}}
      @media (max-width: 480px) {{
        #chart-header .ticker{{font-size:12px;}}
        #chart-header .ohlcv{{font-size:10px;}}
      }}
    </style></head><body>
    <div id="chart-header">
      <span class="ticker">{ticker} 1분봉</span>
      {badge}
      <span class="ohlcv" id="ohlcv"></span>
    </div>
    <div id="chart"></div>
    <script>
    (function(){{
      const bars = {bars_json};
      var chartH = window.innerWidth < 480 ? 260 : (window.innerWidth < 768 ? 300 : 360);
      const el = document.getElementById('chart');
      el.style.height = chartH + 'px';
      const chart = LightweightCharts.createChart(el, {{
        layout: {{background:{{color:'#131722'}},textColor:'#d1d4dc'}},
        grid: {{vertLines:{{color:'#2a2d3a'}},horzLines:{{color:'#2a2d3a'}}}},
        crosshair: {{mode: LightweightCharts.CrosshairMode.Normal}},
        rightPriceScale: {{borderColor:'#2a2d3a'}},
        timeScale: {{borderColor:'#2a2d3a', timeVisible:true, secondsVisible:false}},
        width: el.offsetWidth,
        height: chartH,
      }});
      const series = chart.addCandlestickSeries({{
        upColor:'#26a69a', downColor:'#ef5350',
        borderUpColor:'#26a69a', borderDownColor:'#ef5350',
        wickUpColor:'#26a69a', wickDownColor:'#ef5350',
        priceFormat: {price_format},
      }});
      if(bars.length > 0) {{
        series.setData(bars);
        chart.timeScale().fitContent();
        const last = bars[bars.length-1];
        document.getElementById('ohlcv').textContent =
          'O:'+last.open+' H:'+last.high+' L:'+last.low+' C:'+last.close;
      }}
      chart.subscribeCrosshairMove(function(param) {{
        if(param.time && param.seriesData.size > 0) {{
          const d = param.seriesData.get(series);
          if(d) document.getElementById('ohlcv').textContent =
            'O:'+d.open+' H:'+d.high+' L:'+d.low+' C:'+d.close;
        }}
      }});
      window.addEventListener('resize', function(){{
        chartH = window.innerWidth < 480 ? 260 : (window.innerWidth < 768 ? 300 : 360);
        chart.resize(el.offsetWidth, chartH);
      }});
    }})();
    </script></body></html>
    """
    components.html(html, height=420, scrolling=False)


@st.fragment
def render_realtime_chart(ticker: str, currency: str = "KRW", key_prefix: str = "rt") -> None:
    """1분봉 실시간 차트 섹션을 렌더링합니다.

    - 한투 API 키 없으면: yfinance 30초 polling
    - 한투 API 키 있으면: WebSocket 실시간 수신
    """
    st.divider()
    st.subheader("📡 실시간 1분봉 차트")

    running_key = f"{key_prefix}_{ticker}_rt_running"
    interval_key = f"{key_prefix}_{ticker}_rt_interval"

    refresh_sec = st.session_state.get(interval_key, 30)
    if not st.session_state.get(running_key):
        if st.button("▶️ 실시간 차트 시작", key=f"{key_prefix}_{ticker}_start", type="primary", use_container_width=True):
            st.session_state[running_key] = True
            st.rerun(scope="fragment")
    else:
        col_interval, col_stop = st.columns([3, 1])
        with col_interval:
            refresh_sec = st.select_slider(
                "🔄 업데이트 주기 (초)",
                options=[10, 15, 20, 30, 60],
                value=refresh_sec,
                key=interval_key,
            )
        with col_stop:
            if st.button("⏹️ 중지", key=f"{key_prefix}_{ticker}_stop", use_container_width=True):
                st.session_state[running_key] = False
                st.rerun(scope="fragment")

    if not st.session_state.get(running_key):
        st.caption("▶ 시작 버튼을 누르면 1분봉 데이터를 실시간으로 불러옵니다.")
        return

    # ── 한투 WebSocket 모드 (API 키 있을 때)
    kis = get_kis_client(st.session_state)
    is_realtime = False
    bars: list = []

    if kis:
        kis.subscribe(ticker)
        bars = kis.get_bars(ticker)
        is_realtime = kis.is_connected
        status = "🟢 WebSocket 연결됨" if is_realtime else "🟡 WebSocket 연결 중..."
        st.caption(status)
    
    # ── yfinance polling 모드 (bars가 비어 있으면 항상 실행, 한투도 초기 히스토리 보완용)
    if not bars:
        # yfinance ticker 스타일 변환: 005930 → 005930.KS, AAPL → AAPL
        if ticker.isdigit() or (len(ticker) == 6 and ticker[:3].isdigit()):
            yf_ticker = ticker + ".KS"
        else:
            yf_ticker = ticker
        
        with st.spinner("한투 데이터 불러오는 중..."):
            bars = _fetch_yf_1m(yf_ticker)

    if not bars:
        st.warning("현재 시세 데이터를 가져올 수 없습니다. (장 휴장일이거나 지원하지 않는 종목)")
    else:
        st.caption(f"마지막 업데이트: {now_kst().strftime('%H:%M:%S')} KST | {len(bars)}개 봉")
        _render_ltwc_chart(bars, ticker, is_realtime=is_realtime, currency=currency)

    # ── 자동 리프레시
    time.sleep(refresh_sec)
    st.rerun(scope="fragment")

def render_copy_buttons(gpt_prompt: str, gem_prompt: str, suffix: str, claude_prompt: str = "") -> None:
    st.caption("🚀 버튼 클릭 한 번으로 프롬프트 복사 + AI 채팅 열기!")

    def _copy_btn(label: str, text: str, url: str, bg: str, btn_id: str) -> str:
        t_json = json.dumps(text)
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

    lb1, lb2, lb3 = st.columns(3)
    with lb1:
        components.html(_copy_btn("📋 ChatGPT 복사+열기", gpt_prompt, "https://chatgpt.com/", "#10a37f", f"bgpt_{suffix}"), height=50)
    with lb2:
        components.html(_copy_btn("📋 Gemini 복사+열기", gem_prompt, "https://gemini.google.com/", "#1a73e8", f"bgem_{suffix}"), height=50)
    with lb3:
        _cl_text = claude_prompt if claude_prompt else gpt_prompt
        components.html(_copy_btn("📋 Claude 복사+열기", _cl_text, "https://claude.ai/", "#d97706", f"bcld_{suffix}"), height=50)


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
    cld_p = generate_claude_prompt(ticker, name, market, currency, interval_label, display_df, [], holding_status, avg_price, start_dt_str, end_dt_str)

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
    render_copy_buttons(gpt_p, gem_p, f"single_{ticker}_{key_suffix}", claude_prompt=cld_p)
    st.info("아래 코드를 복사하여 AI 서비스에 직접 붙여넣으셔도 됩니다.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        st.code(gpt_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        st.code(gem_p, language=None)
    with c3:
        st.markdown("### 🟠 Claude (Opus) 용")
        st.code(cld_p, language=None)


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
    # Daily 또는 인트라데이 중 첫 번째 유효 DF를 기준으로 기간 표시
    _daily_df = dfs.get("Daily")
    _ref_df = _daily_df if _daily_df is not None and not _daily_df.empty else next((v for v in dfs.values() if not v.empty), pd.DataFrame())
    
    if not _ref_df.empty:
        start_dt_str = _ref_df.index.min().strftime("%Y-%m-%d %H:%M")
        end_dt_str   = _ref_df.index.max().strftime("%Y-%m-%d %H:%M")

    # 각 타임프레임 데이터테이블 표시
    _LABEL_MAP = {"Daily": "일봉", "Weekly": "주봉", "Monthly": "월봉", "Yearly": "연봉",
                  "60min": "60분봉", "15min": "15분봉", "5min": "5분봉", "1min": "1분봉"}
    for _tf_key, _tf_df in dfs.items():
        if not _tf_df.empty:
            _lbl = _LABEL_MAP.get(_tf_key, _tf_key)
            with st.expander(f"📋 {_lbl} 데이터 ({len(_tf_df)}개)", expanded=False):
                _numeric_cols = _tf_df.select_dtypes(include="number").columns.tolist()
                st.dataframe(_tf_df.sort_index(ascending=False).style.format("{:,.2f}", subset=_numeric_cols), height=250)

    st.subheader("🤖 AI 종합 분석 리포트 (Multi-Timeframe)")
    try:
        gemini_api_key = st.secrets["gemini"]["api_key"]
    except Exception:
        gemini_api_key = None

    gpt_multi_p = generate_multi_timeframe_chatgpt_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
    gem_multi_p = generate_multi_timeframe_gemini_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)
    cld_multi_p = generate_multi_timeframe_claude_prompt(code, name, market, currency, dfs, news_list=news, holding_status=holding_status, avg_price=avg_price, start_dt_str=start_dt_str, end_dt_str=end_dt_str)

    if gemini_api_key:
        if st.button("🤖 Gemini AI 자동 분석 시작 (Multi-Timeframe)", key=f"btn_gemini_multi_{prefix}_{code}"):
            with st.spinner("멀티 타임프레임 분석 중..."):
                st.markdown(get_gemini_response(gem_multi_p, gemini_api_key))
    else:
        st.warning("⚠️ Gemini API 키가 설정되지 않았습니다.")
        st.code('[gemini]\napi_key = "YOUR_GEMINI_API_KEY"', language="toml")

    st.divider()
    st.subheader("📋 수동 종합 분석용 프롬프트 (Backup)")
    render_copy_buttons(gpt_multi_p, gem_multi_p, f"multi_{code}", claude_prompt=cld_multi_p)
    st.info("아래 코드를 복사하여 AI 서비스에 직접 붙여넣으셔도 됩니다.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🟢 ChatGPT Plus 용")
        st.code(gpt_multi_p, language=None)
    with c2:
        st.markdown("### 🔵 Gemini (Google One) 용")
        st.code(gem_multi_p, language=None)
    with c3:
        st.markdown("### 🟠 Claude (Opus) 용")
        st.code(cld_multi_p, language=None)


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

    st.success(f"{period_str}의 분석기간 ({start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}), {len(df)}개 데이터")

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
    _num_cols = display_df.select_dtypes(include="number").columns.tolist()
    st.dataframe(display_df.style.format("{:,.2f}", subset=_num_cols), height=300, width="stretch")

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
    # 1. 분석간격 (+기간 직접 설정)
    st.pills(
        "분석간격",
        ["일/주/월/연봉 종합분석", "시간/분봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)",
         "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"],
        default="일/주/월/연봉 종합분석",
        selection_mode="single",
        key="kr_int",
    )
    interval_kr_sel = st.session_state.get("kr_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    date_selector_fragment("kr", default_end - timedelta(days=365), default_end, interval_kr_sel)

    # 2. 데이터 항목 선택
    extra_opts = ["기본 시세 (OHLCV)", "기술적 지표 (Indicators)", "펀더멘털 (Fundamental)", "수급 (Investor)", "시가총액 (Market Cap)"]
    st.multiselect("데이터 항목 선택 (Data Selection)", extra_opts, default=extra_opts, key="kr_data_sel")

    # 3. 종목 선택
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

    # 4. 최근 검색
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


@st.fragment
def render_us_inputs_fragment(us_sorted_names, us_name_to_ticker, default_idx):
    # 1. 분석간격 (+기간 직접 설정)
    st.pills(
        "데이터 간격 (Interval)",
        ["일/주/월/연봉 종합분석", "시간/분봉 종합분석", "일봉 (Daily)", "주봉 (Weekly)", "월봉 (Monthly)", "연봉 (Yearly)",
         "1시간 (60 Minute)", "30분 (30 Minute)", "10분 (10 Minute)", "5분 (5 Minute)", "3분 (3 Minute)", "1분 (1 Minute)"],
        default="일/주/월/연봉 종합분석",
        selection_mode="single",
        key="us_int",
    )
    interval_us_sel = st.session_state.get("us_int", "일/주/월/연봉 종합분석")
    default_end = datetime.today()
    date_selector_fragment("us", default_end - timedelta(days=365), default_end, interval_us_sel)

    # 3. 종목 선택
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

    # 4. 최근 검색
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


# ─── Multi-Timeframe Helper ───────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner="멀티 타임프레임 데이터 준비 중...")
def _get_multi_timeframe(code: str, df_daily: pd.DataFrame):
    d_cutoff = df_daily.index.max() - timedelta(days=365)
    # 지표를 원본 전체 데이터에 먼저 계산한 후, 필요한 기간(1년)만 잘라냅니다.
    df_d = stamp_today_current_time(calculate_indicators(df_daily.sort_index()).loc[d_cutoff:])

    w_cutoff = df_daily.index.max() - timedelta(days=3650)
    # 주봉도 전체로 리샘플링 후 계산하고 10년치만 잘라냅니다.
    df_w = stamp_today_current_time(calculate_indicators(resample_ohlcv(df_daily, "W")).loc[w_cutoff:])
    df_m = stamp_today_current_time(calculate_indicators(resample_ohlcv(df_daily, "ME")))
    df_y = stamp_today_current_time(calculate_indicators(resample_ohlcv(df_daily, "YE")))

    return df_d, df_w, df_m, df_y


@st.cache_data(ttl=120, show_spinner="멀티 분봉 데이터 준비 중...")
def _get_multi_intraday_timeframe(code: str, df_1m: pd.DataFrame, _cache_date: str = "",
                                   nxt_price: float = 0.0, nxt_vol: float = 0.0,
                                   nxt_open: float = 0.0, nxt_high: float = 0.0,
                                   nxt_low: float = 0.0, nxt_time: str = ""):
    """각 분봉별로 yfinance에서 최대 기간 데이터를 직접 수집하고, 당일은 KIS 1분봉으로 보강합니다."""
    import yfinance as yf
    from kis_api import _fetch_kis_today_minutes

    kst_now = datetime.now(tz=timezone(timedelta(hours=9))).replace(tzinfo=None)
    today_str = kst_now.strftime("%Y-%m-%d")
    kis_today = _fetch_kis_today_minutes(code)

    # yfinance 티커 결정 (KOSPI .KS / KOSDAQ .KQ)
    ticker_yf = f"{code}.KS"
    try:
        _test = yf.Ticker(ticker_yf).history(period="1d", interval="1d")
        if _test.empty:
            ticker_yf = f"{code}.KQ"
    except Exception:
        ticker_yf = f"{code}.KQ"

    def _fetch_yf_intraday(interval: str, period: str) -> pd.DataFrame:
        """yfinance에서 특정 분봉 데이터를 가져오고 당일 KIS 데이터로 보강합니다."""
        try:
            yf_df = yf.Ticker(ticker_yf).history(period=period, interval=interval)
        except Exception:
            yf_df = pd.DataFrame()

        if not yf_df.empty:
            if yf_df.index.tz is not None:
                yf_df.index = yf_df.index.tz_convert("Asia/Seoul").tz_localize(None)
            yf_df = yf_df[["Open", "High", "Low", "Close", "Volume"]]
            # 미래 데이터 제거 + 장 시간 외 이상 데이터 제거 + 당일 yfinance 제거
            yf_df = yf_df[yf_df.index <= kst_now]
            yf_df = yf_df[(yf_df.index.hour >= 9) & (yf_df.index.hour < 16)]
            yf_past = yf_df[yf_df.index.normalize() < pd.Timestamp(today_str)]
        else:
            yf_past = pd.DataFrame()

        # 당일 데이터: KIS 1분봉을 해당 간격으로 리샘플링
        # yfinance interval("60m"등)은 pandas resample freq와 다름 → 변환 필요
        _YF_TO_PANDAS_FREQ = {"60m": "60min", "30m": "30min", "15m": "15min", "5m": "5min", "1m": "1min"}
        pandas_freq = _YF_TO_PANDAS_FREQ.get(interval, interval)
        if not kis_today.empty:
            kis_resampled = resample_ohlcv(kis_today, pandas_freq) if interval != "1m" else kis_today.copy()
        else:
            kis_resampled = pd.DataFrame()

        parts = [df for df in [yf_past, kis_resampled] if not df.empty]
        if not parts:
            return pd.DataFrame()
        merged = pd.concat(parts).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        # 최종 안전장치: 현재 시각 이후 & 장외 시간 제거
        merged = merged[(merged.index <= kst_now) & (merged.index.hour >= 9) & (merged.index.hour < 16)]
        return merged

    def _apply_nxt(df: pd.DataFrame) -> pd.DataFrame:
        """KRX 장외시간에 NXT 데이터를 별도 캔들로 추가합니다.

        1) Google Sheets에 저장된 과거 NXT 10분봉을 날짜별로 장외 시간에 보충
        2) 당일은 실시간 NXT 스냅샷 사용
        """
        if df.empty:
            return df

        # ── 1) 과거 NXT 데이터 (Google Sheets) ──
        try:
            from nxt_store import load_nxt_history
            nxt_hist = load_nxt_history(code=code, days=28)
            if not nxt_hist.empty:
                # 장외 시간 NXT 캔들만: 16:00~08:59
                nxt_hist = nxt_hist[
                    (nxt_hist["datetime"].dt.hour >= 16) | (nxt_hist["datetime"].dt.hour < 9)
                ]
                # 당일 제외 (당일은 실시간으로 처리)
                nxt_hist = nxt_hist[nxt_hist["datetime"].dt.date < kst_now.date()]
                if not nxt_hist.empty:
                    nxt_rows = pd.DataFrame({
                        "Open": nxt_hist["open"].values,
                        "High": nxt_hist["high"].values,
                        "Low": nxt_hist["low"].values,
                        "Close": nxt_hist["close"].values,
                        "Volume": nxt_hist["volume"].values,
                    }, index=pd.DatetimeIndex(nxt_hist["datetime"].values))
                    # 거래량 0인 행 제거
                    nxt_rows = nxt_rows[nxt_rows["Volume"] > 0]
                    if not nxt_rows.empty:
                        df = pd.concat([df, nxt_rows]).sort_index()
                        df = df[~df.index.duplicated(keep="last")]
        except Exception as e:
            print(f"[_apply_nxt] 과거 NXT 로드 오류: {e}")

        # ── 2) 당일 실시간 NXT ──
        if nxt_price <= 0:
            return df
        last = df.index[-1]
        after_hours = kst_now.hour < 9 or kst_now.hour > 15 or (kst_now.hour == 15 and kst_now.minute >= 30)
        if after_hours:
            nxt_ts = kst_now.replace(second=0, microsecond=0)
            if nxt_time and len(nxt_time) >= 4:
                try:
                    nxt_ts = kst_now.replace(hour=int(nxt_time[:2]), minute=int(nxt_time[2:4]), second=0, microsecond=0)
                except (ValueError, IndexError):
                    pass
            if nxt_ts <= last:
                nxt_ts = last + timedelta(minutes=1)
            new_row = pd.DataFrame({
                "Open": [nxt_open if nxt_open > 0 else nxt_price],
                "High": [nxt_high if nxt_high > 0 else nxt_price],
                "Low": [nxt_low if nxt_low > 0 else nxt_price],
                "Close": [nxt_price],
                "Volume": [nxt_vol],
            }, index=[nxt_ts])
            df = pd.concat([df, new_row])
        else:
            if nxt_vol > 0:
                df.at[last, "Volume"] = float(df.at[last, "Volume"]) + nxt_vol
        return df

    # 각 분봉별 기간: 60분=4주, 30분=2주, 15분=1주, 5분=3일, 1분=1일
    df_60 = calculate_indicators(_apply_nxt(_fetch_yf_intraday("60m", "28d")))   # 4주
    df_30 = calculate_indicators(_apply_nxt(_fetch_yf_intraday("30m", "14d")))   # 2주
    df_15 = calculate_indicators(_apply_nxt(_fetch_yf_intraday("15m", "7d")))    # 1주
    df_5 = calculate_indicators(_apply_nxt(_fetch_yf_intraday("5m", "3d")))      # 3일

    # 1분봉: 1일 (KIS 당일 실시간만)
    df_1_raw = kis_today.copy() if not kis_today.empty else df_1m.sort_index()
    df_1 = calculate_indicators(_apply_nxt(df_1_raw))

    return df_60, df_30, df_15, df_5, df_1


def _push_recent(key: str, value: str, storage_key: str) -> None:
    lst = st.session_state.setdefault(key, [])
    if value in lst:
        lst.remove(value)
    lst.insert(0, value)
    st.session_state[key] = lst[:10]
    localS.setItem(storage_key, st.session_state[key])


# ─── KRX Tabs ─────────────────────────────────────────────────────────────────

# Ticker mapping — 로컈 JSON 캐시에서 즉시 로딩, 백그라운드에서 FDR 업데이트
ticker_to_name = get_krx_mapping_instant()  # 섭간 실행 (로컈 JSON)
name_to_ticker, sorted_names = build_name_to_ticker(ticker_to_name)

# 백그라운드에서 FDR 목록 업데이트 (캐시 만료된 경우만)
def _refresh_mapping_bg():
    _cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krx_mapping_cache.json")
    try:
        if os.path.exists(_cache) and (time.time() - os.path.getmtime(_cache)) < 86400:
            return  # 24시간 이내면 갱신 불필요
        get_krx_mapping()  # @st.cache_data 업데이트
    except Exception:
        pass

concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_refresh_mapping_bg)

@st.fragment
def _render_krx_market_tab(name_to_ticker_map: dict) -> None:
    """KRX 현황 탭 — 버튼을 눈러야 무거운 랜킹 데이터를 로드합니다."""
    today_str = today_kst().strftime("%Y%m%d")
    DISPLAY_COLS = ["종목명", "종가", "시가", "고가", "저가", "52주최고", "등락률", "거래량", "거래대금", "is_breakout"]
    NUMERIC_COLS = ["종가", "시가", "고가", "저가", "거래량", "거래대금", "52주최고"]

    tab_krx, tab_nxt = st.tabs(["KRX 단독", "KRX + NXT 통합"])

    with tab_krx:
        if not st.session_state.get("krx_market_loaded"):
            st.info("📊 버튼을 눐러 국내 주식 시장 현황을 불러오세요.")
            if st.button("📊 KRX 현황 불러오기", type="primary", key="btn_load_krx_market"):
                st.session_state["krx_market_loaded"] = True
                st.rerun(fragment=True)
        else:
            krx_time_str = now_kst().strftime("%m/%d %H:%M")
            st.session_state["krx_time"] = krx_time_str
            st.subheader(f"🔥 오늘의 거래량 TOP 10 ({krx_time_str})")
            try:
                render_krx_ranking(today_str, krx_time_str, name_to_ticker_map, NUMERIC_COLS, DISPLAY_COLS)
            except Exception as e:
                st.warning(f"랜킹 데이터를 가져오는데 실패했습니다: {e}\n\n```\n{traceback.format_exc()}\n```")

    with tab_nxt:
        if not st.session_state.get("krx_nxt_market_loaded"):
            st.info("📊 KRX와 넥스트레이드(NXT)를 통합한 시장 현황 데이터를 불러옵니다.")
            st.caption("⚡ NXT는 대체거래소(넥스트레이드)입니다. NXT 거래시간: 오전 8시 ~ 오후 8시 (20분 지연)")
            if st.button("📊 KRX+NXT 통합 현황 불러오기", type="primary", key="btn_load_krx_nxt_market"):
                st.session_state["krx_nxt_market_loaded"] = True
                st.rerun(fragment=True)
        else:
            krx_time_str = now_kst().strftime("%m/%d %H:%M")
            st.session_state["krx_time"] = krx_time_str
            try:
                render_krx_nxt_ranking(today_str, krx_time_str, name_to_ticker_map)
            except Exception as e:
                st.warning(f"KRX+NXT 랜킹 로드 실패: {e}\n\n```\n{traceback.format_exc()}\n```")


with tab_kr_market:
    st.header("🇰🇷 한국거래소 (KRX) 시장 동향")
    _render_krx_market_tab(name_to_ticker)


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

    if st.button("🚀 분석 실행 (KRX Analysis)", type="primary", use_container_width=True):
        symbol = (
            st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else None)
            if name_to_ticker
            else st.session_state.get("kr_code_input", "005930")
        )
        if not symbol:
            st.warning("종목 또는 코드를 입력/선택해주세요.")
        else:
            st.session_state["run_krx"] = True
            st.session_state["run_krx_nxt"] = False
            _push_recent("recent_kr", symbol, "recent_kr")

    if st.button("🔗 KRX+NXT 통합 분석", type="secondary", use_container_width=True,
                 help="KRX 분석 + 넥스트레이드(NXT) 시세를 함께 확인합니다"):
        symbol = (
            st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else None)
            if name_to_ticker
            else st.session_state.get("kr_code_input", "005930")
        )
        if not symbol:
            st.warning("종목 또는 코드를 입력/선택해주세요.")
        else:
            st.session_state["run_krx"] = True
            st.session_state["run_krx_nxt"] = True
            _push_recent("recent_kr", symbol, "recent_kr")

    if st.session_state.get("run_krx"):
        if name_to_ticker:
            selected_name = st.session_state.get("kr_select_box", sorted_names[default_index] if sorted_names else "")
            kr_code = name_to_ticker.get(selected_name)
        else:
            kr_code = st.session_state.get("kr_code_input", "005930")
            selected_name = kr_code

        with st.spinner("KRX 데이터 가져오는 중..."):
            t0 = time.time()
            # date_selector_fragment 가 datetime.date 를 반환할 수 있으므로 datetime 으로 통일
            if hasattr(start_date_kr, 'hour') is False:
                start_date_kr = datetime.combine(start_date_kr, datetime.min.time())
            if hasattr(end_date_kr, 'hour') is False:
                end_date_kr = datetime.combine(end_date_kr, datetime.min.time())
            if interval_kr_sel == "시간/분봉 종합분석":
                fetch_int_kr = "1분 (1 Minute)"
                # 종합분석은 KIS API 분봉 한계(~8영업일)만큼 자동 수집하므로 날짜 제한 경고 불필요
            else:
                fetch_int_kr = interval_kr_sel
                start_date_kr = clamp_intraday_dates(fetch_int_kr, start_date_kr, end_date_kr)
            s_str = start_date_kr.strftime("%Y%m%d")
            e_str = end_date_kr.strftime("%Y%m%d")
            run_nxt = st.session_state.get("run_krx_nxt", False)
            df_kr, market_name = fetch_krx_data(kr_code, s_str, e_str, fetch_int_kr, tuple(extra_data_sel), include_nxt=run_nxt)

            # ── 실시간 가격 반영: 당일 마지막 캔들을 현재가로 업데이트 ──
            if not df_kr.empty:
                from kis_api import get_current_price
                from krx_data import get_nxt_ranking

                kst_now = datetime.now(tz=timezone(timedelta(hours=9))).replace(tzinfo=None)
                last_idx = df_kr.index[-1]
                is_intraday = fetch_int_kr in [
                    "1분 (1 Minute)", "3분 (3 Minute)", "5분 (5 Minute)",
                    "10분 (10 Minute)", "30분 (30 Minute)", "1시간 (60 Minute)",
                ]

                # KIS 실시간 현재가 조회 (모든 분석에 공통)
                kis_rt = get_current_price(kr_code)
                rt_price = float(kis_rt["price"]) if kis_rt and kis_rt.get("ok") else 0.0

                # NXT 데이터 조회 (KRX+NXT 통합 분석일 때만)
                nxt_vol = 0.0
                nxt_price = 0.0
                nxt_open = 0.0
                nxt_high = 0.0
                nxt_low = 0.0
                nxt_time = ""
                if run_nxt:
                    nxt_df = get_nxt_ranking(rows=200)
                    if not nxt_df.empty and kr_code in nxt_df.index:
                        nxt_row = nxt_df.loc[kr_code]
                        nxt_vol = float(nxt_row.get("NXT거래량", 0))
                        nxt_price = float(nxt_row.get("현재가", 0))
                        nxt_open = float(nxt_row.get("NXT시가", 0))
                        nxt_high = float(nxt_row.get("NXT고가", 0))
                        nxt_low = float(nxt_row.get("NXT저가", 0))
                        nxt_time = str(nxt_row.get("NXT시간", ""))

                # 최종 반영할 가격 결정 (NXT > KIS 우선순위)
                live_price = nxt_price if nxt_price > 0 else rt_price

                if live_price > 0:
                    after_hours = kst_now.hour < 9 or kst_now.hour > 15 or (kst_now.hour == 15 and kst_now.minute >= 30)

                    if is_intraday:
                        current_minute = kst_now.replace(second=0, microsecond=0)
                        if after_hours and current_minute > last_idx:
                            # 장 마감 후 새 캔들 추가
                            new_row = pd.DataFrame({
                                "Open": [live_price], "High": [live_price], "Low": [live_price],
                                "Close": [live_price], "Volume": [nxt_vol],
                            }, index=[current_minute])
                            df_kr = pd.concat([df_kr, new_row])
                        else:
                            # 마지막 캔들을 현재가로 갱신
                            df_kr.at[last_idx, "Close"] = live_price
                            df_kr.at[last_idx, "High"] = max(float(df_kr.at[last_idx, "High"]), live_price)
                            df_kr.at[last_idx, "Low"] = min(float(df_kr.at[last_idx, "Low"]), live_price)
                            if nxt_vol > 0:
                                df_kr.at[last_idx, "Volume"] += nxt_vol
                    else:
                        # 일봉 이상: 당일 캔들이 있으면 현재가로 갱신
                        today = kst_now.date()
                        if last_idx.date() == today or (last_idx.date() >= today - timedelta(days=3)):
                            df_kr.at[last_idx, "Close"] = live_price
                            df_kr.at[last_idx, "High"] = max(float(df_kr.at[last_idx, "High"]), live_price)
                            df_kr.at[last_idx, "Low"] = min(float(df_kr.at[last_idx, "Low"]), live_price)
                            if nxt_vol > 0:
                                df_kr.at[last_idx, "Volume"] += nxt_vol

        try:
            if df_kr.empty:
                st.error("데이터가 없습니다. 종목 코드를 확인해주세요.")
            elif interval_kr_sel == "일/주/월/연봉 종합분석":
                elapsed = time.time() - t0
                st.success(f"'{selected_name}' 전체 구간(일/주/월/년) 입체 분석 (⏱️ {elapsed:.2f}초)")
                
                if st.session_state.get("run_krx_nxt"):
                    render_stock_nxt_card(kr_code, selected_name)

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
            elif interval_kr_sel == "시간/분봉 종합분석":
                elapsed = time.time() - t0
                st.success(f"'{selected_name}' 인트라데이 종합구간(60분/30분/15분/5분/1분) 입체 분석 (⏱️ {elapsed:.2f}초)")
                if st.session_state.get("run_krx_nxt"):
                    st.caption("✅ 과거 분봉: yfinance / 당일 실시간: KIS Open API (무지연) / NXT: 장외시간 당일만 반영")
                    render_stock_nxt_card(kr_code, selected_name)
                else:
                    st.caption("✅ 과거 분봉: yfinance / 당일 실시간: KIS Open API (무지연)")

                _today_cache = datetime.now(tz=timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H")
                df_60, df_30, df_15, df_5, df_1 = _get_multi_intraday_timeframe(
                    kr_code, df_kr, _cache_date=_today_cache,
                    nxt_price=nxt_price if run_nxt else 0.0,
                    nxt_vol=nxt_vol if run_nxt else 0.0,
                    nxt_open=nxt_open if run_nxt else 0.0,
                    nxt_high=nxt_high if run_nxt else 0.0,
                    nxt_low=nxt_low if run_nxt else 0.0,
                    nxt_time=nxt_time if run_nxt else "")
                t1, t2, t3, t4, t5, t6 = st.tabs(["📊 종합 리포트", "🕒 60분봉", "🕒 30분봉", "🕒 15분봉", "🕒 5분봉", "🕒 1분봉"])
                with t1:
                    render_multi_ai_content(kr_code, selected_name, market_name, "KRW", {"60min": df_60, "30min": df_30, "15min": df_15, "5min": df_5, "1min": df_1}, [])
                with t2:
                    run_analysis_and_prompts(df_60, kr_code, selected_name, market_name, "KRW", "60분봉", key_suffix="kr_60m", selected_data=extra_data_sel)
                with t3:
                    run_analysis_and_prompts(df_30, kr_code, selected_name, market_name, "KRW", "30분봉", key_suffix="kr_30m", selected_data=extra_data_sel)
                with t4:
                    run_analysis_and_prompts(df_15, kr_code, selected_name, market_name, "KRW", "15분봉", key_suffix="kr_15m", selected_data=extra_data_sel)
                with t5:
                    run_analysis_and_prompts(df_5, kr_code, selected_name, market_name, "KRW", "5분봉", key_suffix="kr_5m", selected_data=extra_data_sel)
                with t6:
                    run_analysis_and_prompts(df_1, kr_code, selected_name, market_name, "KRW", "1분봉", key_suffix="kr_1m", selected_data=extra_data_sel)
            else:
                _period_codes = {"일봉 (Daily)": "D", "주봉 (Weekly)": "W", "월봉 (Monthly)": "ME", "연봉 (Yearly)": "YE"}
                if interval_kr_sel in _period_codes:
                    p = _period_codes[interval_kr_sel]
                    df_final = df_kr.sort_index() if p == "D" else resample_ohlcv(df_kr, p)
                else:
                    df_final = df_kr.sort_index()
                df_final = stamp_today_current_time(calculate_indicators(df_final))
                elapsed = time.time() - t0
                st.success(f"'{selected_name}' {interval_kr_sel} 분석 (⏱️ {elapsed:.2f}초)")
                
                if st.session_state.get("run_krx_nxt"):
                    render_stock_nxt_card(kr_code, selected_name)

                run_analysis_and_prompts(df_final, kr_code, selected_name, market_name, "KRW", interval_kr_sel, key_suffix="kr_single", selected_data=extra_data_sel)
        except Exception as e:
            st.error(f"오류 발생: {e}\n```\n{traceback.format_exc()}\n```")


# ─── US Tabs ────────────────────────────────────────────────────────────────────

us_ticker_map = get_sp500_mapping()
us_name_to_ticker = {f"{n} ({t})": t for t, n in us_ticker_map.items()}
us_sorted_names = sorted(us_name_to_ticker.keys())

@st.fragment
def _render_us_market_tab() -> None:
    """US 현황 탭 — 버튼을 눌러야 무거운 랭킹 데이터를 로드합니다."""
    if not st.session_state.get("us_market_loaded"):
        st.info("📊 버튼을 눌러 미국 주식 시장 현황을 불러오세요.")
        if st.button("📊 US 현황 불러오기", type="primary", key="btn_load_us_market"):
            st.session_state["us_market_loaded"] = True
            st.rerun(fragment=True)
        return

    us_time_str = now_kst().strftime("%m/%d %H:%M")
    st.session_state["us_time"] = us_time_str
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


with tab_us_market:
    st.header("🇺🇸 미국 주식 (US Stock) 시장 동향")
    _render_us_market_tab()

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

        # TradingView chart — responsive height
        components.html(
            f"""
            <div class="tradingview-widget-container" style="margin-bottom:10px">
              <div id="tv_{us_ticker}" style="width:100%;"></div>
              <script src="https://s3.tradingview.com/tv.js"></script>
              <script>
              (function(){{
                var h = window.innerWidth < 768 ? 480 : (window.innerWidth < 1024 ? 700 : 1180);
                new TradingView.widget({{
                  "width":"100%","height":h,"symbol":"{us_ticker}","interval":"{period_code_us}",
                  "timezone":"Asia/Seoul","theme":"light","style":"1","locale":"kr",
                  "enable_publishing":false,"allow_symbol_change":true,"container_id":"tv_{us_ticker}"
                }});
              }})();
              </script>
            </div>""",
            height=1200,
        )

        with st.spinner("미국 주식 데이터 가져오는 중..."):
            t0 = time.time()
            # date_selector_fragment 가 datetime.date 를 반환할 수 있으므로 datetime 으로 통일
            if hasattr(start_date_us, 'hour') is False:
                start_date_us = datetime.combine(start_date_us, datetime.min.time())
            if hasattr(end_date_us, 'hour') is False:
                end_date_us = datetime.combine(end_date_us, datetime.min.time())
            fetch_int_us = "1분 (1 Minute)" if interval_us_sel == "시간/분봉 종합분석" else interval_us_sel
            start_date_us = clamp_intraday_dates(fetch_int_us, start_date_us, end_date_us)
            df_us = fetch_us_data(us_ticker, start_date_us.strftime("%Y%m%d"), end_date_us.strftime("%Y%m%d"), fetch_int_us)

        if df_us.empty:
            st.error("데이터를 찾을 수 없습니다.")
        elif interval_us_sel == "일/주/월/연봉 종합분석":
            st.success(f"'{us_ticker}' 전체 구간(일/주/월/년) 입체 분석")
            df_d, df_w, df_m, df_y = _get_multi_timeframe(us_ticker, df_us)
            t1, t2, t3, t4, t5 = st.tabs(["📊 종합 리포트", "📅 일봉", "📅 주봉", "📅 월봉", "📅 연봉"])
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
        elif interval_us_sel == "시간/분봉 종합분석":
            st.success(f"'{us_ticker}' 인트라데이 종합구간(60분/30분/15분/5분/1분) 입체 분석")
            st.caption("⚠️ yfinance 데이터는 약 15~20분 지연됩니다. US 주식은 실시간 보정이 제공되지 않습니다.")
            df_60, df_30, df_15, df_5, df_1 = _get_multi_intraday_timeframe(us_ticker, df_us)
            t1, t2, t3, t4, t5, t6 = st.tabs(["📊 종합 리포트", "🕒 60분봉", "🕒 30분봉", "🕒 15분봉", "🕒 5분봉", "🕒 1분봉"])
            name_display = selected_us_name if us_name_to_ticker else us_ticker
            with t1:
                render_multi_ai_content(us_ticker, name_display, "US", "USD", {"60min": df_60, "30min": df_30, "15min": df_15, "5min": df_5, "1min": df_1}, [])
            with t2:
                run_analysis_and_prompts(df_60, us_ticker, name_display, "US", "USD", "60분봉", key_suffix="us_60m")
            with t3:
                run_analysis_and_prompts(df_30, us_ticker, name_display, "US", "USD", "30분봉", key_suffix="us_30m")
            with t4:
                run_analysis_and_prompts(df_15, us_ticker, name_display, "US", "USD", "15분봉", key_suffix="us_15m")
            with t5:
                run_analysis_and_prompts(df_5, us_ticker, name_display, "US", "USD", "5분봉", key_suffix="us_5m")
            with t6:
                run_analysis_and_prompts(df_1, us_ticker, name_display, "US", "USD", "1분봉", key_suffix="us_1m")
        else:
            if interval_us_sel in _period_codes_us:
                p = _period_codes_us[interval_us_sel]
                df_final = df_us.sort_index() if p == "D" else resample_ohlcv(df_us, p)
            else:
                df_final = df_us.sort_index()
            df_final = stamp_today_current_time(calculate_indicators(df_final))
            elapsed = time.time() - t0
            name_display = selected_us_name if us_name_to_ticker else us_ticker
            st.success(f"'{name_display}' {interval_us_sel} 분석 (⏱️ {elapsed:.2f}초)")
            run_analysis_and_prompts(df_final, us_ticker, name_display, "US", "USD", interval_us_sel, key_suffix="us_single")


