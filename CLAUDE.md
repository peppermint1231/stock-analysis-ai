# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요
KRX(한국거래소) + NXT(대체거래소) + 미국 주식을 기술적 분석하는 Streamlit 웹앱.
KIS Open API, yfinance, pykrx, Google Sheets, Gemini AI를 활용.

## 실행 및 배포

```bash
# 로컬 실행
pip install -r requirements.txt
streamlit run app.py

# 배포: Streamlit Cloud (GitHub: peppermint1231/stock-analysis-ai)
# 시크릿: st.secrets["gcp_service_account"], st.secrets["kis"], st.secrets["gemini_api_key"] 등
```

Python 3.11 사용 (runtime.txt).

## 아키텍처

### 데이터 흐름
```
[KIS Open API] ──► kis_api.py (현재가, 분봉/일봉)
[KIS WebSocket] ──► kis_ws.py (실시간 체결 → session_state → TradingView 차트)
[pykrx/네이버] ──► krx_data.py (KRX 일별, 랭킹, 투자자, 종목 매핑)
[yfinance] ──► us_data.py (미국 주식), app.py (KRX 분봉)
[Google Sheets] ◄──► nxt_store.py (NXT 스냅샷 5분 주기 저장/조회, 28일 보관)
```

### 모듈 역할
- **app.py** — 진입점/오케스트레이터. UI 레이아웃, 분봉 분석, NXT 캔들 합성. 매우 큰 파일(~1000줄+)
- **kr_ui.py** — KRX/NXT 거래현황 카드, 랭킹 테이블 렌더링 (HTML/CSS 기반)
- **krx_data.py** — KRX 데이터 페칭/캐싱. pykrx pkg_resources shim 포함
- **kis_api.py** — KIS OAuth 토큰 관리, REST API 호출. 토큰은 kis_token.json에 파일 캐시
- **kis_ws.py** — KIS WebSocket 실시간 클라이언트. 백그라운드 스레드 → session_state 패턴
- **nxt_store.py** — Google Sheets 기반 NXT 스냅샷 저장소. gspread + threading
- **us_data.py** — 미국 주식 데이터. yfinance 인터벌 매핑 (10분→15m, 3분→2m 우회)
- **ai_client.py** — Gemini API 호출 (google-genai SDK, gemini-2.0-flash 모델)
- **prompts.py** — AI 프롬프트 생성. JSON 스키마 기반 단일/멀티 타임프레임 분석
- **multi_prompt_logic.py** — 멀티 타임프레임 Gemini 프롬프트 생성
- **utils.py** — `calculate_indicators()` (SMA, RSI, MACD, BB), `resample_ohlcv()`
- **date_fragment.py** — `@st.fragment` 기반 날짜 선택 UI (전체 리런 방지)

### NXT 장외시간 데이터 합성 (핵심 로직)
- `nxt_store.py`의 `start_nxt_scheduler()`가 5분마다 전 종목 NXT 스냅샷을 Google Sheets에 저장
- `app.py`의 `_nxt_snapshots_to_candles()`: 누적 OHLCV → 구간별 캔들로 변환 후 리샘플링
- `app.py`의 `_apply_nxt()`: KRX 장외시간(15:30~09:00)에 NXT 캔들을 추가
  - 섹션1: Sheets 과거 데이터 (best-effort, 실패해도 OK)
  - 섹션2: 실시간 NXT 스냅샷 (항상 작동)
- Sheets 로드 간헐 실패 → 3회 재시도 + 클라이언트 리셋 로직 적용됨

### 분봉 분석 기간 매핑
60분=4주, 30분=2주, 15분=1주, 5분=3일, 1분=1일

### 모바일 UI
- SVG data URI 아이콘 (Material Symbols 폰트 대체)
- 사이드바: 85vw, max 300px
- `initial_sidebar_state="auto"` (모바일=접힘)

## 작업 규칙
- 한국어로 소통
- git push는 업데이트 사항 있으면 알아서 해줘 (자동 푸시)
