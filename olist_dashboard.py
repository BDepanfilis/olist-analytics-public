import streamlit as st
from tools.download_db import ensure_db
from app import ui

st.set_page_config(page_title="Olist Analytics", layout="wide")

# Ensure we have the DuckDB file before anything tries to connect
try:
    ensure_db()
except Exception as e:
    st.error(f"Failed to fetch database: {e}")
    st.stop()

ui.render()
