import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))

from engines import valuation_engine


# ======================================================================
# 1. PAGE CONFIGURATION & ARCHITECTURE SETUP
# ======================================================================

st.set_page_config(
    page_title="Sovereign Valuation Engine v4.2",
    layout="wide"
)

PAGE_VERSION = "v4.2-Sector-Aware"
ENGINE_VERSION = getattr(valuation_engine, "MODEL_VERSION", "unknown")

st.title("🛡️ Sovereign Valuation & Discipline Engine")
st.caption(
    f"Page Version: {PAGE_VERSION} | "
    f"Engine Version: {ENGINE_VERSION} | "
    f"Data Cache TTL: 24 Hours | "
    f"Sector-aware valuation framework"
)

st.subheader("Capital Preservation & Posture Assessment Cockpit")

STATUS_LEGEND = valuation_engine.STATUS_LEGEND
DEFAULT_CORE = valuation_engine.DEFAULT_CORE

calculate_data_quality = valuation_engine.calculate_data_quality
classify_action = valuation_engine.classify_action
style_batch_status = valuation_engine.style_batch_status
calculate_distribution_diagnostics = valuation_engine.calculate_distribution_diagnostics
calculate_robust_z_score = valuation_engine.calculate_robust_z_score
sovereign_allocation_engine = valuation_engine.sovereign_allocation_engine

SOVEREIGN_CORE = DEFAULT_CORE


# ======================================================================
# 2. VALUATION MODEL DISPLAY HELPERS
# ======================================================================

MODEL_LABELS = {
    "PS": "Price / Sales",
    "EV_EBIT": "EV / EBIT",
    "EV_EBITDA": "EV / EBITDA",
    "PB": "Price / Book",
    "P_FFO": "Price / FFO",
    "PB_FFO_FALLBACK": "Price / Book (FFO fallback)",
    "MANUAL OVERRIDE": "Manual Override",
    "ROYALTY OVERRIDE": "Royalty Override",
}


def valuation_model_label(model):
    """
    Converts raw valuation model tags into human-readable labels.
    """
    return MODEL_LABELS.get(str(model).upper(), str(model))


def choose_ratio_column(df_data):
    """
    Chooses the correct valuation ratio column.

    The v4.2 engine produces:

        Valuation_Ratio

    but keeps:

        PS_Ratio

    as a backward-compatible alias.

    Older engines only have:

        PS_Ratio
    """
    if df_data is not None and "Valuation_Ratio" in df_data.columns:
        return "Valuation_Ratio"

    return "PS_Ratio"


def fetch_valuation_bundle(ticker, years):
    """
    Fetches valuation data in a way that works with both:

    1. older valuation_engine.py
       get_hardened_valuation_data() -> 4-tuple

    2. newer v4.2 valuation_engine.py
       get_hardened_valuation_data_v2() -> 6-tuple

    This allows the page to become sector-aware without forcing
    Home.py to change.
    """
    if hasattr(valuation_engine, "get_hardened_valuation_data_v2"):
        return valuation_engine.get_hardened_valuation_data_v2(ticker, years)

    df_data, error, report_freq, fx_note = valuation_engine.get_hardened_valuation_data(
        ticker,
        years
    )

    sector = "UNKNOWN"
    valuation_model = "PS"

    if df_data is not None:
        sector = df_data.attrs.get("sector", "UNKNOWN")
        valuation_model = df_data.attrs.get("valuation_model", "PS")

    return (
        df_data,
        error,
        report_freq,
        fx_note,
        sector,
        valuation_model
    )


# ======================================================================
# 3. SIDEBAR CONTROLS
# ======================================================================

st.sidebar.header("📊 Valuation Engine Parameters")

lookback_years = st.sidebar.slider(
    "Historical Lookback (Years)",
    3,
    10,
    5
)

z_threshold = st.sidebar.number_input(
    "Z-Score Pressure Threshold (σ)",
    value=2.0,
    step=0.1
)

rolling_window = st.sidebar.slider(
    "Rolling Window (Observations)",
    20,
    250,
    60
)

show_causal = st.sidebar.checkbox(
    "Show Lookahead-Free Expanding Window Causal Z-Score",
    value=True
)

st.sidebar.header("🌐 Macro Liquidity Regime")

macro_mode = st.sidebar.selectbox(
    "Macro liquidity regime (feeds the Core Floor logic below)",
    options=[
        "🟢 Expansion Mode (Unrestricted System Liquidity)",
        "🟡 Transition / K-Polarization (Contracting Liquidity)",
        "🔴 Forced System Crunch / Active Asset Stripping",
    ],
    index=1,
)

st.sidebar.header("👑 Core Floor Settings")

core_crunch_floor = st.sidebar.number_input(
    "Core Crunch Floor",
    value=0.10,
    min_value=0.0,
    max_value=1.0,
    step=0.05
)

core_transition_floor = st.sidebar.number_input(
    "Core Transition Floor",
    value=0.25,
    min_value=0.0,
    max_value=1.0,
    step=0.05
)

core_expansion_floor = st.sidebar.number_input(
    "Core Expansion Floor",
    value=0.35,
    min_value=0.0,
    max_value=1.0,
    step=0.05
)

st.sidebar.header("💵 Capital Sizing")

base_tranche = st.sidebar.number_input(
    "Base Tranche Size",
    min_value=0.0,
    value=10000.0,
    step=500.0
)

st.sidebar.header("👑 Batch Scanner")

batch_mode = st.sidebar.checkbox(
    "Run Sovereign Core batch scan",
    value=False
)


# ======================================================================
# 4. BATCH CORE SCANNER COMPONENT
# ======================================================================

if batch_mode:
    st.markdown("### 👑 Sovereign Core Portfolio Scanner Matrix")

    batch_records = []

    with st.spinner("Executing structural data metrics sweep over Core list..."):
        for token in sorted(SOVEREIGN_CORE):
            (
                b_df,
                b_err,
                b_freq,
                b_fx,
                b_sector,
                b_model
            ) = fetch_valuation_bundle(token, lookback_years)

            if b_df is not None and not b_df.empty:
                ratio_col = choose_ratio_column(b_df)

                if ratio_col not in b_df.columns:
                    batch_records.append({
                        "Ticker": token,
                        "Sector": b_sector,
                        "Model": valuation_model_label(b_model),
                        "Current Posture": "⚠️ Scan Fault",
                        "Status Box": "Data Empty/Error",
                        "Current Ratio": "-",
                        "Standard Z": "-",
                        "Robust Z": "-",
                        "Percentile": "-",
                        "Scale Mult": "-",
                        "Error Logs": "Valuation ratio column unavailable."
                    })
                    continue

                b_series = b_df[ratio_col].replace([np.inf, -np.inf], np.nan).dropna()

                if b_series.empty:
                    batch_records.append({
                        "Ticker": token,
                        "Sector": b_sector,
                        "Model": valuation_model_label(b_model),
                        "Current Posture": "⚠️ Scan Fault",
                        "Status Box": "Data Empty/Error",
                        "Current Ratio": "-",
                        "Standard Z": "-",
                        "Robust Z": "-",
                        "Percentile": "-",
                        "Scale Mult": "-",
                        "Error Logs": "Valuation ratio series empty after cleaning."
                    })
                    continue

                b_curr = float(b_series.iloc[-1])
                b_mean = float(b_series.mean())
                b_std = float(b_series.std())

                if b_std and not np.isnan(b_std) and b_std != 0:
                    b_z = (b_curr - b_mean) / b_std
                else:
                    b_z = 0.0

                b_rob_z, _, _ = calculate_robust_z_score(b_series, b_curr)
                b_diag = calculate_distribution_diagnostics(b_series, b_curr)

                floors_cfg = {
                    "crunch": core_crunch_floor,
                    "transition": core_transition_floor,
                    "expansion": core_expansion_floor
                }

                b_stance, b_mult, _, _ = sovereign_allocation_engine(
                    ticker=token,
                    is_core=token in SOVEREIGN_CORE,
                    z_score=b_z,
                    robust_z_score=b_rob_z,
                    z_threshold=z_threshold,
                    percentile=b_diag["percentile"],
                    skewness=b_diag["skewness"],
                    macro_mode=macro_mode,
                    floors=floors_cfg
                )

                b_posture = classify_action(b_mult)

                batch_records.append({
                    "Ticker": token,
                    "Sector": b_sector,
                    "Model": valuation_model_label(b_model),
                    "Current Posture": b_posture,
                    "Status Box": b_stance,
                    "Current Ratio": f"{b_curr:.2f}",
                    "Standard Z": f"{b_z:.2f}",
                    "Robust Z": f"{b_rob_z:.2f}",
                    "Percentile": f"{b_diag['percentile']:.1f}%",
                    "Scale Mult": f"{b_mult:.2f}x",
                    "Error Logs": ""
                })

            else:
                batch_records.append({
                    "Ticker": token,
                    "Sector": b_sector,
                    "Model": valuation_model_label(b_model),
                    "Current Posture": "⚠️ Scan Fault",
                    "Status Box": "Data Empty/Error",
                    "Current Ratio": "-",
                    "Standard Z": "-",
                    "Robust Z": "-",
                    "Percentile": "-",
                    "Scale Mult": "-",
                    "Error Logs": b_err if b_err else "Data retrieval execution failure"
                })

    batch_df = pd.DataFrame(batch_records)

    if not batch_df.empty:
        display_cols = [
            "Ticker",
            "Sector",
            "Model",
            "Current Posture",
            "Status Box",
            "Current Ratio",
            "Standard Z",
            "Robust Z",
            "Percentile",
            "Scale Mult",
            "Error Logs"
        ]

        st.dataframe(
            batch_df[display_cols].style.map(
                style_batch_status,
                subset=["Status Box"]
            ),
            use_container_width=True,
            hide_index=True
        )

        halt_count = batch_df["Status Box"].astype(str).str.contains("Halt").sum()
        scarcity_count = batch_df["Status Box"].astype(str).str.contains("Scarcity").sum()
        value_count = batch_df["Status Box"].astype(str).str.contains("Value").sum()
        fault_count = batch_df["Current Posture"].astype(str).str.contains("Fault").sum()

        s1, s2, s3, s4 = st.columns(4)

        s1.metric("Deep Value Signals", int(value_count))
        s2.metric("Scarcity Premiums Detected", int(scarcity_count))
        s3.metric("Hard Pause Signals", int(halt_count))
        s4.metric("Logged Scan Faults", int(fault_count))

    else:
        st.info("No batch scan records were produced.")

    st.markdown("---")


# ======================================================================
# 5. SINGLE TICKER INTERFACE
# ======================================================================

ticker_input = st.text_input(
    "Enter Focus Capital Symbol (e.g. FNV, TPL, ASML, PANW):",
    value="PANW"
).upper().strip()

if ticker_input:
    is_core = ticker_input in SOVEREIGN_CORE

    with st.spinner(f"Splicing matrix components for {ticker_input}..."):
        (
            df_data,
            error,
            report_freq,
            fx_note,
            sector,
            valuation_model
        ) = fetch_valuation_bundle(ticker_input, lookback_years)

    if error:
        st.error(f"Engine Interruption: {error}")

    elif df_data is not None and not df_data.empty:
        ratio_col = choose_ratio_column(df_data)

        if ratio_col not in df_data.columns:
            st.error(
                "Engine returned data but no usable valuation ratio column was found. "
                "Expected either 'Valuation_Ratio' or 'PS_Ratio'."
            )
            st.stop()

        ratio_series = df_data[ratio_col].replace([np.inf, -np.inf], np.nan).dropna()

        if ratio_series.empty:
            st.error("Valuation ratio series is empty after cleaning.")
            st.stop()

        ratio_label = valuation_model_label(valuation_model)

        if len(ratio_series) < 60:
            st.warning(
                f"Only {len(ratio_series)} valid valuation observations are available inside "
                f"this window. Structural statistical confidence is limited."
            )

        # --------------------------------------------------------------
        # Base variables compilation
        # --------------------------------------------------------------

        current_ratio = float(ratio_series.iloc[-1])
        mean_ratio = float(ratio_series.mean())
        std_ratio = float(ratio_series.std())

        p10 = float(ratio_series.quantile(0.10))
        p50 = float(ratio_series.quantile(0.50))
        p90 = float(ratio_series.quantile(0.90))
        p95 = float(ratio_series.quantile(0.95))
        max_ratio = float(ratio_series.max())

        valuation_drawdown = (
            (current_ratio / max_ratio - 1) * 100
            if max_ratio and max_ratio != 0
            else 0.0
        )

        current_price = (
            df_data["Close"].iloc[-1]
            if "Close" in df_data.columns
            else np.nan
        )

        current_market_cap = (
            df_data["Market_Cap"].iloc[-1]
            if "Market_Cap" in df_data.columns
            else np.nan
        )

        if std_ratio and not np.isnan(std_ratio) and std_ratio != 0:
            z_score = (current_ratio - mean_ratio) / std_ratio
        else:
            z_score = 0.0

        robust_z_score, median_ratio, mad_ratio = calculate_robust_z_score(
            ratio_series,
            current_ratio
        )

        diags = calculate_distribution_diagnostics(
            ratio_series,
            current_ratio
        )

        floors_config = {
            "crunch": core_crunch_floor,
            "transition": core_transition_floor,
            "expansion": core_expansion_floor
        }

        # --------------------------------------------------------------
        # Run Architecture Posture Allocation Engine
        # --------------------------------------------------------------

        status_stance, allocation_multiplier, explanation, distribution_reliability = sovereign_allocation_engine(
            ticker=ticker_input,
            is_core=is_core,
            z_score=z_score,
            robust_z_score=robust_z_score,
            z_threshold=z_threshold,
            percentile=diags["percentile"],
            skewness=diags["skewness"],
            macro_mode=macro_mode,
            floors=floors_config
        )

        model_deployment_amount = base_tranche * allocation_multiplier
        reserved_cash = max(base_tranche - model_deployment_amount, 0.0)

        action_class = classify_action(allocation_multiplier)
        data_quality = calculate_data_quality(df_data, report_freq, fx_note)

        # --------------------------------------------------------------
        # Identity Status Layout Banner Cards
        # --------------------------------------------------------------

        c1, c2 = st.columns([1, 3])

        with c1:
            if is_core:
                st.success(
                    "👑 **SOVEREIGN CORE ACTIVE**\n\n"
                    "Allocation floor protection applied"
                )
            else:
                st.warning(
                    "⚔️ **TACTICAL LAYER EXPOSURE**\n\n"
                    "Pausable pacing framework active"
                )

        with c2:
            st.info(
                f"**Statistical Profile:** {diags['shape']} "
                f"| Realized Skewness: {diags['skewness']:.2f} "
                f"| Realized Rank Percentile: {diags['percentile']:.1f}% "
                f"| Distribution Trust Profile: {distribution_reliability}"
            )

        st.caption(
            f"🧭 Sector: {sector} | "
            f"Valuation Model: {ratio_label}"
        )

        st.caption(
            f"💵 Latest Close Price: {current_price:,.2f} | "
            f"Estimated Market Capitalization: {current_market_cap:,.0f}"
        )

        st.caption(
            f"🧪 Analytical Health Matrix: {data_quality}"
        )

        if fx_note:
            st.caption(f"🌐 Currency Matrix: {fx_note}")

        # --------------------------------------------------------------
        # 6-Column Metrics Bar Setup
        # --------------------------------------------------------------

        m1, m2, m3, m4, m5, m6 = st.columns(6)

        m1.metric(f"Current {ratio_label}", f"{current_ratio:.2f}")
        m2.metric(f"{lookback_years}Y Mean", f"{mean_ratio:.2f}")
        m3.metric("Standard Z", f"{z_score:.2f}")
        m4.metric("Robust Z (MAD)", f"{robust_z_score:.2f}")
        m5.metric("Valuation Drawdown", f"{valuation_drawdown:.1f}%")

        if "Value" in status_stance:
            m6.info(status_stance)
        elif "Scarcity" in status_stance or "Regime" in status_stance:
            m6.subheader(status_stance)
        elif "Halt" in status_stance or "Fragility" in status_stance:
            m6.error(status_stance)
        elif "Premium" in status_stance or "Expectation" in status_stance:
            m6.warning(status_stance)
        else:
            m6.success(status_stance)

        # --------------------------------------------------------------
        # Allocation Ticket Output Framework Render
        # --------------------------------------------------------------

        st.markdown("### 🎫 Model Posture Assessment Ticket")

        box_bg = "#1e293b"
        border_line = "#3b82f6" if is_core else "#f97316"

        st.markdown(
            f"<div style='padding: 22px; background-color: {box_bg}; border-radius: 8px; border-left: 8px solid {border_line};'>"
            f"<h4>Target Tracking Asset: <b>{ticker_input}</b> | Core Tier Designation Status: {'TRUE' if is_core else 'FALSE'}</h4>"
            f"<ul>"
            f"<li><b>Sector Classification:</b> {sector}</li>"
            f"<li><b>Valuation Model:</b> {ratio_label}</li>"
            f"<li><b>Model Capital Posture:</b> <b>{action_class}</b></li>"
            f"<li><b>Macro System Condition Matrix:</b> {macro_mode}</li>"
            f"<li><b>Designated Input Target Base Single-Tranche:</b> {base_tranche:,.2f}</li>"
            f"<li><b>Deployment Velocity Scale Multiplier:</b> <b>{allocation_multiplier:.2f}x</b></li>"
            f"<li><b>Calculated Model Deployment Capital Amount:</b> <span style='font-size: 1.15em; color:#4ade80;'><b>{model_deployment_amount:,.2f}</b></span></li>"
            f"<li><b>Undeployed Capital Liquidity Cash Reserve (Optionality Buffer):</b> <span style='font-size: 1.15em; color:#f87171;'><b>{reserved_cash:,.2f}</b></span></li>"
            f"<li><b>System Logic Pipeline Routing:</b> {explanation}</li>"
            f"<li><b>Execution Hygiene Note:</b> If acting on the model externally, use disciplined limit-order behaviour and avoid chasing wide spreads or volatile openings.</li>"
            f"</ul>"
            f"</div>",
            unsafe_allow_html=True
        )

        st.caption(
            "⚡ *Model parameters represent a closed-loop rule-based systematic risk management protocol "
            "and do not describe personalized financial or investment advice.*"
        )

        # --------------------------------------------------------------
        # Model Posture Narrative Panel Interpretation Block
        # --------------------------------------------------------------

        st.markdown("### 🧭 Model Posture Interpretation")

        p1, p2, p3, p4 = st.columns(4)

        p1.metric("Core Classification", "Sovereign Core" if is_core else "Tactical Layer")
        p2.metric("Capital Posture", action_class)
        p3.metric("Liquidity Reserve Saved", f"{reserved_cash:,.2f}")
        p4.metric("Model Deployment Size", f"{model_deployment_amount:,.2f}")

        if is_core and allocation_multiplier > 0:
            st.info(
                "Sovereign Core logic is active. The model throttles deployment intensity when valuation pressure rises, "
                "but preserves a structural accumulation floor unless you manually change the core floor input fields."
            )
        elif not is_core and allocation_multiplier == 0:
            st.warning(
                "Tactical Layer pause is active. The model is preserving cash optionality because valuation pressure, macro regimes, "
                "or both are unfavorable for fresh position entry."
            )
        else:
            st.info(
                "The model balances micro-valuation metrics, skewness indices, and macro liquidity conditions to determine systemic capital pacing."
            )

        # --------------------------------------------------------------
        # Chart Block 1: Structural vs Robust Multi-Regime Mapping Engine
        # --------------------------------------------------------------

        st.markdown("---")

        if std_ratio and not np.isnan(std_ratio) and std_ratio != 0:
            upper_band = mean_ratio + (z_threshold * std_ratio)
            lower_band = mean_ratio - (z_threshold * std_ratio)
        else:
            upper_band = np.nan
            lower_band = np.nan

        if not np.isnan(median_ratio) and not np.isnan(mad_ratio) and mad_ratio != 0:
            robust_upper = median_ratio + (z_threshold * mad_ratio / 0.6745)
            robust_lower = median_ratio - (z_threshold * mad_ratio / 0.6745)
        else:
            robust_upper = np.nan
            robust_lower = np.nan

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=df_data.index,
                y=df_data[ratio_col],
                name=f"Realized {ratio_label} Path",
                line=dict(color="#ffffff", width=2.5)
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df_data.index,
                y=[mean_ratio] * len(df_data),
                name="Mean Boundary Reference",
                line=dict(color="#94a3b8", dash="dash")
            )
        )

        if not np.isnan(upper_band):
            fig.add_trace(
                go.Scatter(
                    x=df_data.index,
                    y=[upper_band] * len(df_data),
                    name=f"Standard Limit High (+{z_threshold}σ)",
                    line=dict(color="#ef4444", width=1.5)
                )
            )

        if not np.isnan(lower_band):
            fig.add_trace(
                go.Scatter(
                    x=df_data.index,
                    y=[lower_band] * len(df_data),
                    name=f"Standard Limit Low (-{z_threshold}σ)",
                    line=dict(color="#22c55e", width=1.5)
                )
            )

        if not np.isnan(median_ratio):
            fig.add_trace(
                go.Scatter(
                    x=df_data.index,
                    y=[median_ratio] * len(df_data),
                    name="Robust Distribution Median",
                    line=dict(color="#cbd5e1", dash="dot", width=1)
                )
            )

        if not np.isnan(robust_upper):
            fig.add_trace(
                go.Scatter(
                    x=df_data.index,
                    y=[robust_upper] * len(df_data),
                    name=f"Robust High Band (+{z_threshold}σ MAD)",
                    line=dict(color="#a855f7", dash="longdashdot", width=1.5)
                )
            )

        if not np.isnan(robust_lower):
            fig.add_trace(
                go.Scatter(
                    x=df_data.index,
                    y=[robust_lower] * len(df_data),
                    name=f"Robust Low Band (-{z_threshold}σ MAD)",
                    line=dict(color="#a3e635", dash="longdashdot", width=1.5)
                )
            )

        fig.add_trace(
            go.Scatter(
                x=df_data.index,
                y=[p10] * len(df_data),
                name="10th Percentile Value Floor",
                line=dict(color="#4ade80", dash="dashdot", width=1)
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df_data.index,
                y=[p90] * len(df_data),
                name="90th Percentile Premium Zone",
                line=dict(color="#fb923c", dash="dashdot", width=1)
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df_data.index,
                y=[p95] * len(df_data),
                name="95th Percentile Hard Barrier",
                line=dict(color="#f97316", dash="dashdot", width=1)
            )
        )

        fig.update_layout(
            title=(
                f"{ticker_input} Historical Valuation Framework "
                f"({ratio_label} — Standard Metrics vs Robust MAD & Percentile Boundaries)"
            ),
            xaxis_title="Timeline Calendar",
            yaxis_title=ratio_label,
            template="plotly_dark",
            height=600,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        st.plotly_chart(fig, use_container_width=True)

        # --------------------------------------------------------------
        # Chart Block 2: Dynamic Tracking Trace Bypassing Zero Faults
        # --------------------------------------------------------------

        st.markdown("---")
        st.subheader("🛡️ Causal Dynamic Risk Tracking Trace")

        df_ts = df_data.copy()

        roll_mean = df_ts[ratio_col].rolling(rolling_window).mean()
        roll_std = df_ts[ratio_col].rolling(rolling_window).std()

        df_ts["Z_tactical"] = (
            df_ts[ratio_col] - roll_mean
        ) / roll_std.replace(0, np.nan)

        if show_causal:
            expanding_mean = df_ts[ratio_col].expanding(min_periods=rolling_window).mean()
            expanding_std = df_ts[ratio_col].expanding(min_periods=rolling_window).std()

            df_ts["Z_causal_expanding"] = (
                df_ts[ratio_col] - expanding_mean
            ) / expanding_std.replace(0, np.nan)

        df_ts = df_ts.replace([np.inf, -np.inf], np.nan)
        df_ts_plot = df_ts.dropna(subset=["Z_tactical"])

        if not df_ts_plot.empty:
            fig2 = go.Figure()

            fig2.add_trace(
                go.Scatter(
                    x=df_ts_plot.index,
                    y=df_ts_plot["Z_tactical"],
                    name="Rolling Window Tactical Z-Score",
                    line=dict(color="#06b6d4", width=2)
                )
            )

            if show_causal and "Z_causal_expanding" in df_ts.columns:
                causal_plot = df_ts.dropna(subset=["Z_causal_expanding"])

                if not causal_plot.empty:
                    fig2.add_trace(
                        go.Scatter(
                            x=causal_plot.index,
                            y=causal_plot["Z_causal_expanding"],
                            name="Lookahead-Free Expanding Window Causal Z-Score",
                            line=dict(color="#ec4899", width=1.5, dash="dash")
                        )
                    )

            fig2.add_hline(
                y=z_threshold,
                line=dict(color="#ef4444", dash="dot"),
                annotation_text=f"High Bound Pressure threshold (+{z_threshold}σ)"
            )

            fig2.add_hline(
                y=-z_threshold,
                line=dict(color="#22c55e", dash="dot"),
                annotation_text=f"Low Bound Discount threshold (-{z_threshold}σ)"
            )

            fig2.add_hline(
                y=0,
                line=dict(color="#64748b", dash="dash")
            )

            fig2.update_layout(
                title=f"{ticker_input} Rolling Historical Valuation Internal Pressure Waveforms",
                xaxis_title="Timeline Calendar",
                yaxis_title="Standard Deviations (σ)",
                template="plotly_dark",
                height=450,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            st.plotly_chart(fig2, use_container_width=True)

        else:
            st.warning(
                "Insufficient valid rolling-window observations to populate the dynamic Z-score trace."
            )

        # --------------------------------------------------------------
        # Chart Block 3: Empirical Valuation Footprint Breakdown
        # --------------------------------------------------------------

        st.markdown("---")
        st.subheader("📊 Empirical Sample Density Distribution Topology")

        fig3 = go.Figure()

        fig3.add_trace(
            go.Histogram(
                x=ratio_series,
                nbinsx=45,
                name="Realized Historical Observations",
                marker=dict(color="#475569")
            )
        )

        fig3.add_vline(
            x=current_ratio,
            line_color="#22d3ee",
            line_width=3.5,
            annotation_text="Today Current Multiple"
        )

        fig3.add_vline(
            x=mean_ratio,
            line_color="#94a3b8",
            line_dash="dash",
            annotation_text="Sample Mean"
        )

        fig3.add_vline(
            x=p10,
            line_color="#4ade80",
            line_dash="dot",
            annotation_text="10th Percentile Floor"
        )

        fig3.add_vline(
            x=p50,
            line_color="#ffffff",
            line_dash="dash",
            annotation_text="Median Baseline"
        )

        fig3.add_vline(
            x=p90,
            line_color="#fb923c",
            line_dash="dot",
            annotation_text="90th Percentile Premium Zone"
        )

        fig3.add_vline(
            x=p95,
            line_color="#f87171",
            line_dash="dot",
            annotation_text="95th Percentile Extreme"
        )

        fig3.update_layout(
            title=f"{ticker_input} Total Realized Sample Distribution Topology Map",
            xaxis_title=ratio_label,
            yaxis_title="Historical Trading Frequency Count",
            template="plotly_dark",
            height=400
        )

        st.plotly_chart(fig3, use_container_width=True)

        with st.expander("📘 Systematic Framework Architecture Legend"):
            for stance, interpretation in STATUS_LEGEND.items():
                st.markdown(f"**{stance}** — *{interpretation}*")
