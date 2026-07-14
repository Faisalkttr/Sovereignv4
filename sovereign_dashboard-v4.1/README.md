# Sovereign Conviction Engine

A combined dashboard wiring your structural allocation grid to your four
analytical engines (Expectations, Valuation, Quality, plus the standalone
Macro overlay), with a Ticker Verifier to sanity-check any symbol first.

## Structure

```
Home.py                        # Combined Conviction dashboard (start here)
structural_grid.py              # Your sections/layers/tickers/target weights (from the uploaded grid image)
engines/
  expectations_engine.py        # SovereignExpectationsEngine (was app1.py) -- unchanged logic
  valuation_engine.py           # Valuation/scoring functions extracted from app3.py -- unchanged logic
  quality_engine.py             # NEW: ROIC / margins / leverage / dilution scoring
  portfolio_engine.py           # NEW: concentration limits + cross-ticker correlation clustering
pages/
  1_Expectations_Engine.py      # Standalone single-ticker Expectations page (was streamlit_app.py)
  2_Valuation_Engine.py         # Standalone Valuation & Discipline page (was app3.py), now imports engines/valuation_engine.py
  3_Macro_Engine.py             # Macro regime page (was execution_engine.py), unchanged -- needs a FRED API key
  4_Quality_Engine.py           # NEW: standalone single-ticker Quality page
  5_Ticker_Verifier.py          # NEW: checks whether a ticker resolves in yfinance + has enough data for each engine
  6_Portfolio_Engine.py         # NEW: concentration (structural grid) + correlation (chosen ticker set) dashboard
```

## Running it

```bash
pip install -r requirements.txt
streamlit run Home.py
```

Streamlit will automatically pick up everything in `pages/` as extra
navigation entries in the sidebar, so all four views (combined + the 3
individual engines) are reachable from one running app.

## How the pieces connect

- **structural_grid.py** is pure data: it encodes your sections (INFRA,
  ENERGY & COMMODITY, AI/SEMIS, EM, Business & Futuristic Overlay, BTC,
  GOLD, CASH), each ticker's layer, and its target weight within the
  portfolio. `flatten_universe()` turns that into one row per ticker with
  an `effective_weight` (section target % x layer weight). The old
  "satellite" watchlist tier (Rail & Logistics, Water & Waste, Cyber
  Security, Networking, Energy/Materials/Industrials, Human Healthcare)
  has been fully merged into the core sections -- `SATELLITE` is now an
  empty dict, kept only so nothing breaks if something still iterates it.
- **Home.py** has two tabs:
  - **📋 Structural Grid Scan** -- pick a subset of sections/tickers from
    `structural_grid.py`, then for each one runs:
    1. `valuation_engine.get_hardened_valuation_data()` + `sovereign_allocation_engine()`
       -> a 0-1.5x deployment multiplier based on how rich/cheap the ticker
       is vs. its own P/S history.
    2. `expectations_engine.SovereignExpectationsEngine` -> an Expectations
       Burden Score (0-100) measuring how much forward growth is priced in.
    3. `quality_engine.get_quality_data()` + `compute_quality_score()` -> a
       Quality Score (0-100) from ROIC, gross margin, FCF margin, net
       debt/EBITDA, and share dilution -- is this a *good business*,
       independent of price or timing?
    4. Equal-weights all three into a **Conviction Score**, and computes
       **Suggested $ Deployment** = structural weight x portfolio value x
       valuation multiplier (capped further if Expectations burden is high
       OR Quality is low) x a manual macro overlay multiplier.
  - **🔍 Ad-Hoc Ticker Scan** -- run the exact same three engines and blend
    on ANY ticker(s), including ones not in `structural_grid.py` at all.
    No structural weight exists for these, so $ sizing is optional and
    uses a hypothetical weight % you enter yourself -- meant for vetting a
    new idea before deciding whether it belongs in the grid. Both tabs
    call the same `scan_ticker()` function so the scoring logic lives in
    one place, not duplicated per-tab.
- **Macro Engine (page 3)** is intentionally *not* re-implemented inside
  Home.py -- it's a portfolio-wide regime call (FRED liquidity/credit/
  dollar data), not a per-ticker one, and its ~1,400 lines of governor/
  kill-switch/positioning logic would be a second copy to maintain if
  duplicated. Run it separately, read its `governed_target` output, and
  enter that as the "Macro overlay multiplier" in Home.py's sidebar.

## Quality Engine (new)

`engines/quality_engine.py` scores five metrics against an explicit,
editable threshold table (`QUALITY_THRESHOLDS`) -- ROIC, gross margin, FCF
margin, net debt/EBITDA, and YoY share dilution -- then blends them
(re-normalized over whichever metrics were actually resolvable from the
ticker's statements) into a single Quality Score and classification.

It intentionally does **not** try to be sector-aware: royalty/streaming
names (FNV, WPM, TPL) get an explicit warning banner (`sector_caveat`)
rather than a silently misleading score, since a generic operating-company
ROIC/margin template doesn't map cleanly onto their business model. If you
add more royalty/financial/REIT-style names to the grid, add them to
`SECTOR_CAVEAT_TICKERS` too.

## Portfolio Engine (new)

Every other engine scores one ticker at a time. `engines/portfolio_engine.py`
+ `pages/6_Portfolio_Engine.py` look at the RESULT of your allocation
decisions as a whole:

- **Concentration** -- runs directly against `structural_grid.py`'s target
  weights (no scan or price data needed): flags any single position,
  layer, or section that breaches an editable limit, and checks your cash
  buffer. BTC/GOLD/CASH are excluded from position/layer breach checks
  (they're deliberate strategic sleeves, not accidentally oversized stock
  positions) but still count toward section totals and the cash-buffer check.
- **Correlation** -- for a chosen ticker set (defaults to your most recent
  Home.py Structural Grid Scan via `st.session_state`, or pick manually),
  fetches real price history in one batched `yf.download()` call, computes
  pairwise return correlation, and flags/clusters tickers that move
  together above a threshold -- catching cases where several "different"
  high-conviction picks are actually the same underlying bet.

## Ticker Verifier (new)

`pages/5_Ticker_Verifier.py` -- run any ticker (or a whole pasted list, or
the entire structural grid at once) through the same category of data
fetches the three scoring engines depend on, and see a pass/fail verdict
*before* trusting it. This is the tool that would have caught the
ADNOC Gas/ACWA Power duplicate, `ABB` resolving to the wrong company, and
`CEO`/`CHL` being dead NYSE tickers since 2021 -- all in one batch check,
instead of one back-and-forth per bad ticker.

Use the "Verify entire grid" tab any time you edit `structural_grid.py`.

## Known gaps / things to sanity-check before trusting the output

- **Ticker symbology has been verified against Yahoo Finance** for the
  non-US names (`8035.T` Tokyo Electron, `6920.T` Lasertec, `2222.SR`
  Aramco, `ADNOCGAS.AB` ADNOC Gas, `2082.SR` ACWA Power, `7010.SR` STC,
  `ABB.NS`/`POWERINDIA.NS`/etc. for India, `HIJP.L`/`ISDE.L`/`EIDO` for
  the ETF names, `0883.HK`/`0941.HK` for CNOOC/China Mobile -- both
  delisted from the NYSE in 2021 and now HKEX-only). Run the **Ticker
  Verifier** page (`pages/5_Ticker_Verifier.py`) → "Verify entire grid"
  any time you edit `structural_grid.py`, since new tickers you add
  yourself won't have been through this check.
- `CORE_ELIGIBLE_TICKERS` in `structural_grid.py` is a carried-over read
  of which tickers the *previous* version of the grid marked "can be used
  as core" -- the current grid image doesn't have an equivalent
  annotation column, so double-check this list still matches your intent
  (it drives which floor logic and caps apply in the Valuation Engine).
- Layer `effective_weight` is a **ceiling for the layer**, not an
  automatic even split across every ticker listed in it -- e.g. INFRA
  Layer 3 now has 7 tickers (VRT, BE, ANET, FTNT, CHKP, CRWD, ZS) sharing
  one 2.8% (=14%×20%) slice of the portfolio. The grid image listed
  `FTNT/CHKP` and `CRWD/ZS` as slash-separated either/or pairs; all four
  are included as separate rows here since a layer's weight is a shared
  ceiling rather than a per-ticker entitlement -- narrow each pair to one
  name yourself if that was the intent, or let the Conviction Score rank
  within the layer to decide.
