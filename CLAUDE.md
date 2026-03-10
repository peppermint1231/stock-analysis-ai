# 주식 기술적 분석 앱 (Streamlit)

## 프로젝트 개요
KRX(한국거래소) + NXT(대체거래소) + 미국 주식을 분석하는 Streamlit 웹앱.
KIS Open API, yfinance, Google Sheets, Gemini AI를 활용.

## 핵심 파일 구조
- **app.py** — 메인 오케스트레이터. UI 레이아웃, 분봉 분석, NXT 캔들 합성
- **kr_ui.py** — KRX/NXT 거래현황 카드, 랭킹 테이블 등 한국 주식 UI
- **krx_data.py** — KRX 데이터 (pykrx, 네이버 스크래핑)
- **kis_api.py** — KIS Open API 클라이언트 (실시간 시세, 일봉)
- **nxt_store.py** — NXT 스냅샷을 Google Sheets에 저장/조회 (5분 간격, 28일 보관)
- **us_data.py** — 미국 주식 데이터 (yfinance, S&P500)
- **ai_client.py** — Gemini AI 분석 클라이언트
- **prompts.py** — AI 프롬프트 생성 (단일/멀티 타임프레임)
- **utils.py** — 기술 지표 계산 (`calculate_indicators`), OHLCV 리샘플링

## 주요 기술 사항

### NXT 장외시간 데이터
- `nxt_store.py`가 5분마다 전 종목 NXT 스냅샷을 Google Sheets에 저장
- `_nxt_snapshots_to_candles()` (app.py): 누적 OHLCV → 구간별 캔들로 변환 후 리샘플링
- `_apply_nxt()` (app.py): KRX 장외시간(15:30~09:00)에 NXT 캔들 추가
  - 섹션1: Sheets 과거 데이터 (best-effort, 실패해도 OK)
  - 섹션2: 실시간 NXT 스냅샷 (항상 작동)
- Sheets 로드가 간헐적으로 실패함 → 3회 재시도 + 클라이언트 리셋 로직 적용됨

### 분봉 분석 구조 (app.py)
- 60분=4주, 30분=2주, 15분=1주, 5분=3일, 1분=1일
- yfinance로 KRX 데이터 → `_apply_nxt()`로 NXT 합성 → `calculate_indicators()`

### 거래현황 카드 (kr_ui.py `render_stock_nxt_card`)
- KRX/NXT 카드: 둥근 테두리, 색상 틴트, 네이버 링크
- 네이버 URL: `https://stock.naver.com/domestic/stock/{code}/price`
- 투자자 배지: 개인/외국인/기관 인라인 pill
- NXT 거래 비중 프로그레스바

### 모바일 UI (app.py CSS)
- SVG data URI 아이콘 (Material Symbols 폰트 대체)
- 사이드바: 85vw, max 300px
- `initial_sidebar_state="auto"` (모바일=접힘, 데스크탑=자동)

## 배포
- GitHub: peppermint1231/stock-analysis-ai
- Streamlit Cloud 배포
- 시크릿: `st.secrets["gcp_service_account"]`, KIS API 키 등

## 작업 규칙
- git push는 업데이트 사항 있으면 알아서 해줘 (자동 푸시)
- 한국어로 소통
