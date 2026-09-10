"""
Sovereign Conviction Engine -- combined dashboard.

This is the real version of the "paste a CSV, get a ranked Top 10" idea --
wired to your actual Expectations, Valuation, and Quality engines (not fake
manual 0-100 inputs).

TWO WAYS TO USE IT
  1. Structural Grid Scan -- scoped to the tickers in your allocation grid
     (structural_grid.py). Sizing uses each ticker's real structural target
     weight, so "Suggested $ Deployment" reflects your actual portfolio plan.
  2. Ad-Hoc Ticker Scan -- run the exact same three engines + blended
     Conviction Score on ANY ticker, including ones outside your current
     universe. No structural weight exists for these, so sizing is optional
     and uses a hypothetical weight % you enter yourself -- useful for
     vetting a new idea before deciding whether it belongs in the grid at all.

WHAT IT DOESN'T DO
  It does NOT re-implement the Macro Engine's FRED pipeline here (that's
  a portfolio-wide regime call, not a per-ticker one, and duplicating a
  1,400-line pipeline into this page would be its own maintenance burden).
  Instead, run the Macro Engine page separately and enter its output
  as the "Macro overlay multiplier" in the sidebar -- same manual-input
  philosophy the Macro Engine itself already uses for your allocation %
  and positioning inputs.
"""

import concurrent.futures
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))
from engines.expectations_engine import SovereignExpectationsEngine
from engines import valuation_engine
from engines import quality_engine
from structural_grid import (
    CORE_ELIGIBLE_TICKERS,
    NON_EQUITY_TICKERS,
    flatten_universe,
)

st.set_page_config(page_title="Sovereign Conviction Engine", page_icon="🏆", layout="wide")

st.title("🏆 Sovereign Conviction Engine")
st.caption(
    "Structural Grid + Valuation + Expectations + Quality engines -> ranked deployment table. "
    "Macro regime is a manual overlay -- run the Macro Engine page and enter its reading below."
)

UNIVERSE = flatten_universe()
UNIVERSE_DF = pd.DataFrame(UNIVERSE)

# ----------------------------------------------------------------------
# Sidebar controls (shared by both tabs)
# ----------------------------------------------------------------------

st.sidebar.header("💵 Portfolio Sizing")
total_portfolio_value = st.sidebar.number_input(
    "Total portfolio value", min_value=0.0, value=100000.0, step=1000.0,
    help="Used with each ticker's target weight (structural, or hypothetical in the Ad-Hoc tab) "
         "to size suggested $ deployment.",
)

st.sidebar.header("🌐 Macro Overlay (manual)")
macro_multiplier = st.sidebar.slider(
    "Macro regime multiplier", min_value=0.0, max_value=2.0, value=1.0, step=0.05,
    help="Read this off the Macro Engine page (governed_target / your normal target, roughly) "
         "and enter it here. 1.0 = neutral / no macro adjustment. This scales every risk-asset "
         "suggested deployment below; it is NOT re-derived from FRED inside this page.",
)
macro_mode_for_valuation = st.sidebar.selectbox(
    "Macro liquidity regime (feeds the Valuation Engine's own floor logic)",
    options=[
        "🟢 Expansion Mode (Unrestricted System Liquidity)",
        "🟡 Transition / K-Polarization (Contracting Liquidity)",
        "🔴 Forced System Crunch / Active Asset Stripping",
    ],
    index=1,
)

st.sidebar.header("📊 Valuation Engine Parameters")
lookback_years = st.sidebar.slider("Historical Lookback (Years)", 3, 10, 5)
z_threshold = st.sidebar.number_input("Z-Score Pressure Threshold (σ)", value=2.0, step=0.1)

st.sidebar.header("👑 Core Floor Settings")
core_crunch_floor = st.sidebar.number_input("Core Crunch Floor", value=0.10, min_value=0.0, max_value=1.0, step=0.05)
core_transition_floor = st.sidebar.number_input("Core Transition Floor", value=0.25, min_value=0.0, max_value=1.0, step=0.05)
core_expansion_floor = st.sidebar.number_input("Core Expansion Floor", value=0.35, min_value=0.0, max_value=1.0, step=0.05)
floors_cfg = {"crunch": core_crunch_floor, "transition": core_transition_floor, "expansion": core_expansion_floor}


# ----------------------------------------------------------------------
# Shared scoring function -- both tabs call this so the scoring logic
# lives in exactly one place, not duplicated per-tab.
# ----------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_engine_metrics(
    ticker: str,
    is_core: bool,
    lookback_years: int,
    z_threshold: float,
    macro_mode_for_valuation: str,
    floors_cfg: dict,
) -> dict:
    """
    The expensive part of scan_ticker: the actual Valuation + Expectations
    + Quality engine calls, which hit Yahoo Finance via yfinance. Cached
    for 30 minutes per (ticker, is_core, lookback_years, z_threshold,
    macro_mode, floors) combination, so:
      - Re-running a scan with unchanged sidebar params doesn't refetch
        data from Yahoo for tickers already scanned.
      - Scanning the same ticker in both the Grid tab and the Ad-Hoc tab
        (with the same is_core flag) only fetches it once.
    Deliberately does NOT take macro_multiplier or total_portfolio_value
    as arguments -- those only affect the cheap blend step in
    scan_ticker(), so moving the macro slider or changing portfolio value
    never invalidates this cache / triggers a refetch.
    """
    row = {
        "Ticker": ticker,
        "Core": "Yes" if is_core else "No",
        "Valuation Status": "N/A",
        "Expectations Status": "N/A",
        "Quality Status": "N/A",
        "Valuation Multiplier": np.nan,
        "Expectations Burden": np.nan,
        "Quality Score": np.nan,
        "Conviction Score": np.nan,
        "Deployment Multiplier": np.nan,
        "Notes": "",
    }

    # --- Valuation Engine ---
    try:
        df_data, error, report_freq, fx_note = valuation_engine.get_hardened_valuation_data(ticker, lookback_years)
        if error or df_data is None or df_data.empty:
            row["Notes"] = f"Valuation Engine: {error or 'no data'}"
        else:
            current_ps = df_data["PS_Ratio"].iloc[-1]
            mean_ps = df_data["PS_Ratio"].mean()
            std_ps = df_data["PS_Ratio"].std()
            z_score = (current_ps - mean_ps) / std_ps if std_ps and not np.isnan(std_ps) and std_ps != 0 else 0.0
            robust_z, _, _ = valuation_engine.calculate_robust_z_score(df_data["PS_Ratio"], current_ps)
            diags = valuation_engine.calculate_distribution_diagnostics(df_data["PS_Ratio"], current_ps)

            status_stance, val_mult, explanation, _ = valuation_engine.sovereign_allocation_engine(
                ticker=ticker, is_core=is_core, z_score=z_score, robust_z_score=robust_z,
                z_threshold=z_threshold, percentile=diags["percentile"], skewness=diags["skewness"],
                macro_mode=macro_mode_for_valuation, floors=floors_cfg,
            )
            row["Valuation Status"] = status_stance
            row["Valuation Multiplier"] = val_mult
    except Exception as e:
        row["Notes"] = f"Valuation Engine exception: {e}"

    # --- Expectations Engine ---
    try:
        engine = SovereignExpectationsEngine(ticker, is_core=is_core)
        exp_df = engine.hydrate_standalone_data()
        metrics = engine.execute(exp_df)
        row["Expectations Status"] = metrics["Expectations Classification"]
        row["Expectations Burden"] = metrics["Expectations Burden Score"]
    except Exception as e:
        row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Expectations Engine exception: {e}"

    # --- Quality Engine ---
    try:
        q_metrics, q_error = quality_engine.get_quality_data(ticker)
        if q_error or q_metrics is None:
            row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Quality Engine: {q_error or 'no data'}"
        else:
            q_result = quality_engine.compute_quality_score(ticker, q_metrics)
            row["Quality Status"] = q_result["classification"]
            row["Quality Score"] = q_result["quality_score"]
    except Exception as e:
        row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Quality Engine exception: {e}"

    # --- Blend into Conviction Score + deployment multiplier ---
    val_mult = row["Valuation Multiplier"]
    burden = row["Expectations Burden"]
    quality_score = row["Quality Score"]

    have_any = not np.isnan(val_mult) or not np.isnan(burden) or not np.isnan(quality_score)
    if have_any:
        val_component = min(max(val_mult, 0), 1.5) / 1.5 * 100 if not np.isnan(val_mult) else 50.0
        exp_component = 100 - burden if not np.isnan(burden) else 50.0
        qual_component = quality_score if not np.isnan(quality_score) else 50.0

        # Equal-weighted three-way blend. Valuation and Expectations answer
        # "is now a good time / price," Quality answers "is this a good
        # business at all" -- independent axes, so no single engine should
        # be able to carry a bad business to a high Conviction Score just
        # because it looks statistically cheap or unpriced-for-perfection.
        row["Conviction Score"] = (val_component + exp_component + qual_component) / 3

        # Expectations and Quality both act as hard caps on deployment
        # intensity, not just score inputs -- a cheap-looking multiple on a
        # fragile business, or one still pricing in aggressive growth,
        # shouldn't get full-size deployment just because the Valuation
        # Engine alone says "Value Zone".
        effective_mult = val_mult if not np.isnan(val_mult) else 0.0
        if not np.isnan(burden):
            if burden >= 75:
                effective_mult = min(effective_mult, 0.50)
            elif burden >= 55:
                effective_mult = min(effective_mult, 0.75)
        if not np.isnan(quality_score):
            if quality_score < 35:
                effective_mult = min(effective_mult, 0.50)
            elif quality_score < 50:
                effective_mult = min(effective_mult, 0.75)

        # Stored pre-macro so the (uncached) caller can apply the macro
        # overlay without needing to rerun the engines above.
        row["_effective_mult_premacro"] = effective_mult

    return row


def scan_ticker(ticker: str, is_core: bool) -> dict:
    """
    Cheap wrapper around the cached engine fetch: applies the macro
    overlay multiplier (which changes every time the sidebar slider
    moves, and shouldn't bust the Yahoo-data cache above) to produce the
    final Deployment Multiplier.
    """
    row = dict(_fetch_engine_metrics(
        ticker, is_core, lookback_years, z_threshold,
        macro_mode_for_valuation, floors_cfg,
    ))
    effective_mult = row.pop("_effective_mult_premacro", None)
    if effective_mult is not None:
        row["Deployment Multiplier"] = effective_mult * (
            macro_multiplier if not is_core else max(macro_multiplier, 0.5)
        )
    else:
        row["Deployment Multiplier"] = np.nan
    return row


def format_results(df: pd.DataFrame) -> pd.DataFrame:
    """Shared display formatting for both tabs' result tables."""
    display_df = df.copy()
    if "Structural Weight" in display_df.columns:
        display_df["Structural Weight"] = display_df["Structural Weight"].map(lambda x: f"{x:.1%}")
    if "Hypothetical Weight" in display_df.columns:
        display_df["Hypothetical Weight"] = display_df["Hypothetical Weight"].map(
            lambda x: f"{x:.1%}" if pd.notna(x) and x > 0 else "-")
    display_df["Valuation Multiplier"] = display_df["Valuation Multiplier"].map(
        lambda x: f"{x:.2f}x" if pd.notna(x) else "-")
    display_df["Expectations Burden"] = display_df["Expectations Burden"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    display_df["Quality Score"] = display_df["Quality Score"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    display_df["Conviction Score"] = display_df["Conviction Score"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    if "Suggested $ Deployment" in display_df.columns:
        display_df["Suggested $ Deployment"] = display_df["Suggested $ Deployment"].map(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
    return display_df


BLEND_CAPTION = (
    "Conviction Score equal-weights three independent axes: Valuation richness (is now a good price, "
    "vs. this ticker's own trading history), Expectations burden (how much growth is already priced "
    "in), and Quality (is this a good business at all -- ROIC, margins, leverage, dilution). Data "
    "sourced from Yahoo Finance via yfinance; informational only, not investment advice."
)

tab_grid, tab_adhoc = st.tabs(["📋 Structural Grid Scan", "🔍 Ad-Hoc Ticker Scan"])

# ========================================================================
# TAB 1: Structural Grid Scan
# ========================================================================
with tab_grid:
    st.subheader("📋 Select tickers to scan")

    sections_available = sorted(UNIVERSE_DF["section"].unique())
    picked_sections = st.multiselect(
        "Sections", options=sections_available, default=["INFRA", "ENERGY & COMMODITY", "AI/SEMIS"],
        help="Each ticker triggers 3 engine data-fetches. Keep the list short while testing -- "
             "yfinance calls are the slow part.",
        key="grid_sections",
    )

    candidate_df = UNIVERSE_DF[UNIVERSE_DF["section"].isin(picked_sections)]
    candidate_tickers = sorted(t for t in candidate_df["ticker"].unique() if t not in NON_EQUITY_TICKERS)

    picked_tickers = st.multiselect(
        "Tickers (equity only -- BTC/GOLD/CASH are shown separately below as fixed sleeves)",
        options=candidate_tickers, default=candidate_tickers, key="grid_tickers",
    )

    grid_run_clicked = st.button("🚀 Run Conviction Scan", type="primary", key="grid_run")

    st.subheader("🪙 Fixed Sleeves (not scored -- structural allocation only)")
    fixed_rows = UNIVERSE_DF[UNIVERSE_DF["ticker"].isin(NON_EQUITY_TICKERS)]
    fixed_display = fixed_rows[["ticker", "effective_weight"]].copy()
    fixed_display["Suggested $"] = fixed_display["effective_weight"] * total_portfolio_value
    fixed_display.columns = ["Sleeve", "Target Weight", "Suggested $"]
    fixed_display["Target Weight"] = fixed_display["Target Weight"].map(lambda x: f"{x:.1%}")
    fixed_display["Suggested $"] = fixed_display["Suggested $"].map(lambda x: f"{x:,.0f}")
    st.dataframe(fixed_display, use_container_width=True, hide_index=True)

    st.divider()

    if not grid_run_clicked:
        st.info("Pick your sections/tickers above and click **Run Conviction Scan**.")
    elif not picked_tickers:
        st.warning("No tickers selected.")
    else:
        results = []
        total = len(picked_tickers)
        completed = 0
        progress = st.progress(0.0, text="Starting scan...")

        # scan_ticker() is network I/O-bound (yfinance calls to Yahoo), so
        # tickers are fetched concurrently rather than one at a time. This
        # is the main lever on wall-clock scan time; caching in
        # _fetch_engine_metrics() handles the "same ticker scanned again"
        # case. Tune max_workers down if you hit Yahoo rate-limiting.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, total)) as executor:
            future_to_ticker = {
                executor.submit(scan_ticker, ticker, ticker in CORE_ELIGIBLE_TICKERS): ticker
                for ticker in picked_tickers
            }
            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                completed += 1
                progress.progress(completed / total, text=f"Scanned {ticker} ({completed}/{total})")

                grid_row = candidate_df[candidate_df["ticker"] == ticker].iloc[0]
                row = future.result()
                row["Section"] = grid_row["section"]
                row["Layer"] = grid_row["layer"]
                row["Structural Weight"] = grid_row["effective_weight"]

                deployment_mult = row.pop("Deployment Multiplier")
                row["Suggested $ Deployment"] = (
                    grid_row["effective_weight"] * total_portfolio_value * deployment_mult
                    if pd.notna(deployment_mult) else np.nan
                )
                results.append(row)

        progress.progress(1.0, text="Scan complete.")
        progress.empty()

        results_df = pd.DataFrame(results).sort_values("Conviction Score", ascending=False, na_position="last")
        col_order = ["Ticker", "Section", "Layer", "Structural Weight", "Core", "Valuation Status",
                     "Expectations Status", "Quality Status", "Valuation Multiplier", "Expectations Burden",
                     "Quality Score", "Conviction Score", "Suggested $ Deployment", "Notes"]
        results_df = results_df[col_order]

        st.session_state["last_grid_scan_tickers"] = results_df["Ticker"].tolist()

        st.subheader("🏆 Ranked Conviction Output")
        st.dataframe(format_results(results_df), use_container_width=True, hide_index=True)

        failed = results_df[results_df["Notes"] != ""]
        if not failed.empty:
            with st.expander(f"⚠️ {len(failed)} ticker(s) had data issues"):
                st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)

        st.caption(
            BLEND_CAPTION + " Suggested $ Deployment = structural target weight x portfolio value x "
            "valuation multiplier (capped further by high Expectations burden or low Quality) x macro overlay."
        )
        st.info(
            "💡 Check these tickers for concentration and correlation risk on the "
            "**Portfolio Engine** page -- it picks up this scan's ticker list automatically."
        )

# ========================================================================
# TAB 2: Ad-Hoc Ticker Scan -- any ticker, outside the structural grid
# ========================================================================
with tab_adhoc:
    st.subheader("🔍 Scan any ticker(s) -- no structural grid membership required")
    st.caption(
        "For vetting an idea before deciding whether it belongs in structural_grid.py at all. "
        "Runs the exact same three engines and blend as the grid scan. Since there's no fixed "
        "structural weight here, sizing is optional and uses a hypothetical weight % you set below."
    )

    adhoc_text = st.text_area(
        "Ticker(s) -- comma, space, or newline separated",
        placeholder="e.g. NVDA, MSFT, 0700.HK",
        height=80, key="adhoc_tickers_input",
    )

    raw = adhoc_text.replace(",", " ").replace("\n", " ").split()
    adhoc_tickers = sorted(set(t.strip().upper() for t in raw if t.strip()))

    if adhoc_tickers:
        adhoc_core_tickers = st.multiselect(
            "Treat as core holdings? (affects Valuation Engine floor logic -- see Core Floor Settings "
            "in the sidebar)",
            options=adhoc_tickers, default=[], key="adhoc_core_select",
        )
    else:
        adhoc_core_tickers = []

    size_it = st.checkbox(
        "Size a suggested $ deployment using a hypothetical weight",
        value=False, key="adhoc_size_toggle",
        help="Off by default -- without a real structural weight from the grid, any $ figure here "
             "is purely illustrative (what deployment WOULD look like if this ticker got this weight).",
    )
    hypothetical_weight_pct = 0.0
    if size_it:
        hypothetical_weight_pct = st.number_input(
            "Hypothetical weight (% of total portfolio, applied to every ticker in this scan)",
            min_value=0.0, max_value=100.0, value=2.0, step=0.5, key="adhoc_weight_pct",
        ) / 100.0

    adhoc_run_clicked = st.button("🔍 Run Ad-Hoc Scan", type="primary", key="adhoc_run")

    st.divider()

    if not adhoc_run_clicked:
        st.info("Enter one or more tickers above and click **Run Ad-Hoc Scan**.")
    elif not adhoc_tickers:
        st.warning("Enter at least one ticker first.")
    else:
        results = []
        total = len(adhoc_tickers)
        completed = 0
        progress = st.progress(0.0, text="Starting scan...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, total)) as executor:
            future_to_ticker = {
                executor.submit(scan_ticker, ticker, ticker in adhoc_core_tickers): ticker
                for ticker in adhoc_tickers
            }
            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                completed += 1
                progress.progress(completed / total, text=f"Scanned {ticker} ({completed}/{total})")

                row = future.result()
                deployment_mult = row.pop("Deployment Multiplier")
                if size_it and pd.notna(deployment_mult):
                    row["Hypothetical Weight"] = hypothetical_weight_pct
                    row["Suggested $ Deployment"] = hypothetical_weight_pct * total_portfolio_value * deployment_mult
                else:
                    row["Hypothetical Weight"] = np.nan
                    row["Suggested $ Deployment"] = np.nan

                results.append(row)

        progress.progress(1.0, text="Scan complete.")
        progress.empty()

        results_df = pd.DataFrame(results).sort_values("Conviction Score", ascending=False, na_position="last")
        col_order = ["Ticker", "Core", "Valuation Status", "Expectations Status", "Quality Status",
                     "Valuation Multiplier", "Expectations Burden", "Quality Score", "Conviction Score",
                     "Hypothetical Weight", "Suggested $ Deployment", "Notes"]
        results_df = results_df[col_order]

        st.subheader("🏆 Ranked Conviction Output (ad-hoc)")
        st.dataframe(format_results(results_df), use_container_width=True, hide_index=True)

        failed = results_df[results_df["Notes"] != ""]
        if not failed.empty:
            with st.expander(f"⚠️ {len(failed)} ticker(s) had data issues"):
                st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)

        st.caption(
            BLEND_CAPTION + (
                " Suggested $ Deployment = hypothetical weight x portfolio value x valuation multiplier "
                "(capped further by high Expectations burden or low Quality) x macro overlay -- purely "
                "illustrative, not tied to any actual portfolio target."
                if size_it else
                " No $ sizing was requested for this scan -- check 'Size a suggested $ deployment' above "
                "to see an illustrative figure."
            )
        )

        if not results_df.empty and st.session_state.get("adhoc_run"):
            st.info(
                "💡 Liked what you see? Add promising tickers to `structural_grid.py` (with a real "
                "section/layer/target weight) to include them in the main Structural Grid Scan going forward."
            )
    """
    row = {
        "Ticker": ticker,
        "Core": "Yes" if is_core else "No",
        "Valuation Status": "N/A",
        "Expectations Status": "N/A",
        "Quality Status": "N/A",
        "Valuation Multiplier": np.nan,
        "Expectations Burden": np.nan,
        "Quality Score": np.nan,
        "Conviction Score": np.nan,
        "Deployment Multiplier": np.nan,
        "Notes": "",
    }

    # --- Valuation Engine ---
    try:
        df_data, error, report_freq, fx_note = valuation_engine.get_hardened_valuation_data(ticker, lookback_years)
        if error or df_data is None or df_data.empty:
            row["Notes"] = f"Valuation Engine: {error or 'no data'}"
        else:
            current_ps = df_data["PS_Ratio"].iloc[-1]
            mean_ps = df_data["PS_Ratio"].mean()
            std_ps = df_data["PS_Ratio"].std()
            z_score = (current_ps - mean_ps) / std_ps if std_ps and not np.isnan(std_ps) and std_ps != 0 else 0.0
            robust_z, _, _ = valuation_engine.calculate_robust_z_score(df_data["PS_Ratio"], current_ps)
            diags = valuation_engine.calculate_distribution_diagnostics(df_data["PS_Ratio"], current_ps)

            status_stance, val_mult, explanation, _ = valuation_engine.sovereign_allocation_engine(
                ticker=ticker, is_core=is_core, z_score=z_score, robust_z_score=robust_z,
                z_threshold=z_threshold, percentile=diags["percentile"], skewness=diags["skewness"],
                macro_mode=macro_mode_for_valuation, floors=floors_cfg,
            )
            row["Valuation Status"] = status_stance
            row["Valuation Multiplier"] = val_mult
    except Exception as e:
        row["Notes"] = f"Valuation Engine exception: {e}"

    # --- Expectations Engine ---
    try:
        engine = SovereignExpectationsEngine(ticker, is_core=is_core)
        exp_df = engine.hydrate_standalone_data()
        metrics = engine.execute(exp_df)
        row["Expectations Status"] = metrics["Expectations Classification"]
        row["Expectations Burden"] = metrics["Expectations Burden Score"]
    except Exception as e:
        row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Expectations Engine exception: {e}"

    # --- Quality Engine ---
    try:
        q_metrics, q_error = quality_engine.get_quality_data(ticker)
        if q_error or q_metrics is None:
            row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Quality Engine: {q_error or 'no data'}"
        else:
            q_result = quality_engine.compute_quality_score(ticker, q_metrics)
            row["Quality Status"] = q_result["classification"]
            row["Quality Score"] = q_result["quality_score"]
    except Exception as e:
        row["Notes"] = (row["Notes"] + " | " if row["Notes"] else "") + f"Quality Engine exception: {e}"

    # --- Blend into Conviction Score + deployment multiplier ---
    val_mult = row["Valuation Multiplier"]
    burden = row["Expectations Burden"]
    quality_score = row["Quality Score"]

    have_any = not np.isnan(val_mult) or not np.isnan(burden) or not np.isnan(quality_score)
    if have_any:
        val_component = min(max(val_mult, 0), 1.5) / 1.5 * 100 if not np.isnan(val_mult) else 50.0
        exp_component = 100 - burden if not np.isnan(burden) else 50.0
        qual_component = quality_score if not np.isnan(quality_score) else 50.0

        # Equal-weighted three-way blend. Valuation and Expectations answer
        # "is now a good time / price," Quality answers "is this a good
        # business at all" -- independent axes, so no single engine should
        # be able to carry a bad business to a high Conviction Score just
        # because it looks statistically cheap or unpriced-for-perfection.
        row["Conviction Score"] = (val_component + exp_component + qual_component) / 3

        # Expectations and Quality both act as hard caps on deployment
        # intensity, not just score inputs -- a cheap-looking multiple on a
        # fragile business, or one still pricing in aggressive growth,
        # shouldn't get full-size deployment just because the Valuation
        # Engine alone says "Value Zone".
        effective_mult = val_mult if not np.isnan(val_mult) else 0.0
        if not np.isnan(burden):
            if burden >= 75:
                effective_mult = min(effective_mult, 0.50)
            elif burden >= 55:
                effective_mult = min(effective_mult, 0.75)
        if not np.isnan(quality_score):
            if quality_score < 35:
                effective_mult = min(effective_mult, 0.50)
            elif quality_score < 50:
                effective_mult = min(effective_mult, 0.75)

        row["Deployment Multiplier"] = effective_mult * (macro_multiplier if not is_core else max(macro_multiplier, 0.5))

    return row


def format_results(df: pd.DataFrame) -> pd.DataFrame:
    """Shared display formatting for both tabs' result tables."""
    display_df = df.copy()
    if "Structural Weight" in display_df.columns:
        display_df["Structural Weight"] = display_df["Structural Weight"].map(lambda x: f"{x:.1%}")
    if "Hypothetical Weight" in display_df.columns:
        display_df["Hypothetical Weight"] = display_df["Hypothetical Weight"].map(
            lambda x: f"{x:.1%}" if pd.notna(x) and x > 0 else "-")
    display_df["Valuation Multiplier"] = display_df["Valuation Multiplier"].map(
        lambda x: f"{x:.2f}x" if pd.notna(x) else "-")
    display_df["Expectations Burden"] = display_df["Expectations Burden"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    display_df["Quality Score"] = display_df["Quality Score"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    display_df["Conviction Score"] = display_df["Conviction Score"].map(
        lambda x: f"{x:.1f}" if pd.notna(x) else "-")
    if "Suggested $ Deployment" in display_df.columns:
        display_df["Suggested $ Deployment"] = display_df["Suggested $ Deployment"].map(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
    return display_df


BLEND_CAPTION = (
    "Conviction Score equal-weights three independent axes: Valuation richness (is now a good price, "
    "vs. this ticker's own trading history), Expectations burden (how much growth is already priced "
    "in), and Quality (is this a good business at all -- ROIC, margins, leverage, dilution). Data "
    "sourced from Yahoo Finance via yfinance; informational only, not investment advice."
)

tab_grid, tab_adhoc = st.tabs(["📋 Structural Grid Scan", "🔍 Ad-Hoc Ticker Scan"])

# ========================================================================
# TAB 1: Structural Grid Scan
# ========================================================================
with tab_grid:
    st.subheader("📋 Select tickers to scan")

    sections_available = sorted(UNIVERSE_DF["section"].unique())
    picked_sections = st.multiselect(
        "Sections", options=sections_available, default=["INFRA", "ENERGY & COMMODITY", "AI/SEMIS"],
        help="Each ticker triggers 3 engine data-fetches. Keep the list short while testing -- "
             "yfinance calls are the slow part.",
        key="grid_sections",
    )

    candidate_df = UNIVERSE_DF[UNIVERSE_DF["section"].isin(picked_sections)]
    candidate_tickers = sorted(t for t in candidate_df["ticker"].unique() if t not in NON_EQUITY_TICKERS)

    picked_tickers = st.multiselect(
        "Tickers (equity only -- BTC/GOLD/CASH are shown separately below as fixed sleeves)",
        options=candidate_tickers, default=candidate_tickers, key="grid_tickers",
    )

    grid_run_clicked = st.button("🚀 Run Conviction Scan", type="primary", key="grid_run")

    st.subheader("🪙 Fixed Sleeves (not scored -- structural allocation only)")
    fixed_rows = UNIVERSE_DF[UNIVERSE_DF["ticker"].isin(NON_EQUITY_TICKERS)]
    fixed_display = fixed_rows[["ticker", "effective_weight"]].copy()
    fixed_display["Suggested $"] = fixed_display["effective_weight"] * total_portfolio_value
    fixed_display.columns = ["Sleeve", "Target Weight", "Suggested $"]
    fixed_display["Target Weight"] = fixed_display["Target Weight"].map(lambda x: f"{x:.1%}")
    fixed_display["Suggested $"] = fixed_display["Suggested $"].map(lambda x: f"{x:,.0f}")
    st.dataframe(fixed_display, use_container_width=True, hide_index=True)

    st.divider()

    if not grid_run_clicked:
        st.info("Pick your sections/tickers above and click **Run Conviction Scan**.")
    elif not picked_tickers:
        st.warning("No tickers selected.")
    else:
        results = []
        progress = st.progress(0.0, text="Starting scan...")

        for i, ticker in enumerate(picked_tickers):
            progress.progress(i / len(picked_tickers), text=f"Scanning {ticker}...")

            grid_row = candidate_df[candidate_df["ticker"] == ticker].iloc[0]
            is_core = ticker in CORE_ELIGIBLE_TICKERS

            row = scan_ticker(ticker, is_core)
            row["Section"] = grid_row["section"]
            row["Layer"] = grid_row["layer"]
            row["Structural Weight"] = grid_row["effective_weight"]

            deployment_mult = row.pop("Deployment Multiplier")
            row["Suggested $ Deployment"] = (
                grid_row["effective_weight"] * total_portfolio_value * deployment_mult
                if pd.notna(deployment_mult) else np.nan
            )
            results.append(row)

        progress.progress(1.0, text="Scan complete.")
        progress.empty()

        results_df = pd.DataFrame(results).sort_values("Conviction Score", ascending=False, na_position="last")
        col_order = ["Ticker", "Section", "Layer", "Structural Weight", "Core", "Valuation Status",
                     "Expectations Status", "Quality Status", "Valuation Multiplier", "Expectations Burden",
                     "Quality Score", "Conviction Score", "Suggested $ Deployment", "Notes"]
        results_df = results_df[col_order]

        st.session_state["last_grid_scan_tickers"] = results_df["Ticker"].tolist()

        st.subheader("🏆 Ranked Conviction Output")
        st.dataframe(format_results(results_df), use_container_width=True, hide_index=True)

        failed = results_df[results_df["Notes"] != ""]
        if not failed.empty:
            with st.expander(f"⚠️ {len(failed)} ticker(s) had data issues"):
                st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)

        st.caption(
            BLEND_CAPTION + " Suggested $ Deployment = structural target weight x portfolio value x "
            "valuation multiplier (capped further by high Expectations burden or low Quality) x macro overlay."
        )
        st.info(
            "💡 Check these tickers for concentration and correlation risk on the "
            "**Portfolio Engine** page -- it picks up this scan's ticker list automatically."
        )

# ========================================================================
# TAB 2: Ad-Hoc Ticker Scan -- any ticker, outside the structural grid
# ========================================================================
with tab_adhoc:
    st.subheader("🔍 Scan any ticker(s) -- no structural grid membership required")
    st.caption(
        "For vetting an idea before deciding whether it belongs in structural_grid.py at all. "
        "Runs the exact same three engines and blend as the grid scan. Since there's no fixed "
        "structural weight here, sizing is optional and uses a hypothetical weight % you set below."
    )

    adhoc_text = st.text_area(
        "Ticker(s) -- comma, space, or newline separated",
        placeholder="e.g. NVDA, MSFT, 0700.HK",
        height=80, key="adhoc_tickers_input",
    )

    raw = adhoc_text.replace(",", " ").replace("\n", " ").split()
    adhoc_tickers = sorted(set(t.strip().upper() for t in raw if t.strip()))

    if adhoc_tickers:
        adhoc_core_tickers = st.multiselect(
            "Treat as core holdings? (affects Valuation Engine floor logic -- see Core Floor Settings "
            "in the sidebar)",
            options=adhoc_tickers, default=[], key="adhoc_core_select",
        )
    else:
        adhoc_core_tickers = []

    size_it = st.checkbox(
        "Size a suggested $ deployment using a hypothetical weight",
        value=False, key="adhoc_size_toggle",
        help="Off by default -- without a real structural weight from the grid, any $ figure here "
             "is purely illustrative (what deployment WOULD look like if this ticker got this weight).",
    )
    hypothetical_weight_pct = 0.0
    if size_it:
        hypothetical_weight_pct = st.number_input(
            "Hypothetical weight (% of total portfolio, applied to every ticker in this scan)",
            min_value=0.0, max_value=100.0, value=2.0, step=0.5, key="adhoc_weight_pct",
        ) / 100.0

    adhoc_run_clicked = st.button("🔍 Run Ad-Hoc Scan", type="primary", key="adhoc_run")

    st.divider()

    if not adhoc_run_clicked:
        st.info("Enter one or more tickers above and click **Run Ad-Hoc Scan**.")
    elif not adhoc_tickers:
        st.warning("Enter at least one ticker first.")
    else:
        results = []
        progress = st.progress(0.0, text="Starting scan...")

        for i, ticker in enumerate(adhoc_tickers):
            progress.progress(i / len(adhoc_tickers), text=f"Scanning {ticker}...")

            is_core = ticker in adhoc_core_tickers
            row = scan_ticker(ticker, is_core)

            deployment_mult = row.pop("Deployment Multiplier")
            if size_it and pd.notna(deployment_mult):
                row["Hypothetical Weight"] = hypothetical_weight_pct
                row["Suggested $ Deployment"] = hypothetical_weight_pct * total_portfolio_value * deployment_mult
            else:
                row["Hypothetical Weight"] = np.nan
                row["Suggested $ Deployment"] = np.nan

            results.append(row)

        progress.progress(1.0, text="Scan complete.")
        progress.empty()

        results_df = pd.DataFrame(results).sort_values("Conviction Score", ascending=False, na_position="last")
        col_order = ["Ticker", "Core", "Valuation Status", "Expectations Status", "Quality Status",
                     "Valuation Multiplier", "Expectations Burden", "Quality Score", "Conviction Score",
                     "Hypothetical Weight", "Suggested $ Deployment", "Notes"]
        results_df = results_df[col_order]

        st.subheader("🏆 Ranked Conviction Output (ad-hoc)")
        st.dataframe(format_results(results_df), use_container_width=True, hide_index=True)

        failed = results_df[results_df["Notes"] != ""]
        if not failed.empty:
            with st.expander(f"⚠️ {len(failed)} ticker(s) had data issues"):
                st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)

        st.caption(
            BLEND_CAPTION + (
                " Suggested $ Deployment = hypothetical weight x portfolio value x valuation multiplier "
                "(capped further by high Expectations burden or low Quality) x macro overlay -- purely "
                "illustrative, not tied to any actual portfolio target."
                if size_it else
                " No $ sizing was requested for this scan -- check 'Size a suggested $ deployment' above "
                "to see an illustrative figure."
            )
        )

        if not results_df.empty and st.session_state.get("adhoc_run"):
            st.info(
                "💡 Liked what you see? Add promising tickers to `structural_grid.py` (with a real "
                "section/layer/target weight) to include them in the main Structural Grid Scan going forward."
            )
