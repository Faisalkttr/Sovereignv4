"""
Sovereign Ticker Verifier
=========================
Answers the question we kept hitting manually while building this project:
"does this ticker actually resolve in yfinance, and does it have enough
data for our engines to run on it?"

Every ticker in structural_grid.py should get run through this before it's
trusted -- this is exactly the check that would have caught ADNOCGAS being
a duplicate of ACWA Power's ticker, ABB resolving to the wrong company, and
CEO/CHL being dead NYSE tickers since 2021, without needing a manual
back-and-forth to find each one.

WHAT IT CHECKS, per ticker:
  - Does yf.Ticker(ticker).info resolve to a real company/fund at all?
  - Is there price history? (needed by all three engines)
  - Is there quarterly/annual revenue data? (needed by Valuation + Expectations)
  - Is there shares-outstanding data? (needed by Valuation + Expectations)
  - Is there balance sheet / cash flow data? (needed by Quality)

This is a read-only diagnostic tool -- it doesn't score or rank anything,
it just tells you whether a symbol is safe to add to structural_grid.py.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

sys.path.append(str(Path(__file__).resolve().parent.parent))
from structural_grid import NON_EQUITY_TICKERS, flatten_universe

st.set_page_config(page_title="Sovereign Ticker Verifier", page_icon="🔍", layout="wide")

st.title("🔍 Sovereign Ticker Verifier")
st.caption(
    "Checks whether a ticker actually resolves in yfinance and has enough data for the "
    "Valuation, Expectations, and Quality engines to run on it -- before it goes into "
    "structural_grid.py."
)


@st.cache_data(ttl=3600, show_spinner=False)
def verify_ticker(ticker: str) -> dict:
    """
    Runs the same category of data-fetch calls the three engines depend on,
    and reports what's actually available -- without doing any scoring.
    """
    result = {
        "Ticker": ticker,
        "Resolved": False,
        "Name": "",
        "Exchange": "",
        "Currency": "",
        "Last Price": np.nan,
        "Price History": "❌",
        "Quarterly Financials": "❌",
        "Annual Financials": "❌",
        "Balance Sheet": "❌",
        "Cash Flow": "❌",
        "Shares Outstanding": "❌",
        "Verdict": "🔴 Failed to resolve",
        "Notes": "",
    }

    try:
        stock = yf.Ticker(ticker)

        try:
            info = stock.info or {}
        except Exception:
            info = {}

        name = info.get("longName") or info.get("shortName")
        if name:
            result["Resolved"] = True
            result["Name"] = name
            result["Exchange"] = info.get("exchange", "")
            result["Currency"] = info.get("currency", "")
            result["Last Price"] = info.get("currentPrice") or info.get("regularMarketPrice") or np.nan

        try:
            hist = stock.history(period="5d")
            if not hist.empty:
                result["Price History"] = "✅"
                if not result["Resolved"]:
                    # Some valid tickers (esp. thinly-covered ETFs) return price history
                    # but a near-empty .info dict -- still count these as resolved.
                    result["Resolved"] = True
                    result["Name"] = result["Name"] or "(name unavailable, but price history exists)"
        except Exception as e:
            result["Notes"] += f"Price history error: {e}. "

        if ticker.upper() not in NON_EQUITY_TICKERS:
            try:
                q_fin = stock.quarterly_financials
                if q_fin is not None and not q_fin.empty:
                    result["Quarterly Financials"] = "✅"
            except Exception as e:
                result["Notes"] += f"Quarterly financials error: {e}. "

            try:
                a_fin = stock.financials
                if a_fin is not None and not a_fin.empty:
                    result["Annual Financials"] = "✅"
            except Exception as e:
                result["Notes"] += f"Annual financials error: {e}. "

            try:
                bs = stock.balance_sheet
                if bs is not None and not bs.empty:
                    result["Balance Sheet"] = "✅"
            except Exception as e:
                result["Notes"] += f"Balance sheet error: {e}. "

            try:
                cf = stock.cashflow
                if cf is not None and not cf.empty:
                    result["Cash Flow"] = "✅"
            except Exception as e:
                result["Notes"] += f"Cash flow error: {e}. "

            try:
                shares = stock.get_shares_full(start=pd.Timestamp.now() - pd.Timedelta(days=365))
                has_shares = shares is not None and not shares.empty
            except Exception:
                has_shares = False
            if has_shares or info.get("sharesOutstanding"):
                result["Shares Outstanding"] = "✅"

        # --- Verdict ---
        if not result["Resolved"]:
            result["Verdict"] = "🔴 Failed to resolve"
        elif ticker.upper() in NON_EQUITY_TICKERS:
            result["Verdict"] = "⚪ Non-equity sleeve (not scored by engines)"
        elif result["Price History"] == "✅" and result["Quarterly Financials"] == "✅" and \
                result["Balance Sheet"] == "✅" and result["Cash Flow"] == "✅":
            result["Verdict"] = "✅ Fully compatible (all 3 engines)"
        elif result["Price History"] == "✅" and (
                result["Quarterly Financials"] == "✅" or result["Annual Financials"] == "✅"):
            result["Verdict"] = "🟡 Partial (Valuation/Expectations likely OK, Quality may fail)"
        elif result["Price History"] == "✅":
            result["Verdict"] = "🟠 Price only (likely an ETF/index -- fundamentals-based engines will fail)"
        else:
            result["Verdict"] = "🔴 Resolves but no usable data"

    except Exception as e:
        result["Notes"] += f"Fatal lookup error: {e}"

    return result


def style_verdict(val):
    val = str(val)
    if "Fully compatible" in val:
        return "background-color: #065f46; color: white;"
    if "Partial" in val:
        return "background-color: #ca8a04; color: black;"
    if "Price only" in val:
        return "background-color: #9a3412; color: white;"
    if "Failed" in val or "no usable data" in val:
        return "background-color: #991b1b; color: white;"
    if "Non-equity" in val:
        return "background-color: #1e293b; color: #cbd5e1;"
    return ""


tab_single, tab_batch, tab_grid = st.tabs(["🔎 Single Ticker", "📋 Batch Paste", "📊 Verify Whole Grid"])

# ----------------------------------------------------------------------
# Single ticker
# ----------------------------------------------------------------------
with tab_single:
    ticker_input = st.text_input("Ticker to check", value="", placeholder="e.g. 0883.HK, ADNOCGAS.AB, ISDE.L").strip().upper()
    if st.button("Verify", type="primary", key="single_verify"):
        if not ticker_input:
            st.warning("Enter a ticker first.")
        else:
            with st.spinner(f"Checking {ticker_input}..."):
                r = verify_ticker(ticker_input)

            st.subheader(f"{ticker_input} — {r['Verdict']}")
            if r["Resolved"]:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Name", r["Name"] or "N/A")
                c2.metric("Exchange", r["Exchange"] or "N/A")
                c3.metric("Currency", r["Currency"] or "N/A")
                c4.metric("Last Price", f"{r['Last Price']:.2f}" if pd.notna(r["Last Price"]) else "N/A")

                check_df = pd.DataFrame([
                    {"Data": "Price History", "Available": r["Price History"]},
                    {"Data": "Quarterly Financials", "Available": r["Quarterly Financials"]},
                    {"Data": "Annual Financials", "Available": r["Annual Financials"]},
                    {"Data": "Balance Sheet", "Available": r["Balance Sheet"]},
                    {"Data": "Cash Flow", "Available": r["Cash Flow"]},
                    {"Data": "Shares Outstanding", "Available": r["Shares Outstanding"]},
                ])
                st.dataframe(check_df, use_container_width=True, hide_index=True)
            else:
                st.error(f"This ticker did not resolve in yfinance. {r['Notes']}")

# ----------------------------------------------------------------------
# Batch paste
# ----------------------------------------------------------------------
with tab_batch:
    st.caption("Paste any list of tickers (comma, space, or newline separated) -- e.g. a whole row from your grid.")
    batch_text = st.text_area("Tickers", height=100, placeholder="0883.HK, ADNOCGAS.AB, ISDE.L, HIJP.L")
    if st.button("Verify batch", type="primary", key="batch_verify"):
        raw = batch_text.replace(",", " ").replace("\n", " ").split()
        tickers = sorted(set(t.strip().upper() for t in raw if t.strip()))
        if not tickers:
            st.warning("Paste at least one ticker first.")
        else:
            progress = st.progress(0.0, text="Starting...")
            rows = []
            for i, t in enumerate(tickers):
                progress.progress(i / len(tickers), text=f"Checking {t}...")
                rows.append(verify_ticker(t))
            progress.empty()

            df = pd.DataFrame(rows)
            display_cols = ["Ticker", "Verdict", "Name", "Exchange", "Currency", "Price History",
                             "Quarterly Financials", "Balance Sheet", "Cash Flow", "Shares Outstanding"]
            st.dataframe(
                df[display_cols].style.applymap(style_verdict, subset=["Verdict"]),
                use_container_width=True, hide_index=True,
            )

            failed = df[df["Verdict"].str.contains("Failed|no usable data")]
            if not failed.empty:
                with st.expander(f"⚠️ {len(failed)} ticker(s) failed -- error details"):
                    st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------
# Verify the whole structural grid at once
# ----------------------------------------------------------------------
with tab_grid:
    st.caption(
        "Runs this same check against every ticker currently in structural_grid.py -- the fastest "
        "way to catch a bad symbol before it silently breaks a Home.py scan."
    )
    if st.button("Verify entire grid", type="primary", key="grid_verify"):
        universe = flatten_universe()
        tickers = sorted(set(row["ticker"] for row in universe))

        progress = st.progress(0.0, text="Starting...")
        rows = []
        for i, t in enumerate(tickers):
            progress.progress(i / len(tickers), text=f"Checking {t}...")
            rows.append(verify_ticker(t))
        progress.empty()

        df = pd.DataFrame(rows)

        n_ok = (df["Verdict"].str.contains("Fully compatible")).sum()
        n_partial = (df["Verdict"].str.contains("Partial")).sum()
        n_price_only = (df["Verdict"].str.contains("Price only")).sum()
        n_failed = (df["Verdict"].str.contains("Failed|no usable data")).sum()
        n_nonequity = (df["Verdict"].str.contains("Non-equity")).sum()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("✅ Fully compatible", int(n_ok))
        c2.metric("🟡 Partial", int(n_partial))
        c3.metric("🟠 Price only", int(n_price_only))
        c4.metric("🔴 Failed", int(n_failed))
        c5.metric("⚪ Non-equity", int(n_nonequity))

        display_cols = ["Ticker", "Verdict", "Name", "Exchange", "Currency", "Price History",
                         "Quarterly Financials", "Balance Sheet", "Cash Flow", "Shares Outstanding"]
        st.dataframe(
            df[display_cols].style.applymap(style_verdict, subset=["Verdict"]),
            use_container_width=True, hide_index=True,
        )

        failed = df[df["Verdict"].str.contains("Failed|no usable data")]
        if not failed.empty:
            st.error(f"🔴 {len(failed)} ticker(s) in your grid will not work. Fix these in structural_grid.py:")
            st.dataframe(failed[["Ticker", "Notes"]], use_container_width=True, hide_index=True)
        else:
            st.success("Every ticker in the grid resolved.")

st.caption(
    "Verdicts are heuristic, not a guarantee -- a ticker can pass this check and still have thin/patchy "
    "history that produces a low-confidence read in the actual engines (see each engine's own confidence "
    "flags). Results are cached for 1 hour per ticker."
)
