from __future__ import annotations

import pandas as pd
import altair as alt
import streamlit as st

from .db import run_sql_cached

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _metric_card(label: str, value, fmt: str = None):
    col = st.container()
    with col:
        if fmt == "usd":
            st.subheader(label)
            st.markdown(f"### ${value:,.0f}")
        elif fmt == "int":
            st.subheader(label)
            st.markdown(f"### {int(value or 0):,}")
        else:
            st.subheader(label)
            st.markdown(f"### {value}")
    return col

def run_first_available(sql_candidates: list[str]) -> pd.DataFrame:
    """Try each SQL string until one succeeds (lets us handle schema diffs safely)."""
    for s in sql_candidates:
        try:
            df = run_sql_cached(s)
            if df is not None and not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()

# -----------------------------------------------------------------------------
# SQL (schema placeholder is injected by run_sql_cached)
# -----------------------------------------------------------------------------

# KPI for trailing ~180 data days (anchored on latest date in mart)
Q_KPI_TRAILING_180D = """
WITH cutoff AS (
  SELECT MAX(order_date) AS max_date
  FROM {schema}.mart_sales_daily
),
windowed AS (
  SELECT *
  FROM {schema}.mart_sales_daily
  WHERE order_date > (SELECT max_date - INTERVAL 180 DAY FROM cutoff)
)
SELECT
  SUM(paid_revenue)                                   AS paid_revenue,
  SUM(orders)                                         AS orders,
  CASE WHEN SUM(orders) = 0 THEN NULL
       ELSE SUM(paid_revenue) * 1.0 / SUM(orders)
  END                                                 AS aov
FROM windowed;
"""

# Revenue & Orders (last ~180 data days)
Q_REV_ORDERS_180D = """
WITH bounds AS (
  SELECT
    max(order_date) - INTERVAL 180 DAY AS start_day,
    max(order_date)                     AS end_day
  FROM {schema}.mart_sales_daily
)
SELECT
  order_date,
  SUM(paid_revenue) AS paid_revenue,
  SUM(orders)       AS orders
FROM {schema}.mart_sales_daily, bounds
WHERE order_date >= bounds.start_day
  AND order_date <= bounds.end_day
GROUP BY 1
ORDER BY 1;
"""

# --- Cohort size: multiple fallbacks ---
Q_COHORT_SIZE_MART_CUSTOMER = """
SELECT cohort_month, cohort_size
FROM {schema}.mart_customer_cohorts
ORDER BY cohort_month;
"""

Q_COHORT_SIZE_MART_COHORTS_SIZE = """
SELECT cohort_month, cohort_size
FROM {schema}.mart_cohorts
ORDER BY cohort_month;
"""

Q_COHORT_SIZE_MART_COHORTS_NEW = """
SELECT cohort_month, new_customers AS cohort_size
FROM {schema}.mart_cohorts
ORDER BY cohort_month;
"""

Q_COHORT_SIZE_FROM_LTV_DISTINCT = """
SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_size
FROM {schema}.mart_ltv_customer_monthly
WHERE months_since_cohort = 0
GROUP BY 1
ORDER BY 1;
"""

Q_COHORT_SIZE_FROM_LTV_COL = """
SELECT cohort_month, MAX(cohort_size) AS cohort_size
FROM {schema}.mart_ltv_customer_monthly
GROUP BY 1
ORDER BY 1;
"""

# ---- LTV logic: summary + queries (supports month-0-only fallback) ----
Q_LTV_SUMMARY = """
SELECT
  MIN(months_since_cohort) AS min_m,
  MAX(months_since_cohort) AS max_m,
  COUNT(*)                 AS rows
FROM {schema}.mart_ltv_customer_monthly;
"""

# Prefer avg_cumulative_ltv when present; else fall back to cumulative_ltv
Q_LTV_MONTHLY = """
SELECT
  cohort_month,
  months_since_cohort,
  COALESCE(avg_cumulative_ltv, cumulative_ltv) AS avg_cumulative_ltv
FROM {schema}.mart_ltv_customer_monthly
WHERE months_since_cohort BETWEEN 0 AND 36
ORDER BY cohort_month, months_since_cohort;
"""

# Month-0 only: first-month LTV per cohort
Q_LTV_MONTH0 = """
SELECT
  cohort_month,
  AVG(COALESCE(avg_cumulative_ltv, cumulative_ltv)) AS m0_ltv
FROM {schema}.mart_ltv_customer_monthly
WHERE months_since_cohort = 0
GROUP BY 1
ORDER BY cohort_month;
"""

# Retention heatmap — try two shapes:
Q_RETENTION_COL_RETENTION = """
SELECT
  cohort_month,
  months_since_cohort,
  retention
FROM {schema}.mart_retention_monthly
WHERE months_since_cohort BETWEEN 0 AND 36
ORDER BY cohort_month, months_since_cohort;
"""

Q_RETENTION_COL_RATE = """
SELECT
  cohort_month,
  months_since_cohort,
  retention_rate AS retention
FROM {schema}.mart_retention_monthly
WHERE months_since_cohort BETWEEN 0 AND 36
ORDER BY cohort_month, months_since_cohort;
"""

# Returns & Reviews
Q_RETURNS_DAILY = """
SELECT
  order_date,
  returns,
  avg_review_score
FROM {schema}.mart_returns_quality_daily
ORDER BY order_date;
"""

Q_RETURNS_MONTHLY = """
SELECT
  order_month,
  returns
FROM {schema}.mart_returns_quality_monthly
ORDER BY order_month;
"""

# Marketing: ROAS only when spend > 0
Q_MARKETING_ROAS = """
WITH base AS (
  SELECT day,
         SUM(gross_revenue) AS gross_revenue,
         SUM(spend)         AS spend
  FROM {schema}.mart_marketing_roi
  GROUP BY 1
)
SELECT
  day,
  CASE WHEN spend > 0 THEN gross_revenue * 1.0 / spend END AS roas
FROM base
WHERE spend > 0
ORDER BY day;
"""

# Marketing: spend vs revenue
Q_MARKETING_SERIES = """
SELECT day, 'gross_revenue' AS metric, SUM(gross_revenue) AS value
FROM {schema}.mart_marketing_roi
GROUP BY 1
UNION ALL
SELECT day, 'spend' AS metric, SUM(spend) AS value
FROM {schema}.mart_marketing_roi
GROUP BY 1
ORDER BY day, metric;
"""

# -----------------------------------------------------------------------------
# Tabs
# -----------------------------------------------------------------------------

def render_overview():
    # KPI matches the charts: trailing ~180 data days
    st.subheader("Overview (last ~180 data days)")

    kpi = run_sql_cached(Q_KPI_TRAILING_180D).iloc[0].fillna(0)
    k1, k2, k3 = st.columns([1, 1, 1])
    with k1:
        _metric_card("Paid Revenue", float(kpi["paid_revenue"]), fmt="usd")
    with k2:
        _metric_card("Orders", int(kpi["orders"]), fmt="int")
    with k3:
        _metric_card("AOV", float(kpi["aov"]), fmt="usd")

    st.markdown("### Revenue & Orders (Last ~180 data days)")
    df = run_sql_cached(Q_REV_ORDERS_180D).copy()
    if not df.empty:
        df["order_date"] = pd.to_datetime(df["order_date"])

        rev = (
            alt.Chart(df)
            .mark_line()
            .encode(
                x=alt.X("order_date:T", title="order_date"),
                y=alt.Y("paid_revenue:Q", title="Paid Revenue"),
                tooltip=[
                    alt.Tooltip("order_date:T", title="Date"),
                    alt.Tooltip("paid_revenue:Q", title="Revenue", format=",.0f"),
                ],
            )
            .properties(height=300)
        )

        ords = (
            alt.Chart(df)
            .mark_area(opacity=0.35)
            .encode(
                x=alt.X("order_date:T", title="order_date"),
                y=alt.Y("orders:Q", title="Orders"),
                tooltip=[
                    alt.Tooltip("order_date:T", title="Date"),
                    alt.Tooltip("orders:Q", title="Orders", format=",.0f"),
                ],
            )
            .properties(height=300)
        )

        c1, c2 = st.columns([2, 2])
        with c1:
            st.altair_chart(rev, use_container_width=True)
        with c2:
            st.altair_chart(ords, use_container_width=True)
    else:
        st.info("No data yet in mart_sales_daily.")

def render_cohorts():
    st.subheader("Cohorts: New Customers per Cohort Month")

    dfc = run_first_available([
        Q_COHORT_SIZE_MART_CUSTOMER,
        Q_COHORT_SIZE_MART_COHORTS_SIZE,
        Q_COHORT_SIZE_MART_COHORTS_NEW,
        Q_COHORT_SIZE_FROM_LTV_DISTINCT,
        Q_COHORT_SIZE_FROM_LTV_COL,
    ])

    if not dfc.empty:
        dfc["cohort_month"] = pd.to_datetime(dfc["cohort_month"])
        bar = (
            alt.Chart(dfc)
            .mark_bar()
            .encode(
                x=alt.X("cohort_month:T", title="cohort_month"),
                y=alt.Y("cohort_size:Q", title="New Customers"),
                tooltip=[
                    alt.Tooltip("cohort_month:T", title="Cohort"),
                    alt.Tooltip("cohort_size:Q", title="New Customers", format=",.0f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(bar, use_container_width=True)
    else:
        st.info("Couldn’t find a cohorts table. Build either `mart_customer_cohorts`, `mart_cohorts`, or ensure `mart_ltv_customer_monthly` includes months_since_cohort=0 with customer_id.")

    # ----- LTV section with month-0 fallback -----
    ltvs = run_sql_cached(Q_LTV_SUMMARY)
    max_m = int(ltvs.iloc[0]["max_m"]) if not ltvs.empty else 0

    if max_m > 0:
        st.subheader("Monthly LTV by Months Since Cohort (Avg Cumulative)")
        dfl = run_sql_cached(Q_LTV_MONTHLY)
        if not dfl.empty:
            line = (
                alt.Chart(dfl)
                .mark_line()
                .encode(
                    x=alt.X("months_since_cohort:Q", title="Months Since Cohort"),
                    y=alt.Y("avg_cumulative_ltv:Q", title="Avg Cumulative LTV"),
                    color=alt.Color("cohort_month:T", title="Cohort (month)"),
                    tooltip=[
                        alt.Tooltip("cohort_month:T", title="Cohort"),
                        alt.Tooltip("months_since_cohort:Q", title="Months"),
                        alt.Tooltip("avg_cumulative_ltv:Q", title="Cum LTV", format=",.0f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(line, use_container_width=True)
        else:
            st.info("No data in mart_ltv_customer_monthly.")
    else:
        st.subheader("First-Month LTV by Cohort (data limited to month 0)")
        dfm0 = run_sql_cached(Q_LTV_MONTH0)
        if not dfm0.empty:
            dfm0["cohort_month"] = pd.to_datetime(dfm0["cohort_month"])
            m0 = (
                alt.Chart(dfm0)
                .mark_bar()
                .encode(
                    x=alt.X("cohort_month:T", title="Cohort"),
                    y=alt.Y("m0_ltv:Q", title="First-Month LTV"),
                    tooltip=[
                        alt.Tooltip("cohort_month:T", title="Cohort"),
                        alt.Tooltip("m0_ltv:Q", title="First-Month LTV", format=",.0f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(m0, use_container_width=True)
            st.caption("Note: current marts don’t include months > 0, so we show average first-month LTV per cohort.")
        else:
            st.info("No month-0 LTV data to show.")

    st.subheader("Retention by Months Since Cohort")
    dfr = run_first_available([
        Q_RETENTION_COL_RETENTION,  # if your mart has `retention`
        Q_RETENTION_COL_RATE,       # if your mart has `retention_rate`
    ])
    if not dfr.empty:
        dfr["cohort_month"] = pd.to_datetime(dfr["cohort_month"])
        heat = (
            alt.Chart(dfr)
            .mark_rect()
            .encode(
                x=alt.X("months_since_cohort:O", title="Months Since Cohort"),
                y=alt.Y("cohort_month:T", title="Cohort"),
                color=alt.Color("retention:Q", title="Retention", scale=alt.Scale(scheme="blues")),
                tooltip=[
                    alt.Tooltip("cohort_month:T", title="Cohort"),
                    alt.Tooltip("months_since_cohort:Q", title="Months"),
                    alt.Tooltip("retention:Q", title="Retention", format=".2f"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(heat, use_container_width=True)
    else:
        st.info("No data yet in mart_retention_monthly.")

def render_rr():
    st.subheader("Returns & Review Quality (Daily, last ~180 data days)")
    dfd = run_sql_cached(Q_RETURNS_DAILY)
    if not dfd.empty:
        dfd["order_date"] = pd.to_datetime(dfd["order_date"])

        bars = (
            alt.Chart(dfd)
            .mark_bar(opacity=0.35)
            .encode(
                x=alt.X("order_date:T", title="order_date"),
                y=alt.Y("returns:Q", title="Returns"),
                tooltip=[alt.Tooltip("order_date:T", title="Date"),
                         alt.Tooltip("returns:Q", title="Returns", format=",.0f")],
            )
            .properties(height=280)
        )

        line = (
            alt.Chart(dfd)
            .mark_line(point=True)
            .encode(
                x=alt.X("order_date:T", title="order_date"),
                y=alt.Y("avg_review_score:Q", title="Avg Review Score (1–5)"),
                tooltip=[alt.Tooltip("order_date:T", title="Date"),
                         alt.Tooltip("avg_review_score:Q", title="Avg Score")],
            )
            .properties(height=280)
        )

        c1, c2 = st.columns([2, 2])
        with c1:
            st.altair_chart(bars, use_container_width=True)
        with c2:
            st.altair_chart(line, use_container_width=True)
    else:
        st.info("No daily returns data yet.")

    st.subheader("Returns & Review Quality (Monthly)")
    dfm = run_sql_cached(Q_RETURNS_MONTHLY)
    if not dfm.empty:
        dfm["order_month"] = pd.to_datetime(dfm["order_month"])
        monthly = (
            alt.Chart(dfm)
            .mark_bar()
            .encode(
                x=alt.X("order_month:T", title="order_month"),
                y=alt.Y("returns:Q", title="returns"),
                tooltip=[alt.Tooltip("order_month:T", title="Month"),
                         alt.Tooltip("returns:Q", title="Returns", format=",.0f")],
            )
            .properties(height=280)
        )
        st.altair_chart(monthly, use_container_width=True)
    else:
        st.info("No monthly returns data yet.")

def render_mkt():
    st.subheader("Marketing ROI (last ~180 data days)")

    # Top: ROAS timeline (spend > 0)
    roas = run_sql_cached(Q_MARKETING_ROAS)
    if not roas.empty:
        roas["day"] = pd.to_datetime(roas["day"])
        roas_chart = (
            alt.Chart(roas)
            .mark_line()
            .encode(
                x=alt.X("day:T", title="day"),
                y=alt.Y("roas:Q", title="ROAS / ROMI"),
                tooltip=[alt.Tooltip("day:T", title="Day"),
                         alt.Tooltip("roas:Q", title="ROAS", format=".2f")],
            )
            .properties(height=250)
        )
        st.altair_chart(roas_chart, use_container_width=True)
    else:
        st.info("No ROAS points (spend > 0) in the selected window.")

    # Bottom: Spend vs Gross Revenue
    series = run_sql_cached(Q_MARKETING_SERIES)
    if not series.empty:
        series["day"] = pd.to_datetime(series["day"])
        lines = (
            alt.Chart(series)
            .mark_line()
            .encode(
                x=alt.X("day:T", title="day"),
                y=alt.Y("value:Q", title="Value"),
                color=alt.Color("metric:N", title="metric"),
                tooltip=[alt.Tooltip("day:T", title="Day"),
                         alt.Tooltip("metric:N", title="Metric"),
                         alt.Tooltip("value:Q", title="Value", format=",.0f")],
            )
            .properties(height=320)
        )
        st.altair_chart(lines, use_container_width=True)
    else:
        st.info("No marketing series to plot.")

# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------

def render():
    st.set_page_config(page_title="E-commerce Analytics (Olist)", layout="wide")
    tabs = st.tabs(["Overview", "Cohorts & LTV", "Returns & Reviews", "Marketing"])

    with tabs[0]:
        render_overview()
    with tabs[1]:
        render_cohorts()
    with tabs[2]:
        render_rr()
    with tabs[3]:
        render_mkt()
