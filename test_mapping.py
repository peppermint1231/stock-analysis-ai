import sys
import streamlit as st
from krx_data import get_krx_mapping

st.cache_data.clear()

try:
    mapping = get_krx_mapping()
    print(f"Mapping size: {len(mapping)}")
    if mapping:
        print("First 5 items:", list(mapping.items())[:5])
except Exception as e:
    print(f"Error calling get_krx_mapping: {e}")
