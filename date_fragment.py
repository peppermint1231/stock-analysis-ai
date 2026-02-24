import streamlit as st
from datetime import datetime, timedelta

@st.fragment
def date_selector_fragment(prefix, default_start, default_end, interval_sel):
    """
    Renders the date selection UI.
    Updates st.session_state directly.
    Runs in a fragment to prevent full app rerun on interaction.
    """
    manual_dates = st.checkbox("기간 직접 설정 (Manual Date Range)", value=False, key=f"{prefix}_manual_dates_checkbox")
    
    # Logic to determine effective dates
    final_start = default_start
    final_end = default_end
    
    if manual_dates:
         col_d1, col_d2 = st.columns(2)
         with col_d1:
             final_start = st.date_input("시작일 (Start)", default_start, key=f"{prefix}_start_input")
         with col_d2:
             final_end = st.date_input("종료일 (End)", default_end, key=f"{prefix}_end_input")
    else:
         final_end = default_end
         
         # Auto Logic
         duration_text = "1년 (1 Year)"
         
         if "전체" in interval_sel or "All" in interval_sel or "종합분석" in interval_sel:
             final_start = datetime(1990, 1, 1)
             duration_text = "전체 구간 (Multi-Timeframe Analysis)"
         elif "1분" in interval_sel: 
             final_start = final_end
             duration_text = "1일 (1 Day)"
         elif "3분" in interval_sel: 
             final_start = final_end - timedelta(days=2)
             duration_text = "2일 (2 Days)"
         elif "5분" in interval_sel: 
             final_start = final_end - timedelta(days=4)
             duration_text = "4일 (4 Days)"
         elif "10분" in interval_sel: 
             final_start = final_end - timedelta(days=7)
             duration_text = "7일 (1 Week)"
         elif "30분" in interval_sel: 
             final_start = final_end - timedelta(days=14)
             duration_text = "14일 (2 Weeks)"
         elif "1시간" in interval_sel: 
             final_start = final_end - timedelta(days=29)
             duration_text = "약 1개월 (1 Month)"
         elif "주봉" in interval_sel: 
             final_start = final_end - timedelta(days=3650) 
             duration_text = "10년 (10 Years)"
         elif "월봉" in interval_sel or "연봉" in interval_sel: 
             final_start = datetime(1990, 1, 1) 
             duration_text = "상장 이후 전체 (Max)"
         else: 
             final_start = final_end - timedelta(days=365) # Daily default
             duration_text = "1년 (1 Year)"
             
         st.info(f"💡 분석 간격에 따른 최적 기간({duration_text})이 자동으로 적용됩니다. (변경하려면 위 체크박스 선택)")
    
    # Update Session State for Main App to use
    st.session_state[f"{prefix}_start"] = final_start
    st.session_state[f"{prefix}_end"] = final_end
