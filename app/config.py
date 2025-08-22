# app/config.py
import os

try:
    import streamlit as st
    _SECRETS = dict(st.secrets)  
except Exception:
    _SECRETS = {}

DEFAULT_DUCKDB_PATH = (
    os.getenv("DB_PATH")
    or _SECRETS.get("db", {}).get("path")
    or "olist.duckdb"
)

DEFAULT_SCHEMA = (
    os.getenv("DB_SCHEMA")
    or _SECRETS.get("db", {}).get("schema")
    or "analytics_marts"  # safe fallback for local dev
)
