"""
Standalone single-ticker view for the Sovereign Quality Engine.
Mirrors the layout of pages/1 and pages/2: sidebar input -> run -> metric
cards -> a bar chart of the five component scores.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from engines import quality_engine

st.set_page_config(page_title="Sovereign Quality Engine", page_icon="🏗️", layout="wide")

st.title("🏗️ Sovereign Quality Engine")
st.caption(
    f"Model Version: {quality_engine.MODEL_VERSION} | "
    "Is this a GOOD business -- independent of price, priced-in growth, or macro timing?"
)

with st.expander("Status legend"):
    for label, description in quality_engine.QUALITY_STATUS_LEGEND.items():
        st.markdown(f"**{label}**  \n{description}")

st.sidebar.title("🏗️ Quality Engine")
ticker_input = st.sidebar.text_input("Ticker", value="AAPL").strip().upper()
run_clicked = st.sidebar.button("Run Analysis", type="primary", use_container_width=True)

if not ticker_input:
    st.info("Enter a ticker in the sidebar and click **Run Analysis**.")
    st.stop()

if not run_clicked and "quality_last_result" not in st.session_state:
    st.info("Click **Run Analysis** in the sidebar to fetch statements and score the business.")
    st.stop()

if run_clicked:
    with st.spinner(f"Fetching financial statements for {ticker_input}..."):
        metrics, error = quality_engine.get_quality_data(ticker_input)
    if error or metrics is None:
        st.error(f"Could not complete analysis: {error}")
        st.stop()
    result = quality_engine.compute_quality_score(ticker_input, metrics)
    st.session_state["quality_last_result"] = (ticker_input, metrics, result)

shown_ticker, metrics, result = st.session_state["quality_last_result"]

st.subheader(f"{shown_ticker} — {result['classification']}")

if result["sector_caveat"]:
    st.warning(f"⚠️ {result['sector_caveat']}")

if result["available_weight"] < 0.999 and result["available_weight"] > 0:
    st.info(
        f"Only {result['available_weight']*100:.0f}% of the normal metric weight was resolvable from "
        f"available statement rows for this ticker -- the Quality Score above is re-normalized over "
        f"whichever metrics were available, and is less complete than a full-data read."
    )

score = result["quality_score"]
if not np.isnan(score):
    st.progress(min(max(score / 100, 0.0), 1.0))
    st.caption(f"Quality Score: {score:.1f} / 100")

st.divider()

st.subheader("Component Metrics")


def fmt_pct(x):
    return f"{x:.1%}" if x == x and np.isfinite(x) else "N/A"


def fmt_ratio(x):
    return f"{x:.2f}x" if x == x and np.isfinite(x) else "N/A"


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("ROIC", fmt_pct(metrics.get("roic")), help="NOPAT / Invested Capital")
c2.metric("Gross Margin", fmt_pct(metrics.get("gross_margin")))
c3.metric("FCF Margin", fmt_pct(metrics.get("fcf_margin")))
c4.metric("Net Debt / EBITDA", fmt_ratio(metrics.get("net_debt_to_ebitda")))
c5.metric("Share Dilution (YoY)", fmt_pct(metrics.get("dilution_rate")))

st.divider()

st.subheader("Component Scores (0-100)")

comp = result["component_scores"]
labels = {"roic": "ROIC", "gross_margin": "Gross Margin", "fcf_margin": "FCF Margin",
          "net_debt_to_ebitda": "Net Debt/EBITDA", "dilution_rate": "Dilution"}

chart_labels, chart_values = [], []
for key, label in labels.items():
    val = comp.get(key)
    if val == val:  # not NaN
        chart_labels.append(label)
        chart_values.append(val)

if chart_values:
    fig = go.Figure(go.Bar(
        x=chart_values, y=chart_labels, orientation="h",
        marker=dict(color=chart_values, colorscale=[[0, "#ff6b6b"], [0.5, "#ffb84d"], [1, "#4dd68c"]],
                    cmin=0, cmax=100),
        text=[f"{v:.0f}" for v in chart_values], textposition="outside",
    ))
    fig.update_layout(height=300, margin=dict(l=10, r=30, t=10, b=10), xaxis_range=[0, 105],
                       xaxis_title="Score", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No component scores available to chart.")

with st.expander("Raw statement components"):
    raw = {k.lstrip("_"): v for k, v in metrics.items() if k.startswith("_")}
    raw_df = pd.DataFrame([(k, v) for k, v in raw.items()], columns=["Component", "Value"])
    st.dataframe(raw_df, use_container_width=True, hide_index=True)

st.caption(
    "Scored against an explicit, editable threshold policy (QUALITY_THRESHOLDS in "
    "engines/quality_engine.py), not a universal 'true' standard -- edit it if your bar for "
    "ROIC/margins/leverage/dilution differs. Data sourced from Yahoo Finance via yfinance; "
    "annual statements, not TTM. Informational only, not investment advice."
)
