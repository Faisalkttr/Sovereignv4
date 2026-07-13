"""
Sovereign Portfolio Engine
==========================
Two independent checks on the RESULT of your allocation decisions, not on
any single ticker:

  1. Concentration -- runs against structural_grid.py's actual target
     weights directly. No scan needed, no price data, works immediately.
  2. Correlation -- runs against a chosen ticker set (defaults to your
     most recent Home.py Structural Grid Scan if you've run one this
     session, else pick tickers manually) using real price history.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
from engines import portfolio_engine as pe
from structural_grid import NON_EQUITY_TICKERS, flatten_universe

st.set_page_config(page_title="Sovereign Portfolio Engine", page_icon="🧩", layout="wide")

st.title("🧩 Sovereign Portfolio Engine")
st.caption(
    f"Model Version: {pe.MODEL_VERSION} | Does the RESULT of your allocation decisions hold up -- "
    "position sizing, layer/section limits, cash buffer, and cross-ticker correlation?"
)

tab_concentration, tab_correlation = st.tabs(["📐 Concentration", "🔗 Correlation"])

# ========================================================================
# TAB 1: Concentration -- pure arithmetic on structural_grid.py, no fetch
# ========================================================================
with tab_concentration:
    st.subheader("📐 Structural Grid Concentration Check")
    st.caption(
        "Runs directly against structural_grid.py's target weights -- reflects your intended "
        "portfolio, not any particular scan. Re-run any time you edit the grid."
    )

    c1, c2, c3, c4 = st.columns(4)
    max_position = c1.number_input("Max single position", value=10.0, min_value=1.0, max_value=100.0, step=1.0,
                                    help="As % of total portfolio. Applies to individual equity tickers only "
                                         "-- BTC/GOLD/CASH are deliberate sleeves, not flagged here.") / 100.0
    max_layer = c2.number_input("Max single layer", value=15.0, min_value=1.0, max_value=100.0, step=1.0) / 100.0
    max_section = c3.number_input("Max single section", value=25.0, min_value=1.0, max_value=100.0, step=1.0) / 100.0
    min_cash = c4.number_input("Min cash buffer", value=10.0, min_value=0.0, max_value=100.0, step=1.0) / 100.0

    limits = {
        "max_single_position": max_position, "max_layer": max_layer,
        "max_section": max_section, "min_cash_buffer": min_cash,
    }

    universe = flatten_universe()
    result = pe.check_concentration(universe, limits=limits)

    n_breaches = (len(result["position_breaches"]) + len(result["layer_breaches"])
                  + len(result["section_breaches"]))
    cash_ok = result["cash_buffer"]["sufficient"]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Position breaches", len(result["position_breaches"]))
    k2.metric("Layer breaches", len(result["layer_breaches"]))
    k3.metric("Section breaches", len(result["section_breaches"]))
    k4.metric("Cash buffer", f"{result['cash_buffer']['weight']:.1%}",
              delta="OK" if cash_ok else f"-{result['cash_buffer']['shortfall']:.1%} short",
              delta_color="normal" if cash_ok else "inverse")

    if n_breaches == 0 and cash_ok:
        st.success("✅ No concentration breaches at current limits.")
    else:
        st.warning(f"⚠️ {n_breaches} concentration breach(es) found at current limits.")

    st.divider()

    st.subheader("Section weights")
    section_totals = result["section_totals"]
    fig = go.Figure(go.Bar(
        x=list(section_totals.values()), y=list(section_totals.keys()), orientation="h",
        marker=dict(color=["#dc2626" if v > max_section else "#4dd68c" for v in section_totals.values()]),
        text=[f"{v:.1%}" for v in section_totals.values()], textposition="outside",
    ))
    fig.add_vline(x=max_section, line_dash="dash", line_color="#dc2626",
                  annotation_text=f"Section limit ({max_section:.0%})")
    fig.update_layout(height=320, margin=dict(l=10, r=40, t=10, b=10), xaxis_tickformat=".0%",
                       xaxis_title="Target weight", showlegend=False)
    st.plotly_chart(fig, width="stretch")

    if result["position_breaches"]:
        st.subheader("🔴 Position breaches")
        st.dataframe(pd.DataFrame(result["position_breaches"]).assign(
            weight=lambda d: d["weight"].map(lambda x: f"{x:.2%}"),
            limit=lambda d: d["limit"].map(lambda x: f"{x:.2%}"),
            excess=lambda d: d["excess"].map(lambda x: f"{x:.2%}"),
        ), width="stretch", hide_index=True)

    if result["layer_breaches"]:
        st.subheader("🔴 Layer breaches")
        st.dataframe(pd.DataFrame(result["layer_breaches"]).assign(
            weight=lambda d: d["weight"].map(lambda x: f"{x:.2%}"),
            limit=lambda d: d["limit"].map(lambda x: f"{x:.2%}"),
            excess=lambda d: d["excess"].map(lambda x: f"{x:.2%}"),
        ), width="stretch", hide_index=True)

    if result["section_breaches"]:
        st.subheader("🔴 Section breaches")
        st.dataframe(pd.DataFrame(result["section_breaches"]).assign(
            weight=lambda d: d["weight"].map(lambda x: f"{x:.2%}"),
            limit=lambda d: d["limit"].map(lambda x: f"{x:.2%}"),
            excess=lambda d: d["excess"].map(lambda x: f"{x:.2%}"),
        ), width="stretch", hide_index=True)

    with st.expander("Full layer breakdown"):
        layer_display = result["layer_totals"].copy()
        layer_display["effective_weight"] = layer_display["effective_weight"].map(lambda x: f"{x:.2%}")
        st.dataframe(layer_display, width="stretch", hide_index=True)

# ========================================================================
# TAB 2: Correlation -- needs a ticker set + real price data
# ========================================================================
with tab_correlation:
    st.subheader("🔗 Cross-Ticker Correlation")
    st.caption(
        "Are your different bets actually the same bet wearing different tickers? Flags pairs "
        "whose daily returns move together above the threshold, and merges overlapping pairs "
        "into clusters."
    )

    last_scan = st.session_state.get("last_grid_scan_tickers")

    source = st.radio(
        "Ticker source",
        options=(["Last Home.py Structural Grid Scan", "Pick manually"] if last_scan
                 else ["Pick manually"]),
        horizontal=True,
    )

    if source == "Last Home.py Structural Grid Scan" and last_scan:
        corr_tickers = last_scan
        st.caption(f"Using {len(corr_tickers)} ticker(s) from your last scan: {', '.join(corr_tickers)}")
    else:
        universe = flatten_universe()
        all_equity_tickers = sorted(t for t in {r["ticker"] for r in universe} if t not in NON_EQUITY_TICKERS)
        corr_tickers = st.multiselect(
            "Tickers to check", options=all_equity_tickers, default=all_equity_tickers[:10],
        )

    cc1, cc2 = st.columns(2)
    lookback = cc1.selectbox("Price lookback", options=["6mo", "1y", "2y"], index=1)
    corr_threshold = cc2.slider("Correlation flag threshold", min_value=0.5, max_value=0.99, value=0.80, step=0.05)

    run_corr = st.button("🔗 Analyze Correlation", type="primary")

    if not run_corr:
        st.info("Pick your tickers and click **Analyze Correlation**.")
    elif len(corr_tickers) < 2:
        st.warning("Need at least 2 tickers to compute correlation.")
    else:
        with st.spinner(f"Fetching price history for {len(corr_tickers)} tickers..."):
            returns_df, failed = pe.get_price_returns(tuple(corr_tickers), period=lookback)

        if failed:
            st.warning(f"⚠️ Could not fetch price data for: {', '.join(failed)}")

        if returns_df.empty or returns_df.shape[1] < 2:
            st.error("Not enough price data resolved to compute correlation.")
        else:
            corr_matrix = pe.compute_correlation_matrix(returns_df)
            pairs = pe.flag_correlated_pairs(corr_matrix, threshold=corr_threshold)
            clusters = pe.cluster_correlated_groups(pairs)

            k1, k2, k3 = st.columns(3)
            k1.metric("Tickers analyzed", corr_matrix.shape[0])
            k2.metric("Flagged pairs", len(pairs))
            k3.metric("Correlated clusters", len(clusters))

            st.subheader("Correlation heatmap")
            fig = go.Figure(go.Heatmap(
                z=corr_matrix.values, x=corr_matrix.columns, y=corr_matrix.columns,
                colorscale=[[0, "#1e3a8a"], [0.5, "#1e293b"], [1, "#dc2626"]], zmin=-1, zmax=1,
                text=corr_matrix.round(2).values, texttemplate="%{text}",
            ))
            fig.update_layout(height=max(400, 30 * corr_matrix.shape[0]), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")

            if clusters:
                st.subheader(f"🔴 {len(clusters)} correlated cluster(s) (threshold ≥ {corr_threshold:.2f})")
                for i, cluster in enumerate(clusters, 1):
                    st.markdown(f"**Cluster {i}:** {', '.join(sorted(cluster))}")
                    st.caption(
                        "These move together above your threshold -- holding all of them isn't as "
                        "diversified as the ticker count suggests."
                    )
            else:
                st.success(f"✅ No pairs above the {corr_threshold:.2f} correlation threshold.")

            if pairs:
                with st.expander("All flagged pairs"):
                    pairs_df = pd.DataFrame(pairs)
                    pairs_df["correlation"] = pairs_df["correlation"].map(lambda x: f"{x:.3f}")
                    st.dataframe(pairs_df, width="stretch", hide_index=True)

            # Combined health verdict once both checks have run this session
            concentration_result = pe.check_concentration(flatten_universe())
            health = pe.classify_portfolio_health(concentration_result, pairs)
            st.divider()
            st.subheader(f"Overall portfolio health: {health}")

st.caption(
    "Concentration limits and the correlation threshold are explicit, editable policy (DEFAULT_LIMITS "
    "in engines/portfolio_engine.py / the inputs above), not a universal 'correct' answer -- set them to "
    "match your actual risk tolerance. Price data via yfinance; informational only, not investment advice."
)
