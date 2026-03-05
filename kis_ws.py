"""kis_ws.py — 한국투자증권 OpenAPI 실시간 WebSocket 클라이언트

cisxo 블로그 (https://velog.io/@cisxo/) 아키텍처를 참고하여
Streamlit 환경에 맞게 재설계한 실시간 차트 데이터 수신 모듈입니다.

아키텍처:
  [한투 WebSocket] ──► [KISWebSocketClient (백그라운드 스레드)]
                              │
                    st.session_state["kis_ohlcv"][ticker]
                              │
                    [Streamlit Fragment 렌더링] ──► [TradingView Lightweight Charts]

사용법:
  # st.secrets에 아래 항목이 있으면 자동으로 실시간 모드 활성화
  # [kis]
  # app_key = "PSxxxxxxxxxxxxxxxx"
  # app_secret = "xxxxxx..."
  # is_paper = true   # 모의투자: true / 실전투자: false

  from kis_ws import get_kis_client
  client = get_kis_client()  # 없으면 None 반환
  if client:
      client.subscribe("005930")  # 삼성전자
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─── 한투 API 엔드포인트 ────────────────────────────────────────────────────────
_REST_REAL   = "https://openapi.koreainvestment.com:9443"
_REST_PAPER  = "https://openapivts.koreainvestment.com:29443"
_WS_REAL     = "wss://ops.koreainvestment.com:21000"
_WS_PAPER    = "wss://ops.koreainvestment.com:31000"

# 해외주식 실시간 체결: HDFSCNT0
# 국내주식 실시간 체결: H0STCNT0
_TR_KR = "H0STCNT0"
_TR_US = "HDFSCNT0"


# ─── REST 헬퍼 ──────────────────────────────────────────────────────────────────

def get_oauth_token(app_key: str, app_secret: str, is_paper: bool = False) -> str:
    """OAuth 접근 토큰을 발급합니다 (시세 조회용)."""
    base = _REST_PAPER if is_paper else _REST_REAL
    url = f"{base}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    res = requests.post(url, json=body, timeout=10)
    res.raise_for_status()
    return res.json()["access_token"]


def get_approval_key(app_key: str, app_secret: str, is_paper: bool = False) -> str:
    """WebSocket 연결용 approval key를 발급합니다."""
    # 실전/모의 모두 실전 엔드포인트 사용 (cisxo 참고: 모의는 :29443 사용)
    base = _REST_PAPER if is_paper else _REST_REAL
    url = f"{base}/oauth2/Approval"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": app_secret,
    }
    res = requests.post(url, json=body, timeout=10)
    res.raise_for_status()
    return res.json()["approval_key"]


def fetch_minute_chart(
    app_key: str,
    app_secret: str,
    ticker: str,
    exchange: str = "NAS",
    n_records: int = 100,
    is_paper: bool = False,
) -> list[dict]:
    """1분봉 히스토리 데이터를 REST API로 가져옵니다 (초기 차트 로딩용).

    Returns:
        List of dicts with keys: time(epoch), open, high, low, close, volume
    """
    try:
        token = get_oauth_token(app_key, app_secret, is_paper)
        base = _REST_PAPER if is_paper else _REST_REAL
        url = f"{base}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
            "NMIN": "1",
            "PINC": "1",
            "NEXT": "",
            "NREC": str(n_records),
            "FILL": "",
            "KEYB": "",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "content-type": "application/json; charset=utf-8",
            "appKey": app_key,
            "appSecret": app_secret,
            "tr_id": "HHDFS76950200",
            "custtype": "P",
        }
        res = requests.get(url, params=params, headers=headers, timeout=15)
        data = res.json()
        output2 = data.get("output2", [])
        bars = []
        for item in reversed(output2):
            try:
                dt_str = item.get("kymd", "") + item.get("khms", "")
                dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
                epoch = int(dt.replace(tzinfo=timezone.utc).timestamp())
                bars.append({
                    "time": epoch,
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("last", 0)),
                    "volume": float(item.get("evol", 0)),
                })
            except Exception:
                continue
        return bars
    except Exception as e:
        logger.warning(f"[KIS] 분봉 히스토리 fetch 실패: {e}")
        return []


# ─── 1분봉 집계기 ────────────────────────────────────────────────────────────────

class MinuteBarAggregator:
    """실시간 틱 데이터를 1분봉 OHLCV로 집계합니다."""

    def __init__(self) -> None:
        self._bars: list[dict] = []          # 확정 봉 리스트
        self._current: Optional[dict] = None # 현재(미확정) 봉

    def push_tick(self, price: float, volume: float, ts: datetime) -> Optional[dict]:
        """틱 하나를 집계합니다. 새 봉이 확정되면 반환합니다."""
        minute_ts = ts.replace(second=0, microsecond=0)
        epoch = int(minute_ts.replace(tzinfo=timezone.utc).timestamp())

        if self._current is None or self._current["time"] != epoch:
            # 이전 봉 확정
            if self._current is not None:
                self._bars.append(dict(self._current))
                if len(self._bars) > 1000:  # 메모리 제한
                    self._bars = self._bars[-500:]
            # 새 봉 시작
            self._current = {
                "time": epoch,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
            return self._bars[-1] if self._bars else None  # 직전 확정봉 반환
        else:
            # 같은 분 봉 업데이트
            self._current["high"] = max(self._current["high"], price)
            self._current["low"] = min(self._current["low"], price)
            self._current["close"] = price
            self._current["volume"] += volume
            return None

    def get_current_bar(self) -> Optional[dict]:
        return dict(self._current) if self._current else None

    def get_bars(self) -> list[dict]:
        """확정 봉 전체 + 현재(미확정) 봉을 합쳐서 반환합니다."""
        result = list(self._bars)
        if self._current:
            result.append(dict(self._current))
        return result

    def load_history(self, history: list[dict]) -> None:
        """REST API로 가져온 과거 분봉 데이터를 초기값으로 세팅합니다."""
        self._bars = list(history)
        self._current = None


# ─── WebSocket 클라이언트 ─────────────────────────────────────────────────────────

class KISWebSocketClient:
    """한국투자증권 WebSocket 클라이언트 (백그라운드 스레드 실행).

    cisxo 블로그 아키텍처:
      - 서버(이 클래스) ↔ 한투 WS: 1:1
      - Streamlit UI: 여러 Fragment가 session_state를 읽는 1:N 구조
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        is_paper: bool = False,
        session_state=None,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.is_paper = is_paper
        self._ss = session_state  # st.session_state 참조

        self._ws = None
        self._approval_key: Optional[str] = None
        self._connected = False
        self._should_run = True

        # 구독 관리 (cisxo: subscription map)
        self._subscribed: set[str] = set()
        self._lock = threading.Lock()

        # 종목별 1분봉 집계기
        self._aggregators: dict[str, MinuteBarAggregator] = defaultdict(MinuteBarAggregator)

        # 백그라운드 스레드 시작
        self._thread = threading.Thread(target=self._run, daemon=True, name="KIS-WS")
        self._thread.start()

    # ── 공개 API ────────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, ticker: str, tr_id: str = _TR_KR) -> None:
        """종목 구독 요청. 이미 연결된 경우 즉시 전송, 아니면 연결 후 전송."""
        with self._lock:
            if ticker in self._subscribed:
                return
            self._subscribed.add(ticker)

        if self._connected and self._ws:
            self._send_subscribe(ticker, tr_id, subscribe=True)

    def unsubscribe(self, ticker: str, tr_id: str = _TR_KR) -> None:
        """종목 구독 해제."""
        with self._lock:
            self._subscribed.discard(ticker)
        if self._connected and self._ws:
            self._send_subscribe(ticker, tr_id, subscribe=False)

    def get_bars(self, ticker: str) -> list[dict]:
        """특정 종목의 현재 1분봉 리스트를 반환합니다."""
        return self._aggregators[ticker].get_bars()

    def stop(self) -> None:
        """WebSocket 연결 종료."""
        self._should_run = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # ── 내부 구현 ────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """백그라운드 스레드 메인 루프 (자동 재연결 포함)."""
        retry = 0
        while self._should_run:
            try:
                self._approval_key = get_approval_key(
                    self.app_key, self.app_secret, self.is_paper
                )
                ws_url = _WS_PAPER if self.is_paper else _WS_REAL
                self._connect(ws_url)
                retry = 0
            except Exception as e:
                logger.error(f"[KIS-WS] 연결 오류: {e}")
                self._connected = False
                retry += 1
                wait = min(30, 2 ** retry)
                logger.info(f"[KIS-WS] {wait}초 후 재연결 시도...")
                time.sleep(wait)

    def _connect(self, ws_url: str) -> None:
        try:
            import websocket  # websocket-client
        except ImportError:
            logger.error("[KIS-WS] websocket-client 패키지가 없습니다. pip install websocket-client")
            self._should_run = False
            return

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def _on_open(self, ws) -> None:
        logger.info("[KIS-WS] ✅ WebSocket 연결됨")
        self._connected = True
        # 기존 구독 종목 재구독 (cisxo: 초기 구독 메시지 전송)
        with self._lock:
            tickers = list(self._subscribed)
        for ticker in tickers:
            self._send_subscribe(ticker, _TR_KR, subscribe=True)

    def _on_message(self, ws, message: str) -> None:
        try:
            # 한투 WebSocket 메시지 형식 파싱
            if message.startswith("{"):
                # JSON 메시지 (PINGPONG, 구독 응답 등)
                data = json.loads(message)
                if data.get("header", {}).get("tr_id") == "PINGPONG":
                    ws.send(json.dumps({"header": {"tr_id": "PINGPONG"}}))
                return

            # 파이프(|) 구분 실시간 체결 데이터
            # 형식: 암호화여부^TR_ID^데이터건수|데이터1|데이터2...
            parts = message.split("|")
            if len(parts) < 4:
                return

            tr_id = parts[1]
            data_cnt = int(parts[2])
            raw_data = parts[3]

            fields = raw_data.split("^")

            if tr_id == _TR_KR:
                self._handle_kr_tick(fields)
            elif tr_id == _TR_US:
                self._handle_us_tick(fields)
        except Exception as e:
            logger.debug(f"[KIS-WS] 메시지 파싱 오류: {e}")

    def _handle_kr_tick(self, fields: list[str]) -> None:
        """국내주식 실시간 체결(H0STCNT0) 처리."""
        try:
            # H0STCNT0 필드 순서 (한투 API 명세 기준)
            # 0:유가증권단축종목코드, 2:주식체결시간, 3:주식현재가, 12:체결거래량
            ticker = fields[0]
            time_str = fields[2]    # HHMMSS
            price = float(fields[3])
            volume = float(fields[12])
            now = datetime.now()
            ts = now.replace(
                hour=int(time_str[0:2]),
                minute=int(time_str[2:4]),
                second=int(time_str[4:6]),
                microsecond=0,
            )
            self._aggregators[ticker].push_tick(price, volume, ts)
            self._update_session_state(ticker)
        except Exception as e:
            logger.debug(f"[KIS-WS] KR 틱 처리 오류: {e}")

    def _handle_us_tick(self, fields: list[str]) -> None:
        """해외주식 실시간 체결(HDFSCNT0) 처리."""
        try:
            ticker = fields[0]
            price = float(fields[2])
            volume = float(fields[12]) if len(fields) > 12 else 0.0
            ts = datetime.now()
            self._aggregators[ticker].push_tick(price, volume, ts)
            self._update_session_state(ticker)
        except Exception as e:
            logger.debug(f"[KIS-WS] US 틱 처리 오류: {e}")

    def _update_session_state(self, ticker: str) -> None:
        """집계된 봉 데이터를 session_state에 기록합니다."""
        try:
            if self._ss is not None:
                if "kis_realtime_data" not in self._ss:
                    self._ss["kis_realtime_data"] = {}
                self._ss["kis_realtime_data"][ticker] = self._aggregators[ticker].get_bars()
        except Exception:
            pass

    def _on_error(self, ws, error) -> None:
        logger.error(f"[KIS-WS] 오류: {error}")
        self._connected = False

    def _on_close(self, ws, code, msg) -> None:
        logger.info(f"[KIS-WS] 연결 종료: code={code} msg={msg}")
        self._connected = False

    def _send_subscribe(self, ticker: str, tr_id: str, subscribe: bool) -> None:
        """구독/해제 메시지를 한투 WebSocket에 전송합니다 (cisxo 코드 참고)."""
        try:
            msg = {
                "header": {
                    "approval_key": self._approval_key,
                    "custtype": "P",
                    "tr_type": "1" if subscribe else "2",
                    "content-type": "utf-8",
                },
                "body": {
                    "input": {
                        "tr_id": tr_id,
                        "tr_key": ticker,
                    }
                },
            }
            self._ws.send(json.dumps(msg))
        except Exception as e:
            logger.warning(f"[KIS-WS] 구독 메시지 전송 실패: {e}")


# ─── Streamlit 통합 헬퍼 ─────────────────────────────────────────────────────────

_client_lock = threading.Lock()


def get_kis_client(session_state=None) -> Optional[KISWebSocketClient]:
    """st.secrets에 KIS 설정이 있으면 KISWebSocketClient 싱글턴을 반환합니다.

    st.secrets 형식:
        [kis]
        app_key = "PSxxxxxxxx"
        app_secret = "xxxx..."
        is_paper = true  # 선택 (기본값: false 실전)

    Returns:
        KISWebSocketClient 인스턴스 또는 None (설정 없을 때)
    """
    try:
        import streamlit as st
        kis_cfg = st.secrets.get("kis", {})
        app_key = kis_cfg.get("app_key", "")
        app_secret = kis_cfg.get("app_secret", "")
        if not app_key or not app_secret:
            return None

        # st.session_state에 싱글턴 저장 (Streamlit 재실행 간 유지)
        if "kis_client" not in st.session_state or st.session_state["kis_client"] is None:
            is_paper = bool(kis_cfg.get("is_paper", False))
            with _client_lock:
                if "kis_client" not in st.session_state or st.session_state["kis_client"] is None:
                    st.session_state["kis_client"] = KISWebSocketClient(
                        app_key=app_key,
                        app_secret=app_secret,
                        is_paper=is_paper,
                        session_state=st.session_state,
                    )
        return st.session_state["kis_client"]
    except Exception:
        return None


def get_kis_config() -> dict:
    """st.secrets에서 KIS 설정을 읽어 반환합니다. 없으면 빈 dict."""
    try:
        import streamlit as st
        return dict(st.secrets.get("kis", {}))
    except Exception:
        return {}
