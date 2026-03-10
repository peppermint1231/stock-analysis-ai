"""kr_ui.py — KRX UI 렌더링 모듈

가로 캔들 차트, Top 10 랭킹 테이블, 스타일 헬퍼 등 KRX 탭 렌더링 함수를 담당합니다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup


# ─── Style Helpers ────────────────────────────────────────────────────────────

def format_price_change(val) -> str:
    """등락률 값에 CSS 색상을 반환합니다 (상승=red, 하락=blue)."""
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: red"
        elif val < 0:
            return "color: blue"
    return ""


def add_arrow(val) -> str:
    """등락률 값에 부호만 추가합니다."""
    if isinstance(val, (int, float)):
        return f"+{val:,.2f}" if val > 0 else f"{val:,.2f}"
    return str(val)


def color_name(row: pd.Series) -> list[str]:
    """등락률·52주 신고가에 따라 행 스타일 리스트를 반환합니다."""
    styles = [""] * len(row)
    rate_val = row.get("등락률", 0)
    is_breakout = bool(row.get("is_breakout", False))

    color = ""
    if isinstance(rate_val, (int, float)):
        if rate_val > 0:
            color = "color: red"
        elif rate_val < 0:
            color = "color: blue"

    for col in ("종가", "종목명"):
        if col in row.index and color:
            styles[row.index.get_loc(col)] = color

    if is_breakout and "종목명" in row.index:
        idx = row.index.get_loc("종목명")
        styles[idx] = (
            f"{styles[idx]}; background-color: #FFF9C4; color: #D32F2F;"
            " font-weight: bold; border: 2px solid #FFD700"
        )
        if "52주최고" in row.index:
            styles[row.index.get_loc("52주최고")] = "color: #D32F2F; font-weight: bold;"

    return styles


# ─── Investor Data (Naver Finance Scraping) ──────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _get_naver_investor_data(ticker: str) -> dict:
    """Naver Finance frgn.naver에서 기관/외국인 순매수량을 가져옵니다.

    개인 = -(기관 + 외국인), 기타법인 = 0 (Naver에서 미제공)
    """
    def _parse_int(s: str) -> int:
        s = s.replace(",", "").replace("+", "").strip()
        return int(s) if s and s != "-" else 0

    try:
        url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        for table in soup.find_all("table", {"class": "type2"}):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue
                date_text = cells[0].text.strip()
                if len(date_text) != 10 or "." not in date_text:
                    continue
                try:
                    inst_val = _parse_int(cells[5].text)
                    foreign_val = _parse_int(cells[6].text)
                    return {
                        "개인": -(inst_val + foreign_val),
                        "외국인": foreign_val,
                        "기관": inst_val,
                        "기타": 0,
                        "date": date_text,
                    }
                except Exception:
                    continue
    except Exception:
        pass
    return {"개인": 0, "외국인": 0, "기관": 0, "기타": 0, "date": ""}


# ─── Horizontal Candle Chart ──────────────────────────────────────────────────

def _candle_pct(price: float, prev_close: float) -> float:
    return (price - prev_close) / prev_close * 100


def _candle_cap(pct: float, max_pct: float) -> float:
    return max(-max_pct, min(max_pct, pct))


def _candle_x(pct: float, max_pct: float) -> float:
    return (_candle_cap(pct, max_pct) + max_pct) / (max_pct * 2) * 100


def _investor_bar_row(label: str, val: int, baseline: int) -> str:
    """투자자별 순매수 가로 막대 HTML 행을 생성합니다."""
    v_pct = (val / baseline) * 100 if baseline > 0 else 0
    row_color = "#D32F2F" if val > 0 else "#1976D2" if val < 0 else "#495057"
    s = "+" if val > 0 else ""
    bw = min(abs(v_pct) / 2, 50)
    lm = 50 if val > 0 else 50 - bw
    return f"""
<div style="display: flex; align-items: center; justify-content: space-between; height: 28px; margin-bottom: 4px;">
  <div style="width: 40px; text-align: left; color: #495057; font-weight: bold; font-size: 11px; flex-shrink: 0;">{label}</div>
  <div style="flex: 1; position: relative; height: 14px; margin: 0 4px; display: flex; align-items: center; min-width: 0;">
     <div style="position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: #000; z-index: 1;"></div>
     <div style="position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: #000; z-index: 3;"></div>
     <div style="position: absolute; left: {lm}%; width: {bw}%; height: 12px; top: 1px; background: {row_color}; z-index: 2;"></div>
  </div>
  <div style="width: 50px; text-align: right; display: flex; flex-direction: column; justify-content: flex-end; padding-bottom: 1px; flex-shrink: 0;">
     <div style="font-size: 9px; color: #adb5bd; line-height: 1.1; margin-bottom: 1px;">{val:,.0f}</div>
     <div style="color: {row_color}; font-weight: bold; font-size: 11px; line-height: 1.1;">{s}{v_pct:.0f}%</div>
  </div>
</div>
"""


def render_horizontal_candles(df: pd.DataFrame, ticker_map: dict[str, str], max_pct: float = 30.0) -> str:
    """주어진 DataFrame으로 가로 캔들 차트 HTML 문자열을 생성합니다."""
    html = (
        '<style>'
        '.hc-card { flex-wrap: nowrap; }'
        '.hc-grid { font-family: sans-serif; font-size: 14px; margin-top: 10px; margin-bottom: 20px;'
        '  display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }'
        '@media (max-width: 480px) {'
        '  .hc-grid { grid-template-columns: 1fr; gap: 12px; }'
        '  .hc-card { flex-wrap: wrap !important; padding: 12px 10px !important; }'
        '  .hc-investor { flex: 1 1 100% !important; margin-top: 10px !important; }'
        '  .hc-name { font-size: 13px !important; }'
        '  .hc-candle-area { height: 35px !important; }'
        '  .hc-label { font-size: 10px !important; }'
        '}'
        '@media (min-width: 481px) and (max-width: 768px) {'
        '  .hc-grid { grid-template-columns: 1fr; gap: 15px; }'
        '  .hc-card { flex-wrap: wrap !important; }'
        '  .hc-investor { flex: 1 1 100% !important; margin-top: 12px !important; }'
        '}'
        '</style>'
        '<div class="hc-grid">'
    )

    for ticker in df.index:
        try:
            name_in_df = df.loc[ticker, "종목명"] if "종목명" in df.columns else ""
            name = str(name_in_df) if pd.notna(name_in_df) and str(name_in_df).strip() else ticker_map.get(str(ticker), str(ticker))
            if "name=" in name:
                name = name.split("name=")[-1]

            close_p = float(df.loc[ticker, "현재가"])
            open_p = float(df.loc[ticker, "시가"]) if "시가" in df.columns else close_p
            high_p = float(df.loc[ticker, "고가"]) if "고가" in df.columns else close_p
            low_p = float(df.loc[ticker, "저가"]) if "저가" in df.columns else close_p
            c_pct = float(df.loc[ticker, "등락률"])

            prev_close = close_p / (1 + c_pct / 100.0) if c_pct > -100 else close_p
            if prev_close <= 0:
                continue

            o_cap = _candle_cap(_candle_pct(open_p, prev_close), max_pct)
            h_cap = _candle_cap(_candle_pct(high_p, prev_close), max_pct)
            l_cap = _candle_cap(_candle_pct(low_p, prev_close), max_pct)
            c_cap = _candle_cap(c_pct, max_pct)

            x_o = _candle_x(_candle_pct(open_p, prev_close), max_pct)
            x_h = _candle_x(_candle_pct(high_p, prev_close), max_pct)
            x_l = _candle_x(_candle_pct(low_p, prev_close), max_pct)
            x_c = _candle_x(c_pct, max_pct)

            body_left = min(x_o, x_c)
            body_width = max(0.5, abs(x_o - x_c))
            color = "#D32F2F" if c_pct >= 0 else "#1976D2"
            high_align = "0" if x_h < 80 else "-100%"

            inv = _get_naver_investor_data(str(ticker))
            vals = [inv["개인"], inv["외국인"], inv["기관"], inv["기타"]]
            baseline = max(
                sum(v for v in vals if v > 0),
                abs(sum(v for v in vals if v < 0)),
                1,
            )
            investor_rows = "".join(
                _investor_bar_row(label, val, baseline)
                for label, val in zip(("개인", "외국인", "기관", "기타"), vals)
            )

            vol = float(df.loc[ticker, "거래량"]) if "거래량" in df.columns else 0
            vol_html = f'<div style="font-size:12px;color:#868e96;font-weight:normal;">주 {int(vol):,}</div>' if vol > 0 else ""

            o_pct = _candle_pct(open_p, prev_close)
            h_pct = _candle_pct(high_p, prev_close)
            l_pct = _candle_pct(low_p, prev_close)

            html += f"""
<div class="hc-card" style="border:1px solid #e2e8f0;border-radius:10px;padding:14px 12px;background:white;
box-shadow:0 2px 4px rgba(0,0,0,0.05);display:flex;align-items:stretch;gap:12px;flex-wrap:nowrap;">
  <div style="flex:1 1 100px;min-width:0;">
    <div class="hc-name" style="margin-bottom:18px;font-weight:bold;font-size:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
      <div style="word-break:keep-all;line-height:1.3;min-width:0;">
        {name} <span style="font-size:12px;color:gray;font-weight:normal;">
          ({close_p:,.0f}원 <span style="color:{color};">{c_pct:+.2f}%</span>)
        </span>
      </div>
      {vol_html}
    </div>
    <div class="hc-candle-area" style="position:relative;width:100%;height:40px;background-color:#f8f9fa;
      border-radius:4px;border:1px solid #e9ecef;margin-top:8px;">
      <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background-color:#adb5bd;z-index:1;"></div>
      <div style="position:absolute;left:{x_l}%;width:{x_h-x_l}%;top:19px;height:2px;background-color:#495057;z-index:2;"></div>
      <div style="position:absolute;left:{body_left}%;width:{body_width}%;top:8px;height:24px;background-color:{color};border-radius:2px;z-index:3;"></div>
      <div style="position:absolute;left:{x_o}%;top:0;height:40px;border-left:2px dashed #343a40;z-index:4;"></div>
      <div class="hc-label" style="position:absolute;left:{x_o}%;top:-17px;font-size:10px;color:#495057;transform:translateX(-50%);white-space:nowrap;">시 {open_p:,.0f}</div>
      <div style="position:absolute;left:{x_c}%;top:0;height:40px;border-left:2px solid #212529;z-index:5;"></div>
      <div class="hc-label" style="position:absolute;left:{x_c}%;top:43px;font-size:11px;font-weight:bold;color:{color};transform:translateX(-50%);white-space:nowrap;">종 {close_p:,.0f}</div>
      <div class="hc-label" style="position:absolute;left:{x_l}%;top:58px;font-size:10px;color:#6c757d;transform:translateX(-100%);padding-right:4px;text-align:right;line-height:1.2;">저 {low_p:,.0f}<br>({l_pct:+.1f}%)</div>
      <div class="hc-label" style="position:absolute;left:{x_h}%;top:58px;font-size:10px;color:#6c757d;transform:translateX({high_align});padding-left:4px;line-height:1.2;">고 {high_p:,.0f}<br>({h_pct:+.1f}%)</div>
    </div>
  </div>
  <div class="hc-investor" style="flex:0 0 150px;display:flex;flex-direction:column;justify-content:center;font-size:12px;margin-top:4px;min-width:0;">
    {investor_rows}
  </div>
</div>"""
        except Exception:
            pass

    html += "</div>"
    return html


# ─── Top-10 Processing ────────────────────────────────────────────────────────

def process_top_10(df_subset: pd.DataFrame, ticker_map: dict[str, str], base_date_str: str) -> pd.DataFrame:
    """Top 10 DataFrame에 종목명 링크, 52주 고가, 돌파 여부를 추가합니다."""
    df = df_subset.copy()
    price_col = "종가" if "종가" in df.columns else "현재가"

    def _naver_url(t: str) -> str:
        name = (
            str(df_subset.loc[t, "종목명"])
            if "종목명" in df_subset.columns and pd.notna(df_subset.loc[t, "종목명"]) and str(df_subset.loc[t, "종목명"]).strip()
            else ticker_map.get(t, t)
        )
        return f"https://finance.naver.com/item/main.naver?code={t}&name={name}"

    df["종목명"] = [_naver_url(t) for t in df.index]

    high_prices, breakouts = [], []
    start_52 = datetime.today() - timedelta(days=365)

    for ticker in df.index:
        try:
            curr_close = float(df.loc[ticker, price_col])
            hist = fdr.DataReader(ticker, start_52)
            if not hist.empty and "High" in hist.columns:
                prev_high = hist["High"].iloc[:-1].max() if len(hist) > 1 else 0
                high_prices.append(hist["High"].max())
                breakouts.append(bool(prev_high > 0 and curr_close >= prev_high))
            else:
                raise ValueError("empty")
        except Exception:
            high_prices.append(0)
            breakouts.append(False)

    df["52주최고"] = high_prices
    df["is_breakout"] = breakouts

    for col in ("시가", "고가", "저가"):
        if col not in df.columns:
            df[col] = df[price_col]

    return df


# ─── KRX Ranking Fragment ────────────────────────────────────────────────────

def _build_column_config() -> dict:
    return {
        "종목명": st.column_config.LinkColumn(
            "종목명",
            display_text=r"name=([^&]+)",
            help="클릭 시 네이버페이 증권 차트로 이동합니다. 배경색 있는 종목은 52주 신고가",
            max_chars=100,
        ),
        "등락률": st.column_config.TextColumn("등락률"),
        "is_breakout": st.column_config.CheckboxColumn("전고점 돌파", default=False),
        "52주최고": st.column_config.TextColumn("52주최고"),
        "시가": st.column_config.TextColumn("시가"),
        "고가": st.column_config.TextColumn("고가"),
        "저가": st.column_config.TextColumn("저가"),
    }


def _render_table(df: pd.DataFrame, display_cols: list[str], numeric_cols: list[str], toggle_key: str, ticker_to_name: dict[str, str]) -> None:
    """Top 10 테이블 또는 가로 캔들을 렌더링합니다."""
    df_disp = df.copy()
    for col in numeric_cols:
        if col in df_disp.columns:
            df_disp[col] = df_disp[col].apply(lambda x: f"{x:,.0f}")

    avail = [c for c in display_cols if c in df_disp.columns]
    styler = df_disp[avail].style
    if "등락률" in avail:
        styler = styler.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
    styler = styler.apply(color_name, axis=1)

    use_candle = st.toggle("📈 가로 캔들 차트로 보기", key=toggle_key)
    if use_candle:
        components.html(render_horizontal_candles(df, ticker_to_name), height=900, scrolling=True)
    else:
        st.dataframe(styler, column_config=_build_column_config())


@st.fragment
def render_krx_ranking(
    today_str: str,
    krx_time_str: str,
    name_to_ticker_map: dict[str, str],
    numeric_cols: list[str],
    display_cols: list[str],
) -> None:
    """KRX 전 종목 데이터에서 거래량 / 거래대금 Top 10을 렌더링합니다."""
    from krx_data import get_krx_ranking

    ticker_to_name = {v: k for k, v in name_to_ticker_map.items()}
    _ETF_KEYWORDS = ["KODEX", "TIGER", "KBSTAR", "KINDEX", "ACE", "ARIRANG", "KOSEF", "HANARO", "SOL", "TIMEFOLIO", "WOORI", "히어로즈", "마이티", "ETN", "인버스", "레버리지", "스팩", "선물"]

    with st.spinner("KRX에서 오늘의 실시간 시장 데이터를 가져오는 중..."):
        all_df = get_krx_ranking()

    if all_df.empty:
        st.info("장 시작 전이거나 휴장일입니다. (No Data for Ranking)")
        return

    vol_col = "거래량" if "거래량" in all_df.columns else "Volume"
    val_col = "거래대금" if "거래대금" in all_df.columns else None

    exclude_etf = st.toggle("🚫 ETF/ETN 제외 (순수 주식만 랭킹 보기)", value=True, key="krx_exclude_etf")
    if exclude_etf:
        if ticker_to_name:
            all_df = all_df[all_df.index.isin(ticker_to_name.keys())]
        elif "종목명" in all_df.columns:
            all_df = all_df[~all_df["종목명"].str.contains("|".join(_ETF_KEYWORDS), case=False, na=False)]

    top_vol = all_df.sort_values(vol_col, ascending=False).head(10).copy()
    top_vol = process_top_10(top_vol, ticker_to_name, today_str)
    _render_table(top_vol, display_cols, numeric_cols, "toggle_kr_vol", ticker_to_name)

    st.subheader(f"💰 오늘의 거래대금 TOP 10 ({krx_time_str})")
    if val_col:
        top_val = all_df.sort_values(val_col, ascending=False).head(10).copy()
        top_val = process_top_10(top_val, ticker_to_name, today_str)
        _render_table(top_val, display_cols, numeric_cols, "toggle_kr_val", ticker_to_name)
    else:
        st.warning("'거래대금' 컬럼을 찾을 수 없습니다.")


# ─── KRX + NXT Combined Ranking ──────────────────────────────────────────────

def _naver_link(ticker: str, name: str) -> str:
    return f"https://finance.naver.com/item/main.naver?code={ticker}&name={name}"


def _resolve_name(ticker: str, ticker_to_name: dict[str, str], df: pd.DataFrame) -> str:
    """ticker_to_name → df['종목명'] → ticker 순으로 표시 이름을 반환합니다."""
    n = ticker_to_name.get(ticker, "")
    if n:
        return n
    if "종목명" in df.columns and ticker in df.index:
        v = df.loc[ticker, "종목명"]
        if pd.notna(v) and str(v).strip():
            return str(v)
    return ticker


@st.fragment
def render_krx_nxt_ranking(
    today_str: str,
    krx_time_str: str,
    name_to_ticker_map: dict[str, str],
) -> None:
    """KRX와 NXT(넥스트레이드) 데이터를 통합하여 거래량/거래대금 상위 종목을 렌더링합니다."""
    from krx_data import get_krx_ranking, get_nxt_ranking

    ticker_to_name = {v: k for k, v in name_to_ticker_map.items()}
    _ETF_KW = ["KODEX", "TIGER", "KBSTAR", "KINDEX", "ACE", "ARIRANG", "KOSEF", "HANARO", "SOL", "TIMEFOLIO", "ETN", "인버스", "레버리지", "스팩", "선물"]

    with st.spinner("KRX + NXT 통합 시장 데이터를 가져오는 중..."):
        col_krx, col_nxt = st.columns(2)
        with col_krx:
            with st.spinner("KRX 데이터 로딩..."):
                krx_df = get_krx_ranking()
        with col_nxt:
            with st.spinner("NXT(넥스트레이드) 데이터 로딩..."):
                nxt_df = get_nxt_ranking(rows=100)

    nxt_ok = not nxt_df.empty
    krx_ok = not krx_df.empty

    if nxt_ok:
        st.success(
            f"✅ NXT 데이터 수신 완료 ({len(nxt_df)}개 종목 | "
            f"총 거래량 {nxt_df['NXT거래량'].sum():,.0f}주 | "
            f"총 거래대금 {nxt_df['NXT거래대금'].sum()/1e8:,.1f}억원) — 20분 지연"
        )
    else:
        st.warning("⚠️ NXT 데이터를 가져올 수 없습니다. 장 시간 외(프리마켓 전)이거나 API 일시 장애일 수 있습니다.")

    if not krx_ok:
        st.info("KRX 데이터도 없습니다. 장 시작 전이거나 휴장일입니다.")
        return

    krx_vol_col = "거래량" if "거래량" in krx_df.columns else "Volume"
    krx_val_col = "거래대금" if "거래대금" in krx_df.columns else None

    if nxt_ok:
        merged = krx_df.join(
            nxt_df[["NXT거래량", "NXT거래대금", "종목명"]].rename(columns={"종목명": "_nxt_name"}),
            how="left",
        )
        merged["NXT거래량"] = merged["NXT거래량"].fillna(0)
        merged["NXT거래대금"] = merged["NXT거래대금"].fillna(0)
    else:
        merged = krx_df.copy()
        merged["NXT거래량"] = 0.0
        merged["NXT거래대금"] = 0.0

    krx_vol_series = merged[krx_vol_col].fillna(0) if krx_vol_col in merged.columns else pd.Series(0, index=merged.index)
    merged["합산거래량"] = krx_vol_series + merged["NXT거래량"]
    merged["합산거래대금"] = (
        merged[krx_val_col].fillna(0) + merged["NXT거래대금"]
        if krx_val_col and krx_val_col in merged.columns
        else merged["NXT거래대금"]
    )
    merged["NXT비중"] = (
        merged.apply(lambda r: r["NXT거래량"] / r["합산거래량"] * 100 if r["합산거래량"] > 0 else 0.0, axis=1)
        .round(1)
    )

    exclude_etf = st.toggle("🚫 ETF/ETN 제외 (순수 주식만 랭킹 보기)", value=True, key="nxt_exclude_etf")
    if exclude_etf:
        if ticker_to_name:
            merged = merged[merged.index.isin(ticker_to_name.keys())]
        elif "종목명" in merged.columns:
            merged = merged[~merged["종목명"].str.contains("|".join(_ETF_KW), case=False, na=False)]

    col_cfg = {
        "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]+)"),
        "등락률": st.column_config.TextColumn("등락률"),
        "NXT비중(%)": st.column_config.TextColumn("NXT비중"),
    }

    def _build_vol_display(df_sub: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        top = df_sub.sort_values("합산거래량", ascending=False).head(top_n)
        disp = pd.DataFrame(index=top.index)
        disp["종목명"] = [_naver_link(t, _resolve_name(t, ticker_to_name, top)) for t in top.index]
        if "현재가" in top.columns:
            disp["현재가"] = top["현재가"].apply(lambda x: f"{x:,.0f}")
        if "등락률" in top.columns:
            disp["등락률"] = top["등락률"]
        disp["KRX거래량"] = top[krx_vol_col].apply(lambda x: f"{x:,.0f}") if krx_vol_col in top.columns else "—"
        disp["NXT거래량"] = top["NXT거래량"].apply(lambda x: f"{x:,.0f}")
        disp["합산거래량"] = top["합산거래량"].apply(lambda x: f"{x:,.0f}")
        disp["NXT비중(%)"] = top["NXT비중"].apply(lambda x: f"{x:.1f}%")
        if "합산거래대금" in top.columns:
            disp["합산거래대금"] = top["합산거래대금"].apply(lambda x: f"{x:,.0f}")
        return disp

    def _apply_rate_style(styler, df_disp: pd.DataFrame):
        if "등락률" in df_disp.columns:
            styler = styler.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
        return styler

    st.subheader(f"🔥 KRX+NXT 합산 거래량 TOP 10 ({krx_time_str})")
    disp_vol = _build_vol_display(merged)
    st.dataframe(_apply_rate_style(disp_vol.style, disp_vol), column_config=col_cfg, use_container_width=True)

    st.subheader(f"💰 KRX+NXT 합산 거래대금 TOP 10 ({krx_time_str})")
    top_val = merged.sort_values("합산거래대금", ascending=False).head(10)
    disp_val = pd.DataFrame(index=top_val.index)
    disp_val["종목명"] = [_naver_link(t, _resolve_name(t, ticker_to_name, top_val)) for t in top_val.index]
    if "현재가" in top_val.columns:
        disp_val["현재가"] = top_val["현재가"].apply(lambda x: f"{x:,.0f}")
    if "등락률" in top_val.columns:
        disp_val["등락률"] = top_val["등락률"]
    if krx_val_col and krx_val_col in top_val.columns:
        disp_val["KRX거래대금"] = top_val[krx_val_col].apply(lambda x: f"{x:,.0f}")
    disp_val["NXT거래대금"] = top_val["NXT거래대금"].apply(lambda x: f"{x:,.0f}")
    disp_val["합산거래대금"] = top_val["합산거래대금"].apply(lambda x: f"{x:,.0f}")
    disp_val["NXT비중(%)"] = top_val["NXT비중"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(_apply_rate_style(disp_val.style, disp_val), column_config=col_cfg, use_container_width=True)

    if nxt_ok:
        st.divider()
        st.subheader("📊 NXT 단독 거래량 TOP 10")
        top_nxt = nxt_df.sort_values("NXT거래량", ascending=False).head(10)
        disp_nxt = pd.DataFrame(index=top_nxt.index)
        disp_nxt["종목명"] = [_naver_link(t, _resolve_name(t, ticker_to_name, top_nxt)) for t in top_nxt.index]
        disp_nxt["현재가(NXT)"] = top_nxt["현재가"].apply(lambda x: f"{x:,.0f}")
        disp_nxt["등락률"] = top_nxt["등락률"]
        disp_nxt["NXT거래량"] = top_nxt["NXT거래량"].apply(lambda x: f"{x:,.0f}")
        disp_nxt["NXT거래대금"] = top_nxt["NXT거래대금"].apply(lambda x: f"{x:,.0f}")
        st.dataframe(_apply_rate_style(disp_nxt.style, disp_nxt), column_config=col_cfg, use_container_width=True)


# ─── Individual Stock KRX+NXT Card ──────────────────────────────────────────

@st.cache_data(ttl=5, show_spinner=False)
def _fetch_kis_realtime(code: str) -> dict:
    from kis_api import get_current_price
    data = get_current_price(code)
    if data and data.get("ok"):
        return data
    return {"price": 0, "diff": 0, "rate": 0, "vol": 0, "val": 0, "open": 0, "high": 0, "low": 0, "ok": False}


@st.fragment
def render_stock_nxt_card(code: str, name: str) -> None:
    """단일 종목의 한국투자증권 실시간 시세와 NXT 거래 데이터를 비교 표시합니다."""
    from krx_data import get_nxt_ranking

    from datetime import datetime, timedelta, timezone
    _kst = timezone(timedelta(hours=9))

    col_a, col_b = st.columns(2)
    with col_a:
        with st.spinner("한국투자증권 실시간 시세 조회 중..."):
            nav = _fetch_kis_realtime(code)
            kis_fetch_time = datetime.now(_kst).strftime("%H:%M:%S")
    with col_b:
        with st.spinner("NXT 시세 조회 중 (20분 지연)..."):
            nxt_df = get_nxt_ranking(rows=200)
            nxt_fetch_time = datetime.now(_kst).strftime("%H:%M:%S")

    nxt_row = nxt_df.loc[code] if (not nxt_df.empty and code in nxt_df.index) else None

    st.divider()
    st.subheader("🔗 KRX + NXT 통합 거래 현황")

    if not nav["ok"] and nxt_row is None:
        st.warning("시세 데이터를 가져올 수 없습니다. 장 외 시간이거나 네트워크를 확인해주세요.")
        return

    naver_url = f"https://stock.naver.com/domestic/stock/{code}/price"

    # ── KRX 현황 카드 ──
    if nav["ok"]:
        _now_kst = datetime.now(_kst)
        _market_open = _now_kst.hour > 9 or (_now_kst.hour == 9 and _now_kst.minute >= 0)
        _market_close = _now_kst.hour > 15 or (_now_kst.hour == 15 and _now_kst.minute >= 30)
        _is_market_hours = _market_open and not _market_close
        if _is_market_hours:
            kis_trade_label = f"체결 {kis_fetch_time} · 실시간 무지연"
        else:
            kis_trade_label = f"15:30 종가 · 조회 {kis_fetch_time}"

        sq = "+" if nav["rate"] > 0 else ""
        col_str = "#D32F2F" if nav["rate"] > 0 else "#1976D2" if nav["rate"] < 0 else "#666"
        bg_tint = "rgba(211,47,47,0.04)" if nav["rate"] > 0 else "rgba(25,118,210,0.04)" if nav["rate"] < 0 else "#fafafa"

        st.markdown(
            f"""<div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px 20px;background:{bg_tint};margin-bottom:8px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <a href="{naver_url}" target="_blank" style="font-size:1.05rem;font-weight:700;text-decoration:none;color:#333;">📡 KRX 현황</a>
    <span style="font-size:0.72rem;color:#999;">{kis_trade_label}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
    <span style="font-size:1.6rem;font-weight:bold;">{nav['price']:,.0f}<small style="font-size:0.8rem;"> 원</small></span>
    <span style="color:{col_str};font-weight:bold;font-size:0.95rem;">{sq}{nav['diff']:,.0f} ({sq}{nav['rate']:.2f}%)</span>
  </div>
  <div style="display:flex;gap:20px;margin-top:10px;font-size:0.85rem;color:#555;">
    <span>거래량 <b>{nav['vol']:,.0f}</b> 주</span>
    <span>거래대금 <b>{nav['val']/1e8:,.1f}</b> 억원</span>
  </div>
</div>""",
            unsafe_allow_html=True,
        )

        # 투자자 동향
        inv = _get_naver_investor_data(code)
        if inv and inv.get("date"):
            def _inv_badge(label: str, emoji: str, val: int) -> str:
                c = "#D32F2F" if val > 0 else "#1976D2" if val < 0 else "#666"
                s = f"+{val:,.0f}" if val > 0 else f"{val:,.0f}"
                return f"<span style='display:inline-block;padding:4px 10px;border-radius:8px;background:#f5f5f5;font-size:0.82rem;margin-right:6px;'>{emoji} {label} <b style='color:{c};'>{s}</b></span>"

            st.markdown(
                f"<div style='margin:4px 0 12px;'>"
                f"{_inv_badge('개인', '🧑', inv['개인'])}"
                f"{_inv_badge('외국인', '🌍', inv['외국인'])}"
                f"{_inv_badge('기관', '🏛️', inv['기관'])}"
                f"<span style='font-size:0.7rem;color:#aaa;margin-left:4px;'>({inv['date']})</span></div>",
                unsafe_allow_html=True,
            )

    # ── NXT 현황 카드 ──
    nxt_actual_time = ""
    if nxt_fetch_time:
        try:
            _nxt_dt = datetime.now(_kst) - timedelta(minutes=20)
            nxt_actual_time = _nxt_dt.strftime("%H:%M:%S")
        except Exception:
            pass
    nxt_time_label = f"~{nxt_actual_time} 체결 · 조회 {nxt_fetch_time}" if nxt_actual_time else f"조회 {nxt_fetch_time}"

    if nxt_row is not None:
        np_ = float(nxt_row["현재가"])
        nr = float(nxt_row["등락률"])
        nv = float(nxt_row["NXT거래량"])
        nva = float(nxt_row["NXT거래대금"])
        ns = "+" if nr > 0 else ""
        n_diff = round(np_ - np_ / (1 + nr / 100)) if abs(nr) > 0.001 else 0
        n_col = "#D32F2F" if nr > 0 else "#1976D2" if nr < 0 else "#666"
        n_bg = "rgba(211,47,47,0.04)" if nr > 0 else "rgba(25,118,210,0.04)" if nr < 0 else "#fafafa"

        nxt_share_html = ""
        if nav["ok"] and nav["vol"] > 0 and nv > 0:
            sh = nv / (nav["vol"] + nv) * 100
            bar_w = min(sh, 100)
            nxt_share_html = (
                f'<div style="margin-top:10px;">'
                f'<div style="font-size:0.78rem;color:#888;margin-bottom:3px;">NXT 거래 비중 {sh:.1f}%</div>'
                f'<div style="background:#e0e0e0;border-radius:6px;height:8px;overflow:hidden;">'
                f'<div style="background:linear-gradient(90deg,#5c6bc0,#42a5f5);height:100%;width:{bar_w}%;border-radius:6px;"></div>'
                f'</div></div>'
            )

        st.markdown(
            f"""<div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px 20px;background:{n_bg};margin-bottom:8px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <a href="{naver_url}" target="_blank" style="font-size:1.05rem;font-weight:700;text-decoration:none;color:#333;">🏛️ NXT 현황</a>
    <span style="font-size:0.72rem;color:#999;">20분 지연 · {nxt_time_label}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
    <span style="font-size:1.6rem;font-weight:bold;">{np_:,.0f}<small style="font-size:0.8rem;"> 원</small></span>
    <span style="color:{n_col};font-weight:bold;font-size:0.95rem;">{ns}{n_diff:,.0f} ({ns}{nr:.2f}%)</span>
  </div>
  <div style="display:flex;gap:20px;margin-top:10px;font-size:0.85rem;color:#555;">
    <span>거래량 <b>{nv:,.0f}</b> 주</span>
    <span>거래대금 <b>{nva/1e8:,.1f}</b> 억원</span>
  </div>
  {nxt_share_html}
</div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""<div style="border:1px solid #e0e0e0;border-radius:12px;padding:16px 20px;background:#fafafa;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <a href="{naver_url}" target="_blank" style="font-size:1.05rem;font-weight:700;text-decoration:none;color:#333;">🏛️ NXT 현황</a>
    <span style="font-size:0.75rem;color:#999;">20분 지연</span>
  </div>
  <div style="color:#888;font-size:0.85rem;margin-top:8px;">상위 200 종목에 미포함 — NXT 단독 거래 데이터 없음</div>
</div>""",
            unsafe_allow_html=True,
        )
        if nav["ok"]:
            st.caption(f"💡 네이버 현재가({nav['price']:,.0f}원)에는 NXT 체결분이 이미 포함되어 있습니다.")


# ─── Naver Static Chart ───────────────────────────────────────────────────────

@st.fragment
def render_naver_chart(code: str, name: str) -> None:
    """국내 주식용 네이버 금융 일봉 차트 이미지를 렌더링합니다."""
    st.markdown(f"#### 📈 {name}({code}) 일봉 차트 (Naver)")
    st.caption("TradingView 위젯 지원 제한으로 네이버 금융 차트를 제공합니다.")
    st.image(f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{code}.png", use_container_width=True)
