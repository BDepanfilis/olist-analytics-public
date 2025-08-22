# app/config.py
import os
import streamlit as st

def _secret(section, key, default=None):
    try:
        return st.secrets[section][key]
    except Exception:
        return default

DEFAULT_SCHEMA = (
    os.environ.get("DB_SCHEMA")
    or _secret("db", "schema")
    or "analytics_marts"  
)
