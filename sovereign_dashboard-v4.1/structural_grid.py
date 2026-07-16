"""
Structural Allocation Grid
===========================
Pure data encoding of the portfolio grid image (sections -> layers ->
target weights -> tickers -> thesis). Kept as pure data (no Streamlit, no
network calls) so any page/engine can import SECTIONS or call
flatten_universe() without side effects.

This replaces the previous version of this file -- the grid was revised:
target weights changed, the old "satellite" watchlist (Rail & Logistics,
Water & Waste Infra, Cyber Security, Networking, Energy/Materials/
Industrials, Human Healthcare) has been fully merged into the core
sections below, and a new "Business & Futuristic Overlay" section
(Health, Biotech & Longevity) was added.

Core portfolio (sums to 100%):
  INFRA 14% + ENERGY & COMMODITY 18% + AI/SEMIS 10% + EM 7%
  + Business & Futuristic Overlay 6% + BTC 25% + GOLD 10% + CASH 10% = 100%
"""

# ---------------------------------------------------------------------
# CORE SECTIONS (sums to 100% of the portfolio)
# ---------------------------------------------------------------------
SECTIONS = {
    "INFRA": {
        "target_pct": 0.14,
        "layers": {
            "Layer 1: Hard Assets": {
                "weight": 0.40,
                "tickers": ["TPL", "ADPORTS", "ICTEY", "CNI", "CP", "UNP"],
                "protocol": "Landowners, royalty engines, maritime ports, and Class I "
                            "transcontinental freight rail networks.",
            },
            "Layer 2: Grid & Utilities": {
                "weight": 0.40,
                "tickers": ["LIN", "ABBN.SW", "SU.PA", "GEV", "ETN", "NVT", "CEG", "PWR", "CWCO",
                            "XYL", "ECL", "WM", "RSG"],
                "protocol": "Industrial gases, power electrification, grid equipment, clean "
                            "nuclear energy for data centers, water tech, and environmental waste.",
            },
            "Layer 3: Tech-Adjacent": {
                "weight": 0.20,
                "tickers": ["VRT", "BE", "ANET", "FTNT", "CHKP", "CRWD", "ZS"],
                "protocol": "Data center liquid cooling, fuel cells, networking switches, and "
                            "zero-trust/perimeter cloud cybersecurity infrastructure. "
                            "(FTNT/CHKP and CRWD/ZS were listed as either/or pairs in the grid image "
                            "-- both members of each pair are included here since the layer weight is "
                            "a shared ceiling, not a per-ticker entitlement; narrow to one of each pair "
                            "yourself if that was the intent.)",
            },
        },
    },
    "ENERGY & COMMODITY": {
        "target_pct": 0.18,
        "layers": {
            "Layer 1: Monetary Royalties": {
                "weight": 0.40,
                "tickers": ["FNV", "WPM", "BSM", "DMLP"],
                "protocol": "Precious metals streaming and asset-light gold/silver royalty engines.",
            },
            "Layer 2: Baseload Energy": {
                "weight": 0.40,
                "tickers": ["CCJ", "CNQ", "XOM", "SU", "EQT", "CVX"],
                "protocol": "Uranium pure-plays for nuclear baseload, oil sands, natural gas, and "
                            "integrated global supermajors. (XOM = Light weighting only, per grid.)",
                "light_only": ["XOM"],
            },
            "Layer 3: Industrial Materials": {
                "weight": 0.20,
                "tickers": ["FCX", "SCCO", "BHP", "NEM", "COP", "NUE", "PH", "CAT"],
                "protocol": "Copper/iron mining for global electrification, efficient steel "
                            "production, and heavy construction/machinery standard equipment.",
            },
        },
    },
    "AI/SEMIS": {
        "target_pct": 0.10,
        "layers": {
            "Layer 1: Physical Monopolies": {
                "weight": 0.60,
                "tickers": ["TSM", "ASML", "SHECY", "6920.T"],  # 6920.T = Lasertec
                "protocol": "Structural monopolies in advanced foundries, EUV lithography systems, "
                            "silicon wafers, and EUV mask inspection equipment.",
            },
            "Layer 2: Architecture & Robotics": {
                "weight": 0.30,
                "tickers": ["AVGO", "CDNS", "QCOM", "FANUY", "8035.T", "SNPS"],  # 8035.T = Tokyo Electron
                "protocol": "Custom AI ASICs, electronic design automation (EDA) software, edge AI "
                            "silicon, and industrial factory robotics/automation.",
            },
            "Layer 3: Velocity Applications": {
                "weight": 0.10,
                "tickers": ["NOW", "PANW", "STX"],
                "protocol": "Enterprise generative AI workflow automation, platform cybersecurity, "
                            "and high-capacity mass cloud storage.",
                "core_eligible": ["PANW"],
            },
        },
    },
    "EM": {
        "target_pct": 0.07,
        "layers": {
            "Layer 1: INDIA": {
                "weight": 0.40,
                "tickers": ["ABB.NS", "SIEMENS.NS", "POWERINDIA.NS", "CGPOWER.NS", "PIIND.NS",
                            "SUNPHARMA.NS", "HCLTECH.NS"],
                # ABB.NS (not bare "ABB", which is Swiss ABB Ltd), POWERINDIA.NS (Hitachi Energy India;
                # "HITACHI-ENERGY" is not a real ticker) -- both verified against Yahoo Finance.
                "protocol": "Indian grid modernization, power transmission, agrochemicals, "
                            "pharmaceuticals, and enterprise IT services.",
            },
            "Layer 2: GCC": {
                "weight": 0.40,
                "tickers": ["2222.SR", "ADNOCGAS.AB", "2082.SR", "7010.SR"],
                # Aramco (Tadawul), ADNOC Gas (Abu Dhabi exchange -- NOT Tadawul; do not use .SR for
                # this one), ACWA Power (Tadawul), STC (Tadawul). All verified against Yahoo Finance.
                "protocol": "Highly cash-generative regional energy, natural gas processing, water "
                            "desalination, and telecom/digital infrastructure.",
            },
            "Layer 3: Other Jurisdiction": {
                "weight": 0.20,
                "tickers": ["TLK", "VALE", "0883.HK", "CSUAY", "0941.HK"],
                # TLK = Telkom Indonesia ADR (NYSE)
                # VALE = Vale S.A. ADR (NYSE)
                # 0883.HK = CNOOC Ltd (grid said "CEO") -- CEO was CNOOC's NYSE ADR ticker, delisted
                #           March 2021 under Executive Order 13959; now HKEX-only
                # CSUAY = China Shenhua Energy ADR (OTC)
                # 0941.HK = China Mobile Ltd (grid said "CHL") -- CHL was delisted from NYSE January
                #           2021 under the same executive order; now HKEX-only
                "protocol": "Resource-rich emerging markets (Brazil/Indonesia), proxy ETFs, and "
                            "dominant international infrastructure/telecom operators.",
            },
        },
    },
    "Business & Futuristic Overlay": {
        "target_pct": 0.06,
        "layers": {
            "NVO": {
                "weight": 0.30,
                "tickers": ["NVO"],
                "protocol": "Global metabolic healthcare leader dominating GLP-1/obesity/diabetes "
                            "secular growth engines.",
                "core_eligible": ["NVO"],
            },
            "AZN": {
                "weight": 0.25,
                "tickers": ["AZN"],
                "protocol": "Advanced oncology, complex rare disease therapeutics, and deep "
                            "biopharmaceutical pipeline depth.",
            },
            "ISRG": {
                "weight": 0.25,
                "tickers": ["ISRG"],
                "protocol": "Structural monopoly in da Vinci robotic-assisted minimally invasive "
                            "surgery ecosystems.",
            },
            "TMO": {
                "weight": 0.20,
                "tickers": ["TMO"],
                "protocol": "The universal foundational provider of life sciences tools, reagents, "
                            "and laboratory equipment.",
            },
        },
    },
    "BTC": {"target_pct": 0.25, "tickers": ["BTC"], "protocol": "Cold wallet."},
    "GOLD": {"target_pct": 0.10, "tickers": ["GOLD"], "protocol": "Physical."},
    "CASH": {"target_pct": 0.10, "tickers": ["CASH"], "protocol": "Tactical parking / dry powder."},
}

# No separate satellite tier in this version of the grid -- everything that
# used to live in SATELLITE (Rail & Logistics, Water & Waste Infra, Cyber
# Security, Networking, Energy/Materials/Industrials, Human Healthcare) has
# been folded directly into the core sections above. Kept as an empty dict
# so any code that iterates SATELLITE (none currently does outside
# flatten_universe) doesn't break.
SATELLITE = {}


def flatten_universe() -> list[dict]:
    """
    Flattens SECTIONS (+ SATELLITE, currently empty) into one row-per-ticker
    list: [{"ticker", "section", "layer", "layer_weight", "section_target_pct",
    "effective_weight", "protocol", "group"}]

    effective_weight = section_target_pct * layer_weight -- i.e. this
    ticker's slice of the *whole portfolio*, before you decide how many
    tickers within a layer actually get funded. Layers with N permissible
    tickers do NOT automatically split evenly across them; effective_weight
    is the layer's ceiling, not a per-ticker entitlement. Use it as an
    upper bound when ranking within a layer.

    Exception: "Business & Futuristic Overlay" layers each contain exactly
    one ticker with an explicit weight (30/25/25/20), so effective_weight
    for those four IS the actual per-ticker target, not a shared ceiling.
    """
    rows = []

    for section_name, section in SECTIONS.items():
        target_pct = section.get("target_pct")
        if "layers" in section:
            for layer_name, layer in section["layers"].items():
                for ticker in layer["tickers"]:
                    rows.append({
                        "ticker": ticker,
                        "section": section_name,
                        "layer": layer_name,
                        "layer_weight": layer["weight"],
                        "section_target_pct": target_pct,
                        "effective_weight": (target_pct or 0) * layer["weight"],
                        "protocol": layer.get("protocol", ""),
                        "group": "core",
                    })
        else:
            for ticker in section["tickers"]:
                rows.append({
                    "ticker": ticker,
                    "section": section_name,
                    "layer": section_name,
                    "layer_weight": 1.0,
                    "section_target_pct": target_pct,
                    "effective_weight": target_pct or 0,
                    "protocol": section.get("protocol", ""),
                    "group": "core",
                })

    for section_name, section in SATELLITE.items():
        target_pct = section.get("target_pct")
        for ticker in section["tickers"]:
            rows.append({
                "ticker": ticker,
                "section": section_name,
                "layer": section_name,
                "layer_weight": 1.0,
                "section_target_pct": target_pct,
                "effective_weight": target_pct or 0,
                "protocol": section.get("protocol", ""),
                "group": "satellite",
            })

    return rows


# Tickers that are non-equity (skip in engines that need P/S / revenue data)
NON_EQUITY_TICKERS = {"BTC", "GOLD", "CASH"}

# Tickers explicitly marked "core eligible" in the grid, or a natural core
# read given their thesis (land/royalty/monopoly-style holdings) -- drives
# is_core in the Valuation Engine. This version of the grid doesn't carry
# an explicit "can be used as core" annotation column like the previous
# one did, so this list is carried over from the prior grid's annotations
# where the same tickers still appear here -- double check it still
# matches your intent.
CORE_ELIGIBLE_TICKERS = {
    "TPL", "ADPORTS", "ICTEY", "CNI", "CP", "FNV", "WPM", "TSM", "ASML", "PANW",
    "NVO", "XYL", "WM", "RSG",
}
