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
    """등락률 값에 방향 화살표를 추가합니다."""
    if isinstance(val, (int, float)):
        if val > 0:
            return f"▲ {val:,.2f}"
        elif val < 0:
            return f"▼ {abs(val):,.2f}"
        return f"- {val:,.2f}"
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
    try:
        url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        tables = soup.find_all("table", {"class": "type2"})
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 7:
                    date_text = cells[0].text.strip()
                    # 날짜 형식: YYYY.MM.DD
                    if len(date_text) == 10 and "." in date_text:
                        try:
                            # col5: 기관순매매수량, col6: 외국인순매매수량
                            def _parse_num(s: str) -> int:
                                s = s.replace(",", "").replace("+", "").strip()
                                return int(s) if s and s != "-" else 0

                            inst_val = _parse_num(cells[5].text)
                            foreign_val = _parse_num(cells[6].text)
                            retail_val = -(inst_val + foreign_val)
                            return {
                                "개인": retail_val,
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

def render_horizontal_candles(df: pd.DataFrame, ticker_map: dict[str, str], max_pct: float = 30.0) -> str:
    """주어진 DataFrame으로 가로 캔들 차트 HTML 문자열을 생성합니다."""
    html = (
        '<style>.hc-card { flex-wrap: nowrap; } @media (max-width: 650px) { .hc-card { flex-wrap: wrap !important; } .hc-investor { flex: 1 1 100% !important; margin-top: 15px !important; } }</style>'
        '<div style="font-family: sans-serif; font-size: 14px; margin-top: 10px;'
        ' margin-bottom: 20px; display: grid;'
        ' grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 30px;">'
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

            def _pct(p: float) -> float:
                return (p - prev_close) / prev_close * 100

            def _cap(p: float) -> float:
                return max(-max_pct, min(max_pct, p))

            def _x(p: float) -> float:
                return (_cap(p) + max_pct) / (max_pct * 2) * 100

            o_cap, h_cap, l_cap, c_cap = _cap(_pct(open_p)), _cap(_pct(high_p)), _cap(_pct(low_p)), _cap(c_pct)
            x_o, x_h, x_l, x_c = _x(o_cap), _x(h_cap), _x(l_cap), _x(c_cap)

            body_left = min(x_o, x_c)
            body_width = max(0.5, abs(x_o - x_c))
            color = "#D32F2F" if c_pct >= 0 else "#1976D2"
            high_align = "0" if x_h < 80 else "-100%"

            # --- Investor Volume Logic (Naver Finance) ---
            inv = _get_naver_investor_data(str(ticker))
            retail_val  = inv["개인"]
            foreign_val = inv["외국인"]
            inst_val    = inv["기관"]
            other_val   = inv["기타"]
            
            pos_sum = sum(v for v in (retail_val, foreign_val, inst_val, other_val) if v > 0)
            neg_sum = abs(sum(v for v in (retail_val, foreign_val, inst_val, other_val) if v < 0))
            baseline = max(pos_sum, neg_sum)
            if baseline <= 0: baseline = 1

            def make_row(label, val):
                v_pct = (val / baseline) * 100 if baseline > 0 else 0
                row_color = '#D32F2F' if val > 0 else '#1976D2' if val < 0 else '#495057'
                s = '+' if val > 0 else ''
                bw = min(abs(v_pct) / 2, 50)
                lm = 50 if val > 0 else 50 - bw
                
                return f'''
                <div style="display: flex; align-items: center; justify-content: space-between; height: 32px; margin-bottom: 5px;">
                  <div style="width: 45px; text-align: left; color: #495057; font-weight: bold; font-size: 11px;">{label}</div>
                  <div style="flex: 1; position: relative; height: 16px; margin: 0 5px; display: flex; align-items: center;">
                     <div style="position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: #000; z-index: 1;"></div>
                     <div style="position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: #000; z-index: 3;"></div>
                     <div style="position: absolute; left: {lm}%; width: {bw}%; height: 12px; top: 2px; background: {row_color}; z-index: 2;"></div>
                  </div>
                  <div style="width: 55px; text-align: right; display: flex; flex-direction: column; justify-content: flex-end; padding-bottom: 2px;">
                     <div style="font-size: 9px; color: #adb5bd; line-height: 1.2; margin-bottom: 2px;">{val:,.0f}</div>
                     <div style="color: {row_color}; font-weight: bold; font-size: 11px; line-height: 1.2;">{s}{v_pct:.0f}%</div>
                  </div>
                </div>
                '''

            investor_rows = make_row('개인', retail_val) + make_row('외국인', foreign_val) + make_row('기관', inst_val) + make_row('기타', other_val)

            vol = float(df.loc[ticker, "거래량"]) if "거래량" in df.columns else 0
            vol_html = f'<div style="font-size:12px;color:#868e96;font-weight:normal;">주 {int(vol):,}</div>' if vol > 0 else ""

            html += f"""
<div class="hc-card" style="border:1px solid #e2e8f0;border-radius:12px;padding:20px 15px;background:white;
box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);display:flex;align-items:stretch;gap:15px; flex-wrap: nowrap;">
  <div style="flex:1 1 120px; min-width: 0;">    
    <div style="margin-bottom:25px;font-weight:bold;font-size:15px;display:flex;justify-content:space-between;align-items:center;">
      <div style="word-break: keep-all; line-height: 1.4;">
        {name} <span style="font-size:13px;color:gray;font-weight:normal;">
          ({close_p:,.0f}원 <span style="color:{color};">{c_pct:+.2f}%</span>)
        </span>
      </div>
      {vol_html}
    </div>
    <div style="position:relative;width:100%;height:40px;background-color:#f8f9fa;
      border-radius:4px;border:1px solid #e9ecef; margin-top: 10px;">
      <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background-color:#adb5bd;z-index:1;"></div>
      <div style="position:absolute;left:{x_l}%;width:{x_h-x_l}%;top:19px;height:2px;background-color:#495057;z-index:2;"></div>
      <div style="position:absolute;left:{body_left}%;width:{body_width}%;top:8px;height:24px;background-color:{color};border-radius:2px;z-index:3;"></div>
      <div style="position:absolute;left:{x_o}%;top:0;height:40px;border-left:2px dashed #343a40;z-index:4;"></div>
      <div style="position:absolute;left:{x_o}%;top:-19px;font-size:11px;color:#495057;transform:translateX(-50%);white-space:nowrap;">시 {open_p:,.0f}</div>
      <div style="position:absolute;left:{x_c}%;top:0;height:40px;border-left:2px solid #212529;z-index:5;"></div>
      <div style="position:absolute;left:{x_c}%;top:43px;font-size:12px;font-weight:bold;color:{color};transform:translateX(-50%);white-space:nowrap;">종 {close_p:,.0f}</div>
      <div style="position:absolute;left:{x_l}%;top:62px;font-size:11px;color:#6c757d;transform:translateX(-100%);padding-right:6px;text-align:right;line-height:1.2;">저 {low_p:,.0f}<br>({_pct(low_p):+.1f}%)</div>
      <div style="position:absolute;left:{x_h}%;top:62px;font-size:11px;color:#6c757d;transform:translateX({high_align});padding-left:6px;line-height:1.2;">고 {high_p:,.0f}<br>({_pct(high_p):+.1f}%)</div>
    </div>
  </div>
  <div class="hc-investor" style="flex: 0 0 165px; display: flex; flex-direction: column; justify-content: center; font-size: 13px; margin-top: 5px; min-width: 0;">
    {investor_rows}
  </div>
</div>"""
        except Exception:
            pass

    html += "</div>"
    return html


# ─── Top-10 Processing ────────────────────────────────────────────────────────

def process_top_10(df_subset: pd.DataFrame, ticker_map: dict[str, str], base_date_str: str) -> pd.DataFrame:
    """Top 10 DataFrame에 종목명 링크, 52주 고가, 돌파 여부를 추가합니다.

    pykrx 데이터에는 이미 시가/고가/저가가 포함되어 있으므로 재조회하지 않습니다.
    52주 최고가만 FDR로 별도 조회합니다.
    """
    df = df_subset.copy()

    # 종목명 컬럼 = 네이버 증권 링크
    def _get_name(t: str) -> str:
        if "종목명" in df_subset.columns:
            name_in_df = df_subset.loc[t, "종목명"]
            if pd.notna(name_in_df) and str(name_in_df).strip():
                return str(name_in_df)
        return ticker_map.get(t, t)

    df["종목명"] = [
        f"https://finance.naver.com/item/main.naver?code={t}&name={_get_name(t)}"
        for t in df.index
    ]

    # 현재가 컬럼 결정 (종가 or 현재가)
    price_col = "종가" if "종가" in df.columns else "현재가"

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

    # 시가/고가/저가가 없는 경우에만 종가로 채움 (pykrx 데이터엔 이미 있음)
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
        styler = styler.format({"등락률": add_arrow})
        styler = styler.map(format_price_change, subset=["등락률"])
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
            # ticker_to_name은 기존 get_krx_mapping 캐시(순수 주식만 존재)를 기반으로 하므로,
            # 이 목록에 없는 KODEX, TIGER 등 ETF/ETN 종목을 깔끔하게 필터링할 수 있습니다.
            all_df = all_df[all_df.index.isin(ticker_to_name.keys())]
        elif "종목명" in all_df.columns:
            # 매핑 실패 시 종목명 기반 폴백 필터링 (주요 ETF/ETN 키워드 제외)
            etf_keywords = ["KODEX", "TIGER", "KBSTAR", "KINDEX", "ACE", "ARIRANG", "KOSEF", "HANARO", "SOL", "TIMEFOLIO", "WOORI", "히어로즈", "마이티", "ETN", "인버스", "레버리지", "스팩", "선물"]
            pattern = "|".join(etf_keywords)
            all_df = all_df[~all_df["종목명"].str.contains(pattern, case=False, na=False)]

    # 거래량 Top 10
    top_vol = all_df.sort_values(vol_col, ascending=False).head(10).copy()
    top_vol = process_top_10(top_vol, ticker_to_name, today_str)
    _render_table(top_vol, display_cols, numeric_cols, "toggle_kr_vol", ticker_to_name)

    # 거래대금 Top 10
    st.subheader(f"💰 오늘의 거래대금 TOP 10 ({krx_time_str})")
    if val_col:
        top_val = all_df.sort_values(val_col, ascending=False).head(10).copy()
        top_val = process_top_10(top_val, ticker_to_name, today_str)
        _render_table(top_val, display_cols, numeric_cols, "toggle_kr_val", ticker_to_name)
    else:
        st.warning("'거래대금' 컬럼을 찾을 수 없습니다.")


# ─── KRX + NXT Combined Ranking ──────────────────────────────────────────────

@st.fragment
def render_krx_nxt_ranking(
    today_str: str,
    krx_time_str: str,
    name_to_ticker_map: dict[str, str],
) -> None:
    """KRX와 NXT(넥스트레이드) 데이터를 통합하여 거래량/거래대금 상위 종목을 렌더링합니다."""
    from krx_data import get_krx_ranking, get_nxt_ranking

    ticker_to_name = {v: k for k, v in name_to_ticker_map.items()}

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

    # ── NXT 상태 배지
    if nxt_ok:
        nxt_vol_total = nxt_df["NXT거래량"].sum()
        nxt_val_total = nxt_df["NXT거래대금"].sum()
        st.success(
            f"✅ NXT 데이터 수신 완료 ({len(nxt_df)}개 종목 | "
            f"총 거래량 {nxt_vol_total:,.0f}주 | "
            f"총 거래대금 {nxt_val_total/1e8:,.1f}억원) — 20분 지연"
        )
    else:
        st.warning("⚠️ NXT 데이터를 가져올 수 없습니다. 장 시간 외(프리마켓 전)이거나 API 일시 장애일 수 있습니다.")

    if not krx_ok:
        st.info("KRX 데이터도 없습니다. 장 시작 전이거나 휴장일입니다.")
        return

    # ── 종목명 정리
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
    if krx_val_col and krx_val_col in merged.columns:
        merged["합산거래대금"] = merged[krx_val_col].fillna(0) + merged["NXT거래대금"]
    else:
        merged["합산거래대금"] = merged["NXT거래대금"]

    merged["NXT비중"] = merged.apply(
        lambda r: (r["NXT거래량"] / r["합산거래량"] * 100) if r["합산거래량"] > 0 else 0.0,
        axis=1,
    ).round(1)

    exclude_etf = st.toggle("🚫 ETF/ETN 제외 (순수 주식만 랭킹 보기)", value=True, key="nxt_exclude_etf")
    if exclude_etf:
        if ticker_to_name:
            merged = merged[merged.index.isin(ticker_to_name.keys())]
        elif "종목명" in merged.columns:
            etf_kw = ["KODEX","TIGER","KBSTAR","KINDEX","ACE","ARIRANG","KOSEF","HANARO","SOL","TIMEFOLIO","ETN","인버스","레버리지","스팩","선물"]
            merged = merged[~merged["종목명"].str.contains("|".join(etf_kw), case=False, na=False)]

    def _build_display(df_sub: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        top = df_sub.sort_values("합산거래량", ascending=False).head(top_n).copy()
        def _name(t):
            n = ticker_to_name.get(t, "")
            if n: return n
            if "종목명" in top.columns:
                v = top.loc[t, "종목명"] if t in top.index else ""
                if pd.notna(v) and str(v).strip(): return str(v)
            return t
        disp = pd.DataFrame(index=top.index)
        disp["종목명"] = [f"https://finance.naver.com/item/main.naver?code={t}&name={_name(t)}" for t in top.index]
        if "현재가" in top.columns: disp["현재가"] = top["현재가"].apply(lambda x: f"{x:,.0f}")
        if "등락률" in top.columns: disp["등락률"] = top["등락률"]
        disp["KRX거래량"] = top[krx_vol_col].apply(lambda x: f"{x:,.0f}") if krx_vol_col in top.columns else "—"
        disp["NXT거래량"] = top["NXT거래량"].apply(lambda x: f"{x:,.0f}")
        disp["합산거래량"] = top["합산거래량"].apply(lambda x: f"{x:,.0f}")
        disp["NXT비중(%)"] = top["NXT비중"].apply(lambda x: f"{x:.1f}%")
        if "합산거래대금" in top.columns: disp["합산거래대금"] = top["합산거래대금"].apply(lambda x: f"{x:,.0f}")
        return disp

    col_cfg = {
        "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]+)"),
        "등락률": st.column_config.TextColumn("등락률"),
        "NXT비중(%)": st.column_config.TextColumn("NXT비중"),
    }

    st.subheader(f"🔥 KRX+NXT 합산 거래량 TOP 10 ({krx_time_str})")
    disp_vol = _build_display(merged, 10)
    styler_vol = disp_vol.style
    if "등락률" in disp_vol.columns:
        styler_vol = styler_vol.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
    st.dataframe(styler_vol, column_config=col_cfg, use_container_width=True)

    st.subheader(f"💰 KRX+NXT 합산 거래대금 TOP 10 ({krx_time_str})")
    top_val = merged.sort_values("합산거래대금", ascending=False).head(10)
    disp_val2 = pd.DataFrame(index=top_val.index)
    def _name_v(t):
        n = ticker_to_name.get(t, "")
        if n: return n
        if "종목명" in top_val.columns:
            v = top_val.loc[t, "종목명"] if t in top_val.index else ""
            if pd.notna(v) and str(v).strip(): return str(v)
        return t
    disp_val2["종목명"] = [f"https://finance.naver.com/item/main.naver?code={t}&name={_name_v(t)}" for t in top_val.index]
    if "현재가" in top_val.columns: disp_val2["현재가"] = top_val["현재가"].apply(lambda x: f"{x:,.0f}")
    if "등락률" in top_val.columns: disp_val2["등락률"] = top_val["등락률"]
    if krx_val_col and krx_val_col in top_val.columns: disp_val2["KRX거래대금"] = top_val[krx_val_col].apply(lambda x: f"{x:,.0f}")
    disp_val2["NXT거래대금"] = top_val["NXT거래대금"].apply(lambda x: f"{x:,.0f}")
    disp_val2["합산거래대금"] = top_val["합산거래대금"].apply(lambda x: f"{x:,.0f}")
    disp_val2["NXT비중(%)"] = top_val["NXT비중"].apply(lambda x: f"{x:.1f}%")
    styler_val = disp_val2.style
    if "등락률" in disp_val2.columns:
        styler_val = styler_val.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
    st.dataframe(styler_val, column_config=col_cfg, use_container_width=True)

    if nxt_ok:
        st.divider()
        st.subheader("📊 NXT 단독 거래량 TOP 10")
        top_nxt_only = nxt_df.sort_values("NXT거래량", ascending=False).head(10).copy()
        disp_nxt = pd.DataFrame(index=top_nxt_only.index)
        def _name_n(t): return ticker_to_name.get(t, str(top_nxt_only.loc[t, "종목명"]) if t in top_nxt_only.index else t)
        disp_nxt["종목명"] = [f"https://finance.naver.com/item/main.naver?code={t}&name={_name_n(t)}" for t in top_nxt_only.index]
        disp_nxt["현재가(NXT)"] = top_nxt_only["현재가"].apply(lambda x: f"{x:,.0f}")
        disp_nxt["등락률"] = top_nxt_only["등락률"]
        disp_nxt["NXT거래량"] = top_nxt_only["NXT거래량"].apply(lambda x: f"{x:,.0f}")
        disp_nxt["NXT거래대금"] = top_nxt_only["NXT거래대금"].apply(lambda x: f"{x:,.0f}")
        styler_nxt = disp_nxt.style
        if "등락률" in disp_nxt.columns:
            styler_nxt = styler_nxt.format({"등락률": add_arrow}).map(format_price_change, subset=["등락률"])
        st.dataframe(styler_nxt, column_config=col_cfg, use_container_width=True)


# ─── Individual Stock KRX+NXT Card ──────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_naver_realtime(code: str) -> dict:
    import requests
    from bs4 import BeautifulSoup
    try:
        url = f"https://finance.naver.com/item/sise.naver?code={code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        html = res.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        import re
        def _ext(sel):
            t = soup.select_one(sel)
            if not t: return 0.0
            text = t.get_text(strip=True)
            m = re.sub(r'[^0-9.]', '', text)
            try: return float(m) if m else 0.0
            except ValueError: return 0.0

        rate_el = soup.select_one("#_rate")
        rate_text = rate_el.get_text(strip=True) if rate_el else ""
        
        # Check if the rate has a minus sign, or if the element explicitly has the 'nv01' (blue/down) class
        is_down = "-" in rate_text or (rate_el and "nv01" in rate_el.get("class", []) + [c for child in rate_el.find_all() for c in child.get("class", [])])
        
        p = _ext("#_nowVal")
        diff = -_ext("#_diff") if is_down else _ext("#_diff")
        rate = -_ext("#_rate") if is_down else _ext("#_rate")

        return {
            "price": p, "diff": diff, "rate": rate,
            "vol": _ext("#_quant"), "val": _ext("#_amount") * 1_000_000,
            "ok": p > 0
        }
    except Exception:
        return {"price": 0, "diff": 0, "rate": 0, "vol": 0, "val": 0, "ok": False}


@st.fragment
def render_stock_nxt_card(code: str, name: str) -> None:
    """단일 종목의 네이버 실시간 시세와 NXT 거래 데이터를 비교 표시합니다."""
    from krx_data import get_nxt_ranking

    col_a, col_b = st.columns(2)
    with col_a:
        with st.spinner("네이버 실시간 시세 조회 중..."):
            nav = _fetch_naver_realtime(code)
    with col_b:
        with st.spinner("NXT 시세 조회 중 (20분 지연)..."):
            nxt_df = get_nxt_ranking(rows=200)

    nxt_row = nxt_df.loc[code] if (not nxt_df.empty and code in nxt_df.index) else None

    st.divider()
    st.subheader("🔗 KRX + NXT 통합 거래 현황")

    if not nav["ok"] and nxt_row is None:
        st.warning("시세 데이터를 가져올 수 없습니다. 장 외 시간이거나 네트워크를 확인해주세요.")
        return

    if nav["ok"]:
        st.markdown(f"**📡 [네이버 금융 실시간](https://finance.naver.com/item/main.naver?code={code})** (KRX+NXT 통합 최선가 · 약 30초 지연)")
        c1, c2, c3, c4 = st.columns(4)
        sq = "+" if nav["rate"] > 0 else ""
        ar = "▲" if nav["rate"] > 0 else ("▼" if nav["rate"] < 0 else "—")
        c1.metric("현재가", f"{nav['price']:,.0f} 원", f"{ar} {sq}{nav['rate']:.2f}%")
        c2.metric("전일대비", f"{sq}{nav['diff']:,.0f} 원")
        c3.metric("거래량", f"{nav['vol']:,.0f} 주" if nav["vol"] > 0 else "—")
        c4.metric("거래대금", f"{nav['val']/1e8:,.1f} 억원" if nav["val"] > 0 else "—")

        inv = _get_naver_investor_data(code)
        if inv and inv.get("date"):
            st.markdown(f"**📈 주체별 순매수 동향 (기준: {inv['date']})**")
            i1, i2, i3 = st.columns(3)
            
            def _color_val(val):
                if val > 0: return f"<span style='color:#D32F2F; font-weight:bold;'>+{val:,.0f}</span>"
                if val < 0: return f"<span style='color:#1976D2; font-weight:bold;'>{val:,.0f}</span>"
                return "0"

            i1.markdown(f"**🧑 개인**: {_color_val(inv['개인'])} 주", unsafe_allow_html=True)
            i2.markdown(f"**🌍 외국인**: {_color_val(inv['외국인'])} 주", unsafe_allow_html=True)
            i3.markdown(f"**🏛️ 기관**: {_color_val(inv['기관'])} 주", unsafe_allow_html=True)
        st.text("")

    st.markdown("**🏛️ NXT 단독 거래 데이터** (넥스트레이드 · 20분 지연)")
    if nxt_row is not None:
        np = float(nxt_row["현재가"])
        nr = float(nxt_row["등락률"])
        nv = float(nxt_row["NXT거래량"])
        nva = float(nxt_row["NXT거래대금"])
        ns = "+" if nr > 0 else ""
        na = "▲" if nr > 0 else ("▼" if nr < 0 else "—")
        d1, d2, d3 = st.columns(3)
        d1.metric("NXT 현재가", f"{np:,.0f} 원", f"{na} {ns}{nr:.2f}%")
        d2.metric("NXT 거래량", f"{nv:,.0f} 주")
        d3.metric("NXT 거래대금", f"{nva / 1e8:,.1f} 억원")
        if nav["ok"] and nav["vol"] > 0 and nv > 0:
            sh = nv / (nav["vol"] + nv) * 100
            st.progress(min(sh/100, 1.0), text=f"NXT 거래 비중 약 {sh:.1f}% (네이버 거래량 기준)")
    else:
        st.info("⏳ 해당 종목이 NXT 상위 200 종목에 포함되지 않아 NXT 단독 거래량을 확인할 수 없습니다.")
        if nav["ok"]:
            st.markdown(f"**💡 위 네이버 실시간 현재가({nav['price']:,.0f}원)에는 이미 NXT(넥스트레이드) 체결 가격과 거래량이 모두 포함되어 있습니다.**")
    st.caption("⚡ [NXT 시장 현황 보기](https://www.nextrade.co.kr/menu/transactionStatusMain/menuList.do)")


# ─── Naver Static Chart ───────────────────────────────────────────────────────

@st.fragment
def render_naver_chart(code: str, name: str) -> None:
    """국내 주식용 TradingView를 대체할 네이버 금융 일봉 차트 이미지를 렌더링합니다."""
    st.markdown(f"#### 📈 {name}({code}) 일봉 차트 (Naver)")
    st.caption("TradingView 위젯 지원 제한으로 네이버 금융 차트를 제공합니다.")
    url = f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{code}.png"
    st.image(url, use_container_width=True)
