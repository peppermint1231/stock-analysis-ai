
def generate_multi_timeframe_gemini_prompt(ticker, name, market, currency, timeframe_dfs, news_list=None):
    """
    Generates a COMPREHENSIVE prompt for Gemini to analyze multiple timeframes.
    
    Args:
        timeframe_dfs (dict): {'Daily': df_d, 'Weekly': df_w, 'Monthly': df_m, 'Yearly': df_y}
    """
    
    # Format Tables
    tables_str = ""
    for tf, df in timeframe_dfs.items():
        if not df.empty:
            # Taking recent rows to keep prompt size manageable
            # Daily: last 30, Weekly: last 20, Monthly: last 24, Yearly: All
            if tf == 'Daily': df_slice = df.tail(30)
            elif tf == 'Weekly': df_slice = df.tail(20)
            elif tf == 'Monthly': df_slice = df.tail(24)
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

{tables_str}

[NEWS]
{news_str}

[OUTPUT FORMAT]
1. **종합 데이터 요약**:
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

4. **뉴스 및 이벤트 리스크**:
   - 주요 이슈가 차트에 미친 영향

5. **최종 트레이딩 전략**:
   - **결론**: (강력 매수 / 매수 / 중립 / 매도 / 강력 매도)
   - **전략**: (추세 추종 / 역추세 진입 / 박스권 매매 등)
   - **진입 가격**: 1차, 2차 분할 진입가
   - **목표 가격**: 단기 익절, 장기 목표
   - **손절 가격**: 필히 준수해야 할 라인

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
