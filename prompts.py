"""prompts.py — AI 분석 프롬프트 생성 모듈

ChatGPT / Gemini / Claude 에 전달할 기술적 분석 프롬프트를 생성합니다.
"""
from __future__ import annotations

import pandas as pd


# ─── JSON 스키마 (단일 타임프레임) ──────────────────────────────────────────────

_SINGLE_TF_SCHEMA = """\
{
  "meta": {"ticker":"","asof":"","timeframe":"","currency":""},
  "data_quality": {"status":"ok|warn|fail","issues":[{"type":"","detail":"","impact":""}]},
  "signals": [
    {"method":"trend","score":-2,"stance":"bear|neutral|bull","key_levels":{"support":[],"resistance":[]},"entry_zones":[],"stop":{"hard":null,"soft":null},"targets":{"t1":null,"t2":null},"rationale":[]},
    {"method":"momentum", "...": ""},
    {"method":"volatility", "...": ""},
    {"method":"sr", "...": ""},
    {"method":"volume", "...": ""},
    {"method":"pattern", "...": ""}
  ],
  "news": {"items":[{"date":"","title":"","source":"","url":"","tag":"earnings|guidance|macro|regulation|mna|other","sentiment":"neg|neu|pos","impact":"low|mid|high"}], "summary":[]},
  "aggregate": {"weights":{"trend":0.25,"momentum":0.2,"volatility":0.15,"sr":0.2,"volume":0.1,"pattern":0.1}, "score_total":0, "final_action":"buy|wait|sell"},
  "plan": {"entries":[{"price":null,"size_pct":null,"type":"limit"}], "stop":{"hard":null,"soft":null}, "take_profit":[null,null], "invalidation_triggers":[]}
}"""

# ─── JSON 스키마 (멀티 타임프레임) ──────────────────────────────────────────────

_MULTI_TF_SCHEMA = """\
{
   "meta": {"ticker": "", "name": ""},
   "overall_outlook": "bullish|bearish|neutral",
   "timeframe_analysis": {
       "yearly": "bullish|bearish|neutral",
       "monthly": "bullish|bearish|neutral",
       "weekly": "bullish|bearish|neutral",
       "daily": "bullish|bearish|neutral"
   },
   "score": 0,
   "strategy": {
       "action": "buy|sell|wait",
       "entry": [0, 0],
       "target": [0, 0],
       "stop_loss": 0
   }
}"""


# ─── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _holding_advice(holding_status: str, currency: str, avg_price: float | None) -> str:
    """보유 상태에 따른 매매 전략 지침 문자열을 반환합니다."""
    if "보유" in holding_status and "매도" in holding_status:
        if avg_price and avg_price > 0:
            unit = "원" if currency == "KRW" else "$"
            price_str = f"{avg_price:,.0f}{unit}" if currency == "KRW" else f"{unit}{avg_price:,.2f}"
            return (
                f"사용자는 현재 이 종목을 **보유 중**이며, **평단가는 {price_str}**입니다. "
                "이 평단가를 기준으로 최우선적으로 **청산(익절/손절) 또는 물타기 타이밍**을 잡는 것에 집중하세요."
            )
        return "사용자는 현재 이 종목을 **보유 중**입니다. 최우선적으로 **청산(익절/손절) 타이밍**을 잡는 것에 집중하세요."
    if "미보유" in holding_status:
        return "사용자는 현재 이 종목을 **보유하고 있지 않습니다**. **신규 매수 진입**이 유효한지, 유효하다면 적절한 가격대는 어디인지 분석하세요."
    return "사용자는 현재 **관망(중립)** 상태입니다. 방향성이 확실해질 때까지 기다려야 할지, 아니면 지금 행동해야 할지 객관적으로 분석하세요."


def _format_news(news_list: list | None) -> str:
    """뉴스 목록을 프롬프트용 문자열로 변환합니다."""
    if not news_list:
        return "(뉴스 데이터가 없습니다. 웹 검색 기능을 활용해 주세요.)"
    return "\n".join(
        f"{n.get('date', '')} | {n.get('title', '')} | {n.get('source', '')} | {n.get('link', '')}"
        for n in news_list
    )


def _format_tables(timeframe_dfs: dict[str, pd.DataFrame]) -> str:
    """멀티 타임프레임 DataFrame 딕셔너리를 프롬프트용 CSV 블록 문자열로 변환합니다."""
    limits = {"Daily": 60, "Weekly": 52, "Monthly": 36}
    parts = []
    for tf, df in timeframe_dfs.items():
        if df.empty:
            continue
        n = limits.get(tf)
        df_slice = df.tail(n) if n else df
        parts.append(f"\n[{tf.upper()}_DATA (Recent)]\n{df_slice.to_csv(index=True)}\n")
    return "".join(parts)


# ─── 단일 타임프레임 프롬프트 ──────────────────────────────────────────────────

def generate_chatgpt_prompt(
    ticker: str, name: str, market: str, currency: str, timeframe: str,
    df: pd.DataFrame, news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """ChatGPT(OpenAI) 환경에 최적화된 기술적 분석 프롬프트를 생성합니다."""
    csv_data = df.to_csv(index=True)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""
1) ChatGPT용 프롬프트 (OpenAI 환경에 최적화) OpenAI
1-A) (가능하면) System 메시지 템플릿

아래를 시스템 프롬프트로 넣고, 다음의 User 템플릿에 실제 데이터를 붙이세요.

당신은 "주식 기술적 분석 리포트 생성기"다. 입력으로 제공된 가격/지표 테이블과 최신 뉴스를 근거로, 널리 쓰이는 기술적 분석 이론(추세추종, 모멘텀, 변동성, 지지/저항, 거래량/수급, 패턴, 이벤트 리스크)을 각각 독립적으로 평가하고, 마지막에 가중 종합해 매매전략을 제시하라.

규칙:
1) 한국어로 작성하되, 전문 용어는 영문을 괄호로 병기한다. 예: 상대강도지수(RSI)
2) 데이터 품질 검사를 먼저 수행하고(누락/중복/이상치/분할·배당 반영 여부), 문제 발견 시 "분석 가능/불가"와 보정 가정을 명시한다.
3) 각 방법론별로:
   - 사용 지표/규칙
   - 현재 신호(강세/중립/약세)와 점수(-2~-1/0/+1/+2)
   - 근거를 3~6줄로 '쉬운 말'로 설명
   - 다음 지지/저항/진입 후보 구간(가격 또는 %), 무효화(손절) 기준, 1·2차 목표가를 제시한다.
4) 뉴스는 "사실 요약 → 시장영향 경로(심리/실적/규제/수급) → 기술적 신호와 충돌 여부" 순서로 정리한다.
5) 마지막에 종합 점수(가중치 공개)로 "최종 액션(매수/관망/매도)"을 결정하고,
   - 권장 진입 구간(분할 2~3단계)
   - 손절 기준(하드/소프트)
   - 목표가(보수/기본/공격)
   - 포지션 운용(분할매수, 추세추종, 되돌림 매수 등)
   을 제시한다.
6) 확정적 단정 대신 '시나리오'로 제시하고, 어떤 조건에서 결론이 바뀌는지(트리거)도 써라.
7) 출력은 아래 포맷을 반드시 지키고, 맨 끝에 JSON을 코드블록으로 추가하라(파싱용).
8) **투자자 상태 반영**: {advice}

--------------------------------------------------

1-B) User 메시지 템플릿(실제 데이터 붙이는 자리)
[REQUEST]
아래 입력을 기반으로 기술적 분석 리포트를 생성해줘.
- 분석 기간: (테이블에 기반)
- 투자 성향: (보수/중립/공격) = 중립
- 매매 시간축: {timeframe}
- 주문 가능: 지정가(limit), 분할 진입, 손절 라인 설정
- **현재 보유 상태**: {holding_status}
- **투자자 맞춤 지침**: {advice}

[WEB_SEARCH]
가능하면 웹검색으로 "최근 14일" 주요 뉴스를 10~20개 수집해서 [NEWS]에 보강해줘.
(웹검색이 불가능하다면, 제공된 [NEWS]만 사용해줘.)

[META]
ticker={ticker}
name={name}
market={market}
currency={currency}
bar={timeframe}
timezone=Asia/Seoul
asof={pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
data_range={start_dt_str} ~ {end_dt_str}

[TABLE_PRICE_INDICATORS]
{csv_data}

[NEWS]
{news_str}

[OUTPUT_FORMAT]
아래 섹션 제목을 정확히 사용해줘.

1) 데이터 요약 (분석 데이터 기간: {start_dt_str} ~ {end_dt_str} 명시) 및 점검
2) 방법론별 신호
   2-1) 추세추종(MA/EMA/ADX)
   2-2) 모멘텀(RSI/MACD/Stochastic)
   2-3) 변동성(Bollinger/ATR)
   2-4) 지지·저항(Pivot/Fibonacci/고저점)
   2-5) 거래량·수급(Volume/OBV/VWAP 가능 시)
   2-6) 차트 패턴 분석(헤드앤숄더, 쌍바닥, 플래그, 캔들 패턴 등 가격 추이 기반)
3) 뉴스 기반 이벤트 리스크
4) 종합 결론(가중치·점수 공개)
5) 권장 매매계획(진입/손절/목표/분할/무효화 트리거) -- **중요: 투자자 상태({holding_status})에 맞춘 전략 제시**
6) 파싱용 JSON (마지막에 코드블록)

[JSON_SCHEMA]
{_SINGLE_TF_SCHEMA}
    """


def generate_gemini_prompt(
    ticker: str, name: str, market: str, currency: str, timeframe: str,
    df: pd.DataFrame, news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """Gemini(Google) 환경에 최적화된 기술적 분석 프롬프트를 생성합니다."""
    csv_data = df.to_csv(index=True)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""
2) Gemini용 프롬프트 (구글 검색/요약 스타일에 최적화) Google

Gemini는 "요약→정리→표준화"가 강점이라, 뉴스 태깅/이벤트 리스크와 간결한 결론을 강하게 고정하는 템플릿이 잘 먹힙니다.

2-A) (가능하면) System 메시지 템플릿
역할: 주식 기술적 분석 및 뉴스 이벤트 리스크 통합 리포트 엔진.

목표: 입력 테이블(가격/지표)과 최신 뉴스로부터, 널리 알려진 기술적 분석 규칙을 적용해 방법론별 신호를 산출하고 점수화한 뒤, 가중 종합해 "권장 매매구간/손절/목표/운용 방식"을 제시한다.

작성 규칙:
- 한국어 + 용어는 영문 병기(예: 이동평균선(MA))
- 숫자/레벨/구간을 최대한 구체적으로 제시
- 각 방법론은 (규칙 → 현재 신호 → 근거 → 레벨 → 전략) 순서
- 마지막에 반드시 JSON을 코드블록으로 출력(스키마 준수)
- **투자자 상태 반영**: {advice}

--------------------------------------------------

2-B) User 메시지 템플릿
아래 데이터를 기반으로 기술적 분석 + 최신 뉴스 이벤트 리스크를 통합해 리포트를 작성해줘.

[NEWS_FETCH]
가능하면 검색 기능을 사용해서 "최근 14일" 뉴스 10~20개를 수집하고,
각 뉴스에 대해 tag(earnings/guidance/macro/regulation/mna/other), sentiment(neg/neu/pos), impact(low/mid/high)를 붙여줘.
검색이 불가능하면 제공된 [NEWS]만 사용해.

[META]
ticker={ticker}
name={name}
market={market}
currency={currency}
timeframe={timeframe}
timezone=Asia/Seoul
asof={pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
holding_status={holding_status}
holding_advice={advice}
data_range={start_dt_str} ~ {end_dt_str}

[TABLE_PRICE_INDICATORS]
{csv_data}

[NEWS]
{news_str}

[OUTPUT]
1) 데이터 요약 (분석 데이터 기간: {start_dt_str} ~ {end_dt_str} 반드시 명시, 최근 종가/변동성/거래량 변화)
2) 방법론별 신호(추세/모멘텀/변동성/지지저항/거래량/차트 패턴 분석(헤드앤숄더, 쌍바닥 등)) 각각 점수(-2~+2)
3) 뉴스 이벤트 리스크(태깅표 + 핵심 5줄 요약)
4) 종합 스코어(가중치 공개)와 최종 액션(buy/wait/sell)
5) 실행계획: 분할 진입 2~3단계(가격), 손절(hard/soft), 목표가(보수/기본/공격), 트리거(결론 변경 조건) -- **{holding_status} 상태에 맞춘 전략**
6) JSON(스키마 준수) 코드블록

[JSON_SCHEMA]
(아래 스키마를 그대로 사용)
{_SINGLE_TF_SCHEMA}
    """


# ─── 멀티 타임프레임 프롬프트 ─────────────────────────────────────────────────

def generate_multi_timeframe_gemini_prompt(
    ticker: str, name: str, market: str, currency: str,
    timeframe_dfs: dict[str, pd.DataFrame], news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """Gemini용 멀티 타임프레임(일/주/월/연봉) 통합 분석 프롬프트를 생성합니다."""
    tables_str = _format_tables(timeframe_dfs)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""
2) Gemini용 프롬프트 (Multi-Timeframe 통합 분석)

[ROLE]
당신은 주식 시장의 "멀티 타임프레임(Multi-Timeframe) 기술적 분석 전문가"입니다.
제공된 일봉(Daily), 주봉(Weekly), 월봉(Monthly), 연봉(Yearly) 데이터를 종합하여, 단기/중기/장기 추세의 정합성을 평가하고 최적의 매매 전략을 수립합니다.

[GOAL]
4가지 타임프레임의 데이터를 분석하여 하나의 통합 리포트를 작성하세요.
특히 "큰 추세(연봉/월봉)가 살아있는가?", "중기 조정(주봉)이 마무리되었는가?", "단기 진입 시점(일봉)인가?"를 판단하는 것이 핵심입니다.

[INPUT DATA]
- Ticker: {ticker} ({name})
- Market: {market}
- Timeframes Provided: {', '.join(timeframe_dfs.keys())}
- **Data Range (Daily)**: {start_dt_str} ~ {end_dt_str}
- **Investor Status**: {holding_status}
- **Investor Advice**: {advice}

{tables_str}

[NEWS]
{news_str}

[OUTPUT FORMAT]
1. **종합 데이터 요약 (분석 데이터 기간: {start_dt_str} ~ {end_dt_str} 반드시 명시)**:
   - 연봉/월봉: 장기 추세 (상승/하락/횡보) 및 핵심 지지/저항
   - 주봉: 중기 추세 및 패턴
   - 일봉: 단기 추세 및 거래량 특이사항

2. **멀티 타임프레임 정합성 분석**:
   - 장기(Long-term) vs 단기(Short-term) 동조화 여부 (예: 장기 상승 중 단기 눌림목인가? 장단기 모두 하락인가?)
   - 주요 충돌 구간 (예: 일봉은 상승세나 월봉 저항선 도달)

3. **기술적 분석 세부 (종합)**:
   - 추세구조 (Moving Averages, Dow Theory)
   - 모멘텀 (RSI, Stochastic - 과매수/과매도)
   - 주요 가격 레벨 (지지/저항)
   - 차트 패턴 분석 (헤드앤숄더, 쌍바닥, 플래그, 캔들 패턴 등 가격 추이 기반)

4. **뉴스 및 이벤트 리스크**:
   - 주요 이슈가 차트에 미친 영향

5. **최종 트레이딩 전략 (Status: {holding_status})**:
   - **조언**: {advice}
   - **결론**: (강력 매수 / 매수 / 중립 / 매도 / 강력 매도)
   - **전략**: (추세 추종 / 역추세 진입 / 박스권 매매 / 차익실현 / 손절매 등)
   - **가격 가이드**:
     - 진입(Add/New): 1차, 2차
     - 목표(Target): 단기, 장기
     - 손절(Stop): 필히 준수해야 할 라인

6. **JSON Output**:
   (아래 스키마를 준수하여 코드블록으로 출력)
   {_MULTI_TF_SCHEMA}
"""


def generate_multi_timeframe_chatgpt_prompt(
    ticker: str, name: str, market: str, currency: str,
    timeframe_dfs: dict[str, pd.DataFrame], news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """ChatGPT용 멀티 타임프레임(일/주/월/연봉) 통합 분석 프롬프트를 생성합니다."""
    tables_str = _format_tables(timeframe_dfs)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""
1) ChatGPT용 프롬프트 (Multi-Timeframe 통합 분석)

[ROLE]
당신은 "멀티 타임프레임(Multi-Timeframe) 기술적 분석 전문가"입니다.
제공된 일봉/주봉/월봉/연봉 데이터를 종합하여, 단/중/장기 추세의 정합성을 평가하고 최적 매매 전략을 수립하세요.

[INPUT DATA]
- Ticker: {ticker} ({name})
- Market: {market}
- Timeframes Provided: {', '.join(timeframe_dfs.keys())}
- **Data Range (Daily)**: {start_dt_str} ~ {end_dt_str}
- **Investor Status**: {holding_status}
- **Investor Advice**: {advice}

{tables_str}

[NEWS]
{news_str}

[OUTPUT FORMAT]
아래 섹션을 명확히 구분하여 한글로 상세 리포트 작성:

1. **종합 데이터 요약 (분석 데이터 기간: {start_dt_str} ~ {end_dt_str} 반드시 명시)**: 큰 추세(월/연봉)부터 세부 추세(주/일봉)로 하향식(Top-down) 요약
2. **멀티 타임프레임 정합성 분석**: 장기적 추세와 단기 흐름의 동조화/충돌 여부 체크
3. **핵심 가격 레벨, 지표 (추세, 모멘텀 등) 및 차트 패턴 분석 (헤드앤숄더, 쌍바닥 등)**
4. **최종 매매 전략 (Status: {holding_status})**:
   - **조언**: {advice}
   - **실행 계획**: 구체적 진입, 손절, 목표 범위 제시
5. **JSON 포맷 요약 (분석 결과 파싱용)**:
   ```json
   {{
      "meta": {{"ticker": "{ticker}", "name": "{name}"}},
      "timeframe_analysis": {{"yearly": "","monthly": "","weekly": "","daily": ""}},
      "action": "buy|sell|wait",
      "entry_zone": [], "stop_loss": 0, "targets": []
   }}
   ```
"""


# ─── Claude (Opus) 전용 프롬프트 ───────────────────────────────────────────────

def generate_claude_prompt(
    ticker: str, name: str, market: str, currency: str, timeframe: str,
    df: pd.DataFrame, news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """Claude (Opus) 환경에 최적화된 기술적 분석 프롬프트를 생성합니다.

    Claude의 강점을 활용:
    - XML 태그 기반 구조화된 입력
    - 장문 컨텍스트에서의 정밀한 데이터 분석
    - 다단계 논리 추론 (chain-of-thought)
    - 불확실성 표현과 시나리오 분기
    """
    csv_data = df.to_csv(index=True)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""<system>
당신은 주식 기술적 분석 전문가이자 리스크 관리 어드바이저입니다.

<principles>
- 데이터에 근거한 분석만 수행합니다. 추측은 반드시 "추정"으로 명시합니다.
- 각 판단에 대해 확신도(confidence)를 high/medium/low로 표기합니다.
- 강세/약세 시나리오를 모두 제시하고, 어떤 조건에서 결론이 뒤집히는지(invalidation trigger) 명시합니다.
- 투자자의 현재 포지션 상태를 최우선으로 고려합니다.
</principles>

<analysis_framework>
6가지 독립 방법론을 순차 평가 후 가중 종합합니다:
1. 추세추종 (Trend) — MA/EMA 배열, ADX, 추세선 | 가중치 25%
2. 모멘텀 (Momentum) — RSI, MACD, 스토캐스틱 | 가중치 20%
3. 변동성 (Volatility) — 볼린저 밴드, ATR | 가중치 15%
4. 지지/저항 (S/R) — 피보나치, 피벗, 과거 고저점 | 가중치 20%
5. 거래량/수급 (Volume) — OBV, 거래량 추이 | 가중치 10%
6. 차트 패턴 (Pattern) — 캔들스틱, 클래식 패턴 | 가중치 10%
</analysis_framework>

<scoring>
각 방법론별 점수: -2(강한 약세) / -1(약세) / 0(중립) / +1(강세) / +2(강한 강세)
종합 점수 = Σ(점수 × 가중치), 범위 -2.0 ~ +2.0
</scoring>

<output_rules>
- 한국어로 작성, 전문 용어는 영문 병기 (예: 상대강도지수(RSI))
- 모든 가격 레벨은 구체적 숫자로 제시
- 분석 결과 맨 끝에 JSON을 코드블록으로 출력
</output_rules>
</system>

<user_context>
<investor_status>{holding_status}</investor_status>
<investor_advice>{advice}</investor_advice>
</user_context>

<market_data>
<meta>
ticker={ticker}
name={name}
market={market}
currency={currency}
timeframe={timeframe}
timezone=Asia/Seoul
asof={pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
data_range={start_dt_str} ~ {end_dt_str}
</meta>

<price_indicators>
{csv_data}
</price_indicators>

<news>
{news_str}
</news>
</market_data>

<instructions>
위 데이터를 기반으로 기술적 분석 리포트를 작성해주세요.

웹 검색이 가능하다면 "{name}" 관련 최근 14일 뉴스를 10~20개 추가 수집하여 분석에 반영해주세요.

<required_sections>
1. **데이터 품질 점검**
   - 데이터 기간: {start_dt_str} ~ {end_dt_str}
   - 누락/이상치/분할·배당 조정 여부 확인
   - 분석 신뢰도 판정 (분석 가능/주의/불가)

2. **방법론별 독립 분석** (각각에 대해: 사용 지표 → 현재 신호 → 점수 → 근거 → 핵심 레벨)
   2-1. 추세추종 (MA/EMA/ADX)
   2-2. 모멘텀 (RSI/MACD/Stochastic)
   2-3. 변동성 (Bollinger/ATR)
   2-4. 지지·저항 (Pivot/Fibonacci/고저점)
   2-5. 거래량·수급 (Volume/OBV)
   2-6. 차트 패턴 (헤드앤숄더, 쌍바닥, 플래그, 캔들 패턴 등)

3. **뉴스 & 이벤트 리스크**
   - 각 뉴스: 사실 요약 → 시장 영향 경로 → 기술적 신호와의 정합성
   - 향후 1~2주 주요 이벤트 캘린더 (실적 발표, 금리 결정 등)

4. **시나리오 분석** (Claude 특화)
   - 🟢 강세 시나리오: 조건, 목표가, 확률(추정)
   - 🔴 약세 시나리오: 조건, 지지선, 확률(추정)
   - ⚪ 기본 시나리오: 가장 가능성 높은 전개

5. **종합 결론**
   - 가중치별 점수 테이블
   - 종합 점수 및 최종 액션 (매수/관망/매도)
   - 확신도 (high/medium/low)

6. **매매 실행 계획** (투자자 상태: {holding_status})
   - {advice}
   - 분할 진입 2~3단계 (구체적 가격)
   - 손절: 하드 스탑 / 소프트 스탑
   - 목표가: 보수적 / 기본 / 공격적
   - 무효화 트리거 (이 조건 충족 시 전략 재검토)

7. **JSON 요약** (파싱용, 코드블록)
</required_sections>
</instructions>

<json_schema>
{_SINGLE_TF_SCHEMA}
</json_schema>"""


def generate_multi_timeframe_claude_prompt(
    ticker: str, name: str, market: str, currency: str,
    timeframe_dfs: dict[str, pd.DataFrame], news_list: list | None = None,
    holding_status: str = "관망(중립)", avg_price: float | None = None,
    start_dt_str: str | None = None, end_dt_str: str | None = None,
) -> str:
    """Claude (Opus)용 멀티 타임프레임 통합 분석 프롬프트를 생성합니다."""
    tables_str = _format_tables(timeframe_dfs)
    news_str = _format_news(news_list)
    advice = _holding_advice(holding_status, currency, avg_price)

    return f"""<system>
당신은 멀티 타임프레임(Multi-Timeframe) 기술적 분석 전문가입니다.

<core_methodology>
Top-Down 분석: 연봉 → 월봉 → 주봉 → 일봉 순서로 큰 그림에서 세부로 내려갑니다.
핵심 질문 3가지:
1. 대세 추세(연봉/월봉)가 살아있는가?
2. 중기 조정(주봉)이 마무리 단계인가?
3. 단기 진입 타이밍(일봉)이 왔는가?
</core_methodology>

<principles>
- 상위 타임프레임의 추세가 하위 타임프레임보다 우선합니다.
- 타임프레임 간 신호가 일치할수록 신뢰도가 높습니다.
- 충돌 구간(상위 저항 vs 하위 돌파)은 반드시 명시합니다.
- 각 판단에 확신도(high/medium/low)를 표기합니다.
</principles>

<output_rules>
- 한국어 + 전문 용어 영문 병기
- 구체적 가격 레벨 필수
- 마지막에 JSON 코드블록 출력
</output_rules>
</system>

<user_context>
<investor_status>{holding_status}</investor_status>
<investor_advice>{advice}</investor_advice>
</user_context>

<market_data>
<meta>
ticker={ticker}
name={name}
market={market}
currency={currency}
timeframes={', '.join(timeframe_dfs.keys())}
timezone=Asia/Seoul
asof={pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
data_range={start_dt_str} ~ {end_dt_str}
</meta>

{tables_str}

<news>
{news_str}
</news>
</market_data>

<instructions>
위 멀티 타임프레임 데이터를 종합 분석하여 통합 리포트를 작성해주세요.

웹 검색이 가능하다면 "{name}" 관련 최근 14일 뉴스를 수집하여 반영해주세요.

<required_sections>
1. **Top-Down 데이터 요약** (분석 기간: {start_dt_str} ~ {end_dt_str})
   - 연봉: 장기 대세 추세, 핵심 지지/저항 레벨
   - 월봉: 중장기 추세 및 사이클 위치
   - 주봉: 중기 추세, 조정 패턴 진행 상태
   - 일봉: 단기 추세, 거래량 특이사항, 최근 캔들 패턴

2. **타임프레임 정합성 매트릭스** (Claude 특화)
   | 타임프레임 | 추세 방향 | 모멘텀 | 핵심 레벨 | 확신도 |
   각 타임프레임 간 동조/충돌 여부를 명확히 판정

3. **핵심 기술적 분석**
   - 추세 구조 (MA 배열, 다우 이론)
   - 모멘텀 다이버전스 (RSI/MACD - 타임프레임 간 비교)
   - 주요 가격 레벨 (다중 타임프레임에서 겹치는 지지/저항 = 컨플루언스 존)
   - 차트 패턴 (헤드앤숄더, 쌍바닥, 플래그, 웨지 등)

4. **시나리오 분석**
   - 🟢 강세 시나리오: 트리거 조건, 목표가, 추정 확률
   - 🔴 약세 시나리오: 트리거 조건, 하방 지지, 추정 확률
   - ⚪ 기본(Base) 시나리오: 가장 유력한 전개 방향

5. **뉴스 & 이벤트 리스크**
   - 차트에 이미 반영된 이슈 vs 미반영 리스크
   - 향후 주요 이벤트 캘린더

6. **최종 트레이딩 전략** (투자자 상태: {holding_status})
   - {advice}
   - **결론**: 강력 매수 / 매수 / 중립 / 매도 / 강력 매도
   - **전략 유형**: 추세 추종 / 역추세 / 박스권 / 차익실현 / 손절
   - **가격 가이드**:
     - 진입(Entry): 1차, 2차, 3차 (각 가격 + 비중%)
     - 목표(Target): 단기 / 중기 / 장기
     - 손절(Stop): 반드시 준수할 라인
   - **무효화 트리거**: 이 조건 발생 시 전략 전면 재검토

7. **JSON 요약** (파싱용, 코드블록)
</required_sections>
</instructions>

<json_schema>
{_MULTI_TF_SCHEMA}
</json_schema>"""
