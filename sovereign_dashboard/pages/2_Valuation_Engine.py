import sys
from pathlib import Path

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

sys.path.append(str(Path(__file__).resolve().parent.parent))
from engines import valuation_engine

# ==========================================
# 1. PAGE CONFIGURATION & ARCHITECTURE SETUP
# ==========================================
st.set_page_config(page_title="Sovereign Valuation Engine v1.2", layout="wide")

MODEL_VERSION = "v1.2-Final"
st.title("🛡️ Sovereign Valuation & Discipline Engine")
st.caption(f"Model Version: {MODEL_VERSION} | Data Cache TTL: 24 Hours | Structural Framework Control")
st.subheader("Capital Preservation & Posture Assessment Cockpit")

# Scoring/data-fetch logic now lives in engines/valuation_engine.py so Home.py
# (the combined Conviction dashboard) and this standalone page share one
# implementation instead of two copies that could drift apart.
STATUS_LEGEND = valuation_engine.STATUS_LEGEND
DEFAULT_CORE = valuation_engine.DEFAULT_CORE
calculate_data_quality = valuation_engine.calculate_data_quality
classify_action = valuation_engine.classify_action
style_batch_status = valuation_engine.style_batch_status
calculate_distribution_diagnostics = valuation_engine.calculate_distribution_diagnostics
calculate_robust_z_score = valuation_engine.calculate_robust_z_score
sovereign_allocation_engine = valuation_engine.sovereign_allocation_engine
get_hardened_valuation_data = valuation_engine.get_hardened_valuation_data


# ==========================================
# 5. BATCH CORE SCANNER COMPONENT
# ==========================================
if batch_mode:
    st.markdown("### 👑 Sovereign Core Portfolio Scanner Matrix")
    batch_records = []
    
    with st.spinner("Executing structural data metrics sweep over Core list..."):
        for token in sorted(SOVEREIGN_CORE):
            b_df, b_err, b_freq, b_fx = get_hardened_valuation_data(token, lookback_years)
            if b_df is not None and not b_df.empty:
                b_curr = b_df["PS_Ratio"].iloc[-1]
                b_mean = b_df["PS_Ratio"].mean()
                b_std = b_df["PS_Ratio"].std()
                
                # Asynchronous guard isolating individual ticker division metrics from NaN faults
                if b_std and not np.isnan(b_std) and b_std != 0:
                    b_z = (b_curr - b_mean) / b_std
                else:
                    b_z = 0.0
                
                b_rob_z, b_med, b_mad = calculate_robust_z_score(b_df["PS_Ratio"], b_curr)
                b_diag = calculate_distribution_diagnostics(b_df["PS_Ratio"], b_curr)
                
                floors_cfg = {'crunch': core_crunch_floor, 'transition': core_transition_floor, 'expansion': core_expansion_floor}
                b_stance, b_mult, _, _ = sovereign_allocation_engine(
                    token, token in SOVEREIGN_CORE, b_z, b_rob_z, z_threshold, b_diag["percentile"], b_diag["skewness"], macro_mode, floors_cfg
                )
                b_posture = classify_action(b_mult)
                
                batch_records.append({
                    "Ticker": token,
                    "Current Posture": b_posture,
                    "Status Box": b_stance,
                    "Current P/S": f"{b_curr:.2f}",
                    "Standard Z": f"{b_z:.2f}",
                    "Robust Z": f"{b_rob_z:.2f}",
                    "Percentile": f"{b_diag['percentile']:.1f}%",
                    "Scale Mult": f"{b_mult:.2f}x",
                    "Error Logs": ""
                })
            else:
                batch_records.append({
                    "Ticker": token, "Current Posture": "⚠️ Scan Fault", "Status Box": "Data Empty/Error",
                    "Current P/S": "-", "Standard Z": "-", "Robust Z": "-", "Percentile": "-", "Scale Mult": "-",
                    "Error Logs": b_err if b_err else "Data retrieval execution failure"
                })
    
    batch_df = pd.DataFrame(batch_records)
    st.dataframe(
        batch_df.style.map(style_batch_status, subset=["Status Box"]),
        use_container_width=True,
        hide_index=True
    )
    
    # Render aggregate diagnostic counts underneath the batch matrix
    halt_count = batch_df["Status Box"].astype(str).str.contains("Halt").sum()
    scarcity_count = batch_df["Status Box"].astype(str).str.contains("Scarcity").sum()
    value_count = batch_df["Status Box"].astype(str).str.contains("Value").sum()
    fault_count = batch_df["Current Posture"].astype(str).str.contains("Fault").sum()

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Deep Value Signals", int(value_count))
    s2.metric("Scarcity Premiums Detected", int(scarcity_count))
    s3.metric("Hard Pause Signals", int(halt_count))
    s4.metric("Logged Scan Faults", int(fault_count))
    st.markdown("---")

# ==========================================
# 6. STREAMLIT APPLICATION INTERFACE RENDER
# ==========================================
ticker_input = st.text_input("Enter Focus Capital Symbol (e.g. FNV, TPL, ASML, PANW):", value="PANW").upper().strip()

if ticker_input:
    is_core = ticker_input in SOVEREIGN_CORE
    
    with st.spinner(f"Splicing matrix components for {ticker_input}..."):
        df_data, error, report_freq, fx_note = get_hardened_valuation_data(ticker_input, lookback_years)

        if error:
            st.error(f"Engine Interruption: {error}")
        elif df_data is not None and not df_data.empty:
            
            # Minimum observation safety threshold gauge
            if len(df_data) < 60:
                st.warning(f"Only {len(df_data)} valid valuation observations are available inside this window. Structural statistical confidence is limited.")
            
            # Base variables compilation
            current_ps = df_data["PS_Ratio"].iloc[-1]
            mean_ps = df_data["PS_Ratio"].mean()
            std_ps = df_data["PS_Ratio"].std()
            
            # Unified Distribution Metrics Compilation Block
            p10 = df_data["PS_Ratio"].quantile(0.10)
            p50 = df_data["PS_Ratio"].quantile(0.50)
            p90 = df_data["PS_Ratio"].quantile(0.90)
            p95 = df_data["PS_Ratio"].quantile(0.95)
            
            max_ps = df_data["PS_Ratio"].max()
            valuation_drawdown = (current_ps / max_ps - 1) * 100 if max_ps and max_ps != 0 else 0.0
            
            current_price = df_data["Close"].iloc[-1]
            current_market_cap = df_data["Market_Cap"].iloc[-1]
            
            if std_ps and not np.isnan(std_ps) and std_ps != 0:
                z_score = (current_ps - mean_ps) / std_ps
            else:
                z_score = 0.0
            
            robust_z_score, median_ps, mad_ps = calculate_robust_z_score(df_data["PS_Ratio"], current_ps)
            diags = calculate_distribution_diagnostics(df_data["PS_Ratio"], current_ps)
            
            floors_config = {'crunch': core_crunch_floor, 'transition': core_transition_floor, 'expansion': core_expansion_floor}

            # Run Architecture Posture Allocation Engine
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

            # Compute capital positioning layers
            model_deployment_amount = base_tranche * allocation_multiplier
            reserved_cash = max(base_tranche - model_deployment_amount, 0.0)
            action_class = classify_action(allocation_multiplier)
            data_quality = calculate_data_quality(df_data, report_freq, fx_note)

            # Identity Status Layout Banner Cards
            c1, c2 = st.columns([1, 3])
            with c1:
                if is_core:
                    st.success(f"👑 **SOVEREIGN CORE ACTIVE**\n\nAllocation floor protection applied")
                else:
                    st.warning(f"⚔️ **TACTICAL LAYER EXPOSURE**\n\nPausable pacing framework active")
            with c2:
                st.info(
                    f"**Statistical Profile:** {diags['shape']} "
                    f"| Realized Skewness: {diags['skewness']:.2f} "
                    f"| Realized Rank Percentile: {diags['percentile']:.1f}% "
                    f"| Distribution Trust Profile: {distribution_reliability}"
                )

            st.caption(f"💵 Latest Close Price: {current_price:,.2f} | Estimated Market Capitalization: {current_market_cap:,.0f}")
            st.caption(f"🧪 Analytical Health Matrix: {data_quality}")
            if fx_note:
                st.caption(f"🌐 Currency Matrix: {fx_note}")

            # 6-Column Metrics Bar Setup
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Current P/S", f"{current_ps:.2f}")
            m2.metric(f"{lookback_years}Y Mean", f"{mean_ps:.2f}")
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

            # Allocation Ticket Output Framework Render 
            st.markdown("### 🎫 Model Posture Assessment Ticket")
            box_bg = "#1e293b"
            border_line = "#3b82f6" if is_core else "#f97316"
            
            st.markdown(
                f"<div style='padding: 22px; background-color: {box_bg}; border-radius: 8px; border-left: 8px solid {border_line};'>"
                f"<h4>Target Tracking Asset: <b>{ticker_input}</b> | Core Tier Designation Status: {'TRUE' if is_core else 'FALSE'}</h4>"
                f"<ul>"
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
            st.caption("⚡ *Model parameters represent a closed-loop rule-based systematic risk management protocol and do not describe personalized financial or investment advice.*")

            # Model Posture Narrative Panel Interpretation Block
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

            # Chart Block 1: Structural vs Robust Multi-Regime Mapping Engine
            st.markdown("---")
            
            # Protect Standard Deviation Limit Band Logic from NaN Pollution
            if std_ps and not np.isnan(std_ps) and std_ps != 0:
                upper_band = mean_ps + (z_threshold * std_ps)
                lower_band = mean_ps - (z_threshold * std_ps)
            else:
                upper_band = np.nan
                lower_band = np.nan
            
            if not np.isnan(median_ps) and not np.isnan(mad_ps) and mad_ps != 0:
                # 0.6745 decompresses the robust MAD scale factor to project comparable standard deviation boundaries
                robust_upper = median_ps + (z_threshold * mad_ps / 0.6745)
                robust_lower = median_ps - (z_threshold * mad_ps / 0.6745)
            else:
                robust_upper = np.nan
                robust_lower = np.nan
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_data.index, y=df_data["PS_Ratio"], name="Realized Price-to-Sales Path", line=dict(color="#ffffff", width=2.5)))
            
            # Mean and Standard Deviation Tracks
            fig.add_trace(go.Scatter(x=df_data.index, y=[mean_ps] * len(df_data), name="Mean Boundary Reference", line=dict(color="#94a3b8", dash="dash")))
            
            if not np.isnan(upper_band):
                fig.add_trace(go.Scatter(x=df_data.index, y=[upper_band] * len(df_data), name=f"Standard Limit High (+{z_threshold}σ)", line=dict(color="#ef4444", width=1.5)))
            if not np.isnan(lower_band):
                fig.add_trace(go.Scatter(x=df_data.index, y=[lower_band] * len(df_data), name=f"Standard Limit Low (-{z_threshold}σ)", line=dict(color="#22c55e", width=1.5)))
            
            # Robust MAD statistical overlays
            if not np.isnan(median_ps):
                fig.add_trace(go.Scatter(x=df_data.index, y=[median_ps] * len(df_data), name="Robust Distribution Median", line=dict(color="#cbd5e1", dash="dot", width=1)))
            if not np.isnan(robust_upper):
                fig.add_trace(go.Scatter(x=df_data.index, y=[robust_upper] * len(df_data), name=f"Robust High Band (+{z_threshold}σ MAD)", line=dict(color="#a855f7", dash="longdashdot", width=1.5)))
            if not np.isnan(robust_lower):
                fig.add_trace(go.Scatter(x=df_data.index, y=[robust_lower] * len(df_data), name=f"Robust Low Band (-{z_threshold}σ MAD)", line=dict(color="#a3e635", dash="longdashdot", width=1.5)))

            # Aligned Distribution Percentile Bands
            fig.add_trace(go.Scatter(x=df_data.index, y=[p10] * len(df_data), name="10th Percentile Value Floor", line=dict(color="#4ade80", dash="dashdot", width=1)))
            fig.add_trace(go.Scatter(x=df_data.index, y=[p90] * len(df_data), name="90th Percentile Premium Zone", line=dict(color="#fb923c", dash="dashdot", width=1)))
            fig.add_trace(go.Scatter(x=df_data.index, y=[p95] * len(df_data), name="95th Percentile Hard Barrier", line=dict(color="#f97316", dash="dashdot", width=1)))

            fig.update_layout(
                title=f"{ticker_input} Historical Valuation Framework (Standard Metrics vs Robust MAD & Percentile Boundaries)",
                xaxis_title="Timeline Calendar", yaxis_title="Price-to-Sales Multiple", template="plotly_dark",
                height=600, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)

            # Chart Block 2: Dynamic Tracking Trace Bypassing Zero Faults
            st.markdown("---")
            st.subheader("🛡️ Causal Dynamic Risk Tracking Trace")
            
            df_ts = df_data.copy()
            roll_mean = df_ts["PS_Ratio"].rolling(rolling_window).mean()
            roll_std = df_ts["PS_Ratio"].rolling(rolling_window).std()
            df_ts["Z_tactical"] = (df_ts["PS_Ratio"] - roll_mean) / roll_std.replace(0, np.nan)

            if show_causal:
                expanding_mean = df_ts["PS_Ratio"].expanding(min_periods=rolling_window).mean()
                expanding_std = df_ts["PS_Ratio"].expanding(min_periods=rolling_window).std()
                df_ts["Z_causal_expanding"] = (df_ts["PS_Ratio"] - expanding_mean) / expanding_std.replace(0, np.nan)

            df_ts = df_ts.replace([np.inf, -np.inf], np.nan)
            df_ts_plot = df_ts.dropna(subset=["Z_tactical"])

            if not df_ts_plot.empty:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=df_ts_plot.index, y=df_ts_plot["Z_tactical"], name="Rolling Window Tactical Z-Score", line=dict(color="#06b6d4", width=2)))
                
                if show_causal and "Z_causal_expanding" in df_ts.columns:
                    causal_plot = df_ts.dropna(subset=["Z_causal_expanding"])
                    if not causal_plot.empty:
                        fig2.add_trace(go.Scatter(
                            x=causal_plot.index, y=causal_plot["Z_causal_expanding"],
                            name="Lookahead-Free Expanding Window Causal Z-Score", line=dict(color="#ec4899", width=1.5, dash="dash")
                        ))

                fig2.add_hline(y=z_threshold, line=dict(color="#ef4444", dash="dot"), annotation_text=f"High Bound Pressure threshold (+{z_threshold}σ)")
                fig2.add_hline(y=-z_threshold, line=dict(color="#22c55e", dash="dot"), annotation_text=f"Low Bound Discount threshold (-{z_threshold}σ)")
                fig2.add_hline(y=0, line=dict(color="#64748b", dash="dash"))
                
                fig2.update_layout(
                    title=f"{ticker_input} Rolling Historical Valuation Internal Pressure Waveforms",
                    xaxis_title="Timeline Calendar", yaxis_title="Standard Deviations (σ)", template="plotly_dark",
                    height=450, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("Insufficient valid rolling-window observations to populate the dynamic Z-score trace.")

            # Chart Block 3: Empirical Valuation Footprint Breakdown
            st.markdown("---")
            st.subheader("📊 Empirical Sample Density Distribution Topology")

            fig3 = go.Figure()
            fig3.add_trace(go.Histogram(
                x=df_data["PS_Ratio"], nbinsx=45, name="Realized Historical Observations", marker=dict(color="#475569")
            ))
            
            fig3.add_vline(x=current_ps, line_color="#22d3ee", line_width=3.5, annotation_text="Today Current Multiple")
            fig3.add_vline(x=mean_ps, line_color="#94a3b8", line_dash="dash", annotation_text="Sample Mean")
            fig3.add_vline(x=p10, line_color="#4ade80", line_dash="dot", annotation_text="10th Percentile Floor")
            fig3.add_vline(x=p50, line_color="#ffffff", line_dash="dash", annotation_text="Median Baseline")
            fig3.add_vline(x=p90, line_color="#fb923c", line_dash="dot", annotation_text="90th Percentile Premium Zone")
            fig3.add_vline(x=p95, line_color="#f87171", line_dash="dot", annotation_text="95th Percentile Extreme")

            fig3.update_layout(
                title=f"{ticker_input} Total Realized Sample Distribution Topology Map",
                xaxis_title="Price-to-Sales Multiple", yaxis_title="Historical Trading Frequency Count", template="plotly_dark",
                height=400
            )
            st.plotly_chart(fig3, use_container_width=True)

            with st.expander("📘 Systematic Framework Architecture Legend"):
                for stance, interpretation in STATUS_LEGEND.items():
                    st.markdown(f"**{stance}** — *{interpretation}*")
