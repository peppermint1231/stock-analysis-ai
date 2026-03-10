"""nxt_store.py — NXT 10분봉 데이터를 Google Sheets에 저장/조회하는 모듈

전 종목 NXT 스냅샷을 10분 간격으로 Google Sheets에 저장하고,
4주(28일) 초과 데이터를 자동 삭제합니다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ─── 상수 ──────────────────────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_SPREADSHEET_ID = "11N_JP3s7ESJHjm5JwosRl-ShL5kb4KDfhUka2hAgEgM"
_MAX_DAYS = 28  # 보관 일수
_HEADER = ["datetime", "code", "name", "open", "high", "low", "close", "volume"]

# ─── Google Sheets 연결 ────────────────────────────────────────────────────────
_client_lock = threading.Lock()
_gc: gspread.Client | None = None


def _get_client() -> gspread.Client:
    """gspread 클라이언트를 반환합니다 (싱글턴)."""
    global _gc
    with _client_lock:
        if _gc is None:
            creds_info = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_info, scopes=_SCOPES)
            _gc = gspread.authorize(creds)
        return _gc


def _get_worksheet() -> gspread.Worksheet:
    """스프레드시트의 첫 번째 워크시트를 반환합니다. 헤더가 없으면 추가합니다."""
    gc = _get_client()
    try:
        sh = gc.open_by_key(_SPREADSHEET_ID)
    except gspread.SpreadsheetNotFound:
        raise RuntimeError(
            "NXT 스프레드시트를 찾을 수 없습니다. "
            "서비스 계정 이메일에 편집 권한을 공유하세요."
        )
    ws = sh.sheet1
    # 헤더 확인
    if ws.row_count == 0 or ws.row_values(1) != _HEADER:
        ws.update("A1:H1", [_HEADER])
    return ws


# ─── 저장 ──────────────────────────────────────────────────────────────────────

def save_nxt_snapshot(nxt_df: pd.DataFrame) -> int:
    """NXT 랭킹 DataFrame을 Google Sheets에 10분봉 스냅샷으로 저장합니다.

    Args:
        nxt_df: get_nxt_ranking()이 반환한 DataFrame (index=code)

    Returns:
        저장된 행 수
    """
    if nxt_df is None or nxt_df.empty:
        return 0

    now_kst = datetime.now(_KST)
    # 5분 단위로 내림 (예: 14:43 → 14:40)
    minute_floored = (now_kst.minute // 5) * 5
    dt_str = now_kst.replace(minute=minute_floored, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")

    rows = []
    for code, row in nxt_df.iterrows():
        rows.append([
            dt_str,
            str(code),
            str(row.get("종목명", "")),
            float(row.get("NXT시가", 0)),
            float(row.get("NXT고가", 0)),
            float(row.get("NXT저가", 0)),
            float(row.get("현재가", 0)),
            float(row.get("NXT거래량", 0)),
        ])

    if not rows:
        return 0

    ws = _get_worksheet()
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


# ─── 조회 ──────────────────────────────────────────────────────────────────────

def load_nxt_history(code: str | None = None, days: int = 28) -> pd.DataFrame:
    """Google Sheets에서 NXT 과거 데이터를 로드합니다.

    Args:
        code: 종목코드 (None이면 전체)
        days: 최근 N일 데이터만 로드

    Returns:
        DataFrame with columns: datetime, code, name, open, high, low, close, volume
    """
    ws = _get_worksheet()
    all_data = ws.get_all_values()

    if len(all_data) <= 1:  # 헤더만 있음
        return pd.DataFrame(columns=_HEADER)

    df = pd.DataFrame(all_data[1:], columns=_HEADER)

    # 타입 변환
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 기간 필터
    cutoff = datetime.now(_KST) - timedelta(days=days)
    df = df[df["datetime"] >= cutoff]

    # 종목 필터
    if code:
        df = df[df["code"] == str(code)]

    return df.reset_index(drop=True)


# ─── 정리 (4주 초과 삭제) ──────────────────────────────────────────────────────

def cleanup_old_data() -> int:
    """4주(28일) 초과 데이터를 Google Sheets에서 삭제합니다.

    Returns:
        삭제된 행 수
    """
    ws = _get_worksheet()
    all_data = ws.get_all_values()

    if len(all_data) <= 1:
        return 0

    cutoff = datetime.now(_KST) - timedelta(days=_MAX_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M")

    # 유지할 행 찾기 (헤더 + cutoff 이후 데이터)
    keep_rows = [all_data[0]]  # 헤더
    deleted = 0
    for row in all_data[1:]:
        if row[0] >= cutoff_str:
            keep_rows.append(row)
        else:
            deleted += 1

    if deleted == 0:
        return 0

    # 시트 초기화 후 재작성
    ws.clear()
    if keep_rows:
        ws.update(f"A1:H{len(keep_rows)}", keep_rows)

    return deleted


# ─── 백그라운드 저장 스케줄러 ──────────────────────────────────────────────────

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_nxt_scheduler(fetch_func, interval_minutes: int = 10):
    """백그라운드에서 NXT 데이터를 주기적으로 Google Sheets에 저장합니다.

    Args:
        fetch_func: NXT 데이터를 가져오는 함수 (get_nxt_ranking 등)
        interval_minutes: 저장 간격 (분)
    """
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _loop():
        while True:
            # 다음 10분 정각까지 대기
            now = datetime.now(_KST)
            minutes_past = now.minute % interval_minutes
            seconds_past = minutes_past * 60 + now.second + now.microsecond / 1e6
            wait = (interval_minutes * 60) - seconds_past
            if wait > 0:
                time.sleep(wait)

            try:
                nxt_df = fetch_func(rows=1000)  # 전 종목
                saved = save_nxt_snapshot(nxt_df)
                print(f"[nxt_store] {datetime.now(_KST):%H:%M} — {saved}종목 저장 완료")

                # 매일 자정 근처에 정리 실행
                now = datetime.now(_KST)
                if now.hour == 0 and now.minute < interval_minutes:
                    deleted = cleanup_old_data()
                    if deleted:
                        print(f"[nxt_store] {deleted}행 정리 완료 (28일 초과)")

            except Exception as e:
                print(f"[nxt_store] 저장 오류: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[nxt_store] 백그라운드 스케줄러 시작 ({interval_minutes}분 간격)")
