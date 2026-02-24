
import pandas as pd

def generate_chatgpt_prompt(ticker, name, market, currency, timeframe, df, news_list=None, holding_status="관망(중립)", avg_price=None, start_dt_str=None, end_dt_str=None):
    """
    Generates a prompt for ChatGPT (OpenAI) based on the user's template.
    """
    
    # Format Data Table (CSV style)
    csv_data = df.to_csv(index=True)
    
    # Format News
    news_str = ""
    if news_list and len(news_list) > 0:
        for n in news_list:
            news_str += f"{n.get('date', '')} | {n.get('title', '')} | {n.get('source', '')} | {n.get('link', '')}\n"
    else:
        news_str = "(뉴스 데이터가 없습니다. 웹 검색 기능을 활용해 주세요.)"

    # Holding Status Logic
    holding_advice = ""
    if "보유" in holding_status and "매도" in holding_status: # 보유(매도예정)
         if avg_price is not None and avg_price > 0:
             curr_unit = "원" if currency == "KRW" else "$"
             if currency == "USD": 
                 price_str = f"{curr_unit}{avg_price:,.2f}"
             else:
                 price_str = f"{avg_price:,.0f}{curr_unit}"
             holding_advice = f"사용자는 현재 이 종목을 '보유 중'이며, 평단가는 **{price_str}**입니다. 이 평단가를 기준으로 수익 실현(익절), 물타기, 또는 손실 최소화(손절)를 위한 구체적인 '청산/매매 전략'에 집중하세요."
         else:
             holding_advice = "사용자는 현재 이 종목을 '보유 중'입니다. 수익 실현(익절) 또는 손실 최소화(손절)를 위한 구체적인 '청산/매도 전략'에 집중하세요."
    elif "미보유" in holding_status: # 미보유(매수예정)
         holding_advice = "사용자는 현재 이 종목을 '보유하고 있지 않습니다'. 신규 진입을 위한 '매수 타점'과 '진입 전략'에 집중하세요."
    else: # 관망(중립)
         holding_advice = "사용자는 현재 '관망' 중입니다. 시장의 객관적인 방향성을 파악하고 무리한 진입보다는 확인 매매 관점에서 분석하세요."

    prompt = f"""
1) ChatGPT용 프롬프트 (OpenAI 환경에 최적화) OpenAI
1-A) (가능하면) System 메시지 템플릿

아래를 시스템 프롬프트로 넣고, 다음의 User 템플릿에 실제 데이터를 붙이세요.

당신은 “주식 기술적 분석 리포트 생성기”다. 입력으로 제공된 가격/지표 테이블과 최신 뉴스를 근거로, 널리 쓰이는 기술적 분석 이론(추세추종, 모멘텀, 변동성, 지지/저항, 거래량/수급, 패턴, 이벤트 리스크)을 각각 독립적으로 평가하고, 마지막에 가중 종합해 매매전략을 제시하라.

규칙:
1) 한국어로 작성하되, 전문 용어는 영문을 괄호로 병기한다. 예: 상대강도지수(RSI)
2) 데이터 품질 검사를 먼저 수행하고(누락/중복/이상치/분할·배당 반영 여부), 문제 발견 시 “분석 가능/불가”와 보정 가정을 명시한다.
3) 각 방법론별로:
   - 사용 지표/규칙
   - 현재 신호(강세/중립/약세)와 점수(-2~-1/0/+1/+2)
   - 근거를 3~6줄로 ‘쉬운 말’로 설명
   - 다음 지지/저항/진입 후보 구간(가격 또는 %), 무효화(손절) 기준, 1·2차 목표가를 제시한다.
4) 뉴스는 “사실 요약 → 시장영향 경로(심리/실적/규제/수급) → 기술적 신호와 충돌 여부” 순서로 정리한다.
5) 마지막에 종합 점수(가중치 공개)로 “최종 액션(매수/관망/매도)”을 결정하고,
   - 권장 진입 구간(분할 2~3단계)
   - 손절 기준(하드/소프트)
   - 목표가(보수/기본/공격)
   - 포지션 운용(분할매수, 추세추종, 되돌림 매수 등)
   을 제시한다.
6) 확정적 단정 대신 ‘시나리오’로 제시하고, 어떤 조건에서 결론이 바뀌는지(트리거)도 써라.
7) 출력은 아래 포맷을 반드시 지키고, 맨 끝에 JSON을 코드블록으로 추가하라(파싱용).
8) **투자자 상태 반영**: {holding_advice}

--------------------------------------------------

1-B) User 메시지 템플릿(실제 데이터 붙이는 자리)
[REQUEST]
아래 입력을 기반으로 기술적 분석 리포트를 생성해줘.
- 분석 기간: (테이블에 기반)
- 투자 성향: (보수/중립/공격) = 중립
- 매매 시간축: {timeframe}
- 주문 가능: 지정가(limit), 분할 진입, 손절 라인 설정
- **현재 보유 상태**: {holding_status}
- **투자자 맞춤 지침**: {holding_advice}

[WEB_SEARCH]
가능하면 웹검색으로 “최근 14일” 주요 뉴스를 10~20개 수집해서 [NEWS]에 보강해줘.
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
{{
  "meta": {{"ticker":"","asof":"","timeframe":"","currency":""}},
  "data_quality": {{"status":"ok|warn|fail","issues":[{{"type":"","detail":"","impact":""}}]}},
  "signals": [
    {{"method":"trend","score":-2,"stance":"bear|neutral|bull","key_levels":{{"support":[],"resistance":[]}},"entry_zones":[],"stop":{{"hard":null,"soft":null}},"targets":{{"t1":null,"t2":null}},"rationale":[]}},
    {{"method":"momentum", ...}},
    {{"method":"volatility", ...}},
    {{"method":"sr", ...}},
    {{"method":"volume", ...}},
    {{"method":"pattern", ...}}
  ],
  "news": {{"items":[{{"date":"","title":"","source":"","url":"","tag":"earnings|guidance|macro|regulation|mna|other","sentiment":"neg|neu|pos","impact":"low|mid|high"}}], "summary":[]}},
  "aggregate": {{"weights":{{"trend":0.25,"momentum":0.2,"volatility":0.15,"sr":0.2,"volume":0.1,"pattern":0.1}}, "score_total":0, "final_action":"buy|wait|sell"}},
  "plan": {{"entries":[{{"price":null,"size_pct":null,"type":"limit"}}], "stop":{{"hard":null,"soft":null}}, "take_profit":[null,null], "invalidation_triggers":[]}}
}}
    """
    return prompt

def generate_gemini_prompt(ticker, name, market, currency, timeframe, df, news_list=None, holding_status="관망(중립)", avg_price=None, start_dt_str=None, end_dt_str=None):
    """
    Generates a prompt for Gemini (Google) based on the user's template.
    """
    
    csv_data = df.to_csv(index=True)
    
    news_str = ""
    if news_list and len(news_list) > 0:
        for n in news_list:
            news_str += f"{n.get('date', '')} | {n.get('title', '')} | {n.get('source', '')} | {n.get('link', '')}\n"
    else:
        news_str = "(뉴스 데이터가 없습니다. 웹 검색 기능을 활용해 주세요.)"

    # Holding Status Logic
    holding_advice = ""
    if "보유" in holding_status and "매도" in holding_status:
         if avg_price is not None and avg_price > 0:
             curr_unit = "원" if currency == "KRW" else "$"
             if currency == "USD": 
                 price_str = f"{curr_unit}{avg_price:,.2f}"
             else:
                 price_str = f"{avg_price:,.0f}{curr_unit}"
             holding_advice = f"사용자는 현재 이 종목을 **보유 중**이며, **평단가는 {price_str}**입니다. 이 평단가를 기준으로 최우선적으로 **청산(익절/손절) 또는 물타기 타이밍**을 잡는 것에 집중하세요."
         else:
             holding_advice = "사용자는 현재 이 종목을 **보유 중**입니다. 최우선적으로 **청산(익절/손절) 타이밍**을 잡는 것에 집중하세요."
    elif "미보유" in holding_status:
         holding_advice = "사용자는 현재 이 종목을 **보유하고 있지 않습니다**. **신규 매수 진입**이 유효한지, 유효하다면 적절한 가격대는 어디인지 분석하세요."
    else:
         holding_advice = "사용자는 현재 **관망(중립)** 상태입니다. 방향성이 확실해질 때까지 기다려야 할지, 아니면 지금 행동해야 할지 객관적으로 분석하세요."

    prompt = f"""
2) Gemini용 프롬프트 (구글 검색/요약 스타일에 최적화) Google

Gemini는 “요약→정리→표준화”가 강점이라, 뉴스 태깅/이벤트 리스크와 간결한 결론을 강하게 고정하는 템플릿이 잘 먹힙니다.

2-A) (가능하면) System 메시지 템플릿
역할: 주식 기술적 분석 및 뉴스 이벤트 리스크 통합 리포트 엔진.

목표: 입력 테이블(가격/지표)과 최신 뉴스로부터, 널리 알려진 기술적 분석 규칙을 적용해 방법론별 신호를 산출하고 점수화한 뒤, 가중 종합해 “권장 매매구간/손절/목표/운용 방식”을 제시한다.

작성 규칙:
- 한국어 + 용어는 영문 병기(예: 이동평균선(MA))
- 숫자/레벨/구간을 최대한 구체적으로 제시
- 각 방법론은 (규칙 → 현재 신호 → 근거 → 레벨 → 전략) 순서
- 마지막에 반드시 JSON을 코드블록으로 출력(스키마 준수)
- **투자자 상태 반영**: {holding_advice}

--------------------------------------------------

2-B) User 메시지 템플릿
아래 데이터를 기반으로 기술적 분석 + 최신 뉴스 이벤트 리스크를 통합해 리포트를 작성해줘.

[NEWS_FETCH]
가능하면 검색 기능을 사용해서 “최근 14일” 뉴스 10~20개를 수집하고,
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
holding_advice={holding_advice}
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
{{
  "meta": {{"ticker":"","asof":"","timeframe":"","currency":""}},
  "data_quality": {{"status":"ok|warn|fail","issues":[{{"type":"","detail":"","impact":""}}]}},
  "signals": [
    {{"method":"trend","score":-2,"stance":"bear|neutral|bull","key_levels":{{"support":[],"resistance":[]}},"entry_zones":[],"stop":{{"hard":null,"soft":null}},"targets":{{"t1":null,"t2":null}},"rationale":[]}},
    {{"method":"momentum", ...}},
    {{"method":"volatility", ...}},
    {{"method":"sr", ...}},
    {{"method":"volume", ...}},
    {{"method":"pattern", ...}}
  ],
  "news": {{"items":[{{"date":"","title":"","source":"","url":"","tag":"earnings|guidance|macro|regulation|mna|other","sentiment":"neg|neu|pos","impact":"low|mid|high"}}], "summary":[]}},
  "aggregate": {{"weights":{{"trend":0.25,"momentum":0.2,"volatility":0.15,"sr":0.2,"volume":0.1,"pattern":0.1}}, "score_total":0, "final_action":"buy|wait|sell"}},
  "plan": {{"entries":[{{"price":null,"size_pct":null,"type":"limit"}}], "stop":{{"hard":null,"soft":null}}, "take_profit":[null,null], "invalidation_triggers":[]}}
}}
    """
    return prompt

def generate_multi_timeframe_gemini_prompt(ticker, name, market, currency, timeframe_dfs, news_list=None, holding_status="관망(중립)", avg_price=None, start_dt_str=None, end_dt_str=None):
    """
    Generates a COMPREHENSIVE prompt for Gemini to analyze multiple timeframes.
    
    Args:
        timeframe_dfs (dict): {'Daily': df_d, 'Weekly': df_w, 'Monthly': df_m, 'Yearly': df_y}
        holding_status (str): User's current position status.
    """
    
    # Format Tables
    tables_str = ""
    for tf, df in timeframe_dfs.items():
        if not df.empty:
            # Taking recent rows to keep prompt size manageable, but enough for indicators
            # Daily: last 60, Weekly: last 52, Monthly: last 36, Yearly: All
            if tf == 'Daily': df_slice = df.tail(60)
            elif tf == 'Weekly': df_slice = df.tail(52)
            elif tf == 'Monthly': df_slice = df.tail(36)
            else: df_slice = df
            
            csv_data = df_slice.to_csv(index=True)
            tables_str += f"\n[{tf.upper()}_DATA (Recent)]\n{csv_data}\n"

    # Format News
    news_str = ""
    if news_list and len(news_list) > 0:
        for n in news_list:
            news_str += f"{n.get('date', '')} | {n.get('title', '')} | {n.get('source', '')} | {n.get('link', '')}\n"
    else:
        news_str = "(뉴스 데이터가 없습니다.)"

    # Holding Status Logic
    holding_advice = ""
    if "보유" in holding_status and "매도" in holding_status:
         if avg_price is not None and avg_price > 0:
             curr_unit = "원" if currency == "KRW" else "$"
             if currency == "USD": 
                 price_str = f"{curr_unit}{avg_price:,.2f}"
             else:
                 price_str = f"{avg_price:,.0f}{curr_unit}"
             holding_advice = f"사용자는 현재 이 종목을 **보유 중**이며, **평단가는 {price_str}**입니다. 이 평단가를 기준으로 최우선적으로 **청산(익절/손절) 또는 물타기 타이밍**을 잡는 것에 집중하세요."
         else:
             holding_advice = "사용자는 현재 이 종목을 **보유 중**입니다. 최우선적으로 **청산(익절/손절) 타이밍**을 잡는 것에 집중하세요."
    elif "미보유" in holding_status:
         holding_advice = "사용자는 현재 이 종목을 **보유하고 있지 않습니다**. **신규 매수 진입**이 유효한지, 유효하다면 적절한 가격대는 어디인지 분석하세요."
    else:
         holding_advice = "사용자는 현재 **관망(중립)** 상태입니다. 방향성이 확실해질 때까지 기다려야 할지, 아니면 지금 행동해야 할지 객관적으로 분석하세요."

    prompt = f"""
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
- **Investor Advice**: {holding_advice}

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
   - **조언**: {holding_advice}
   - **결론**: (강력 매수 / 매수 / 중립 / 매도 / 강력 매도)
   - **전략**: (추세 추종 / 역추세 진입 / 박스권 매매 / 차익실현 / 손절매 등)
   - **가격 가이드**:
     - 진입(Add/New): 1차, 2차
     - 목표(Target): 단기, 장기
     - 손절(Stop): 필히 준수해야 할 라인

6. **JSON Output**:
   (아래 스키마를 준수하여 코드블록으로 출력)
   {{
      "meta": {{"ticker": "{ticker}", "name": "{name}"}},
      "overall_outlook": "bullish|bearish|neutral",
      "timeframe_analysis": {{
          "yearly": "bullish|bearish|neutral",
          "monthly": "bullish|bearish|neutral",
          "weekly": "bullish|bearish|neutral",
          "daily": "bullish|bearish|neutral"
      }},
      "score": 0,  // -10 to +10
      "strategy": {{
          "action": "buy|sell|wait",
          "entry": [0, 0],
          "target": [0, 0],
          "stop_loss": 0
      }}
   }}
"""
    return prompt

def generate_multi_timeframe_chatgpt_prompt(ticker, name, market, currency, timeframe_dfs, news_list=None, holding_status="관망(중립)", avg_price=None, start_dt_str=None, end_dt_str=None):
    """
    Generates a COMPREHENSIVE prompt for ChatGPT to analyze multiple timeframes.
    
    Args:
        timeframe_dfs (dict): {'Daily': df_d, 'Weekly': df_w, 'Monthly': df_m, 'Yearly': df_y}
        holding_status (str): User's current position status.
    """
    
    # Format Tables
    tables_str = ""
    for tf, df in timeframe_dfs.items():
        if not df.empty:
            if tf == 'Daily': df_slice = df.tail(60)
            elif tf == 'Weekly': df_slice = df.tail(52)
            elif tf == 'Monthly': df_slice = df.tail(36)
            else: df_slice = df
            
            csv_data = df_slice.to_csv(index=True)
            tables_str += f"\n[{tf.upper()}_DATA (Recent)]\n{csv_data}\n"

    # Format News
    news_str = ""
    if news_list and len(news_list) > 0:
        for n in news_list:
            news_str += f"{n.get('date', '')} | {n.get('title', '')} | {n.get('source', '')} | {n.get('link', '')}\n"
    else:
        news_str = "(뉴스 데이터가 없습니다.)"

    # Holding Status Logic
    holding_advice = ""
    if "보유" in holding_status and "매도" in holding_status:
         if avg_price is not None and avg_price > 0:
             curr_unit = "원" if currency == "KRW" else "$"
             if currency == "USD": 
                 price_str = f"{curr_unit}{avg_price:,.2f}"
             else:
                 price_str = f"{avg_price:,.0f}{curr_unit}"
             holding_advice = f"사용자는 현재 이 종목을 '보유 중'이며, 평단가는 **{price_str}**입니다. 이 평단가를 기준으로 수익 실현(익절), 물타기, 손손절 타이밍에 대한 명확한 전략을 제시하세요."
         else:
             holding_advice = "사용자는 현재 이 종목을 '보유 중'입니다. 청산(익절/손절) 타이밍에 대한 명확한 전략을 제시하세요."
    elif "미보유" in holding_status:
         holding_advice = "사용자는 현재 이 종목을 '미보유' 상태입니다. 신규 진입 매수점과 전략에 집중하세요."
    else:
         holding_advice = "사용자는 현재 '관망' 중입니다. 객관적 방향성과 확인 매매 기준을 안내하세요."

    prompt = f"""
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
- **Investor Advice**: {holding_advice}

{tables_str}

[NEWS]
{news_str}

[OUTPUT FORMAT]
아래 섹션을 명확히 구분하여 한글로 상세 리포트 작성:

1. **종합 데이터 요약 (분석 데이터 기간: {start_dt_str} ~ {end_dt_str} 반드시 명시)**: 큰 추세(월/연봉)부터 세부 추세(주/일봉)로 하향식(Top-down) 요약
2. **멀티 타임프레임 정합성 분석**: 장기적 추세와 단기 흐름의 동조화/충돌 여부 체크
3. **핵심 가격 레벨, 지표 (추세, 모멘텀 등) 및 차트 패턴 분석 (헤드앤숄더, 쌍바닥 등)**
4. **최종 매매 전략 (Status: {holding_status})**:
   - **조언**: {holding_advice}
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
    return prompt

