"""
LEAPS-Safe Universe
===================
Curated list of symbols known to consistently have LEAPS (365+ DTE) options available.

These are highly liquid symbols where Yahoo Finance reliably returns far-dated expirations.
Used by PMCC scanner to ensure valid LEAPS candidates exist.

Selection criteria:
- Top 100 most liquid US equities by options volume
- Confirmed LEAPS availability on major options exchanges
- SPY, QQQ, IWM and other major ETFs always included

Last updated: 2026-02-16
"""

# Tier 1: Major Index ETFs (always have LEAPS)
LEAPS_SAFE_ETFS = [
    "SPY",   # S&P 500 ETF
    "QQQ",   # Nasdaq 100 ETF
    "IWM",   # Russell 2000 ETF
    "DIA",   # Dow Jones ETF
    "XLF",   # Financials ETF
    "XLE",   # Energy ETF
    "XLK",   # Technology ETF
    "XLV",   # Healthcare ETF
    "XLI",   # Industrials ETF
    "GLD",   # Gold ETF
    "SLV",   # Silver ETF
    "TLT",   # 20+ Year Treasury ETF
    "EEM",   # Emerging Markets ETF
    "EFA",   # EAFE ETF
    "HYG",   # High Yield Bond ETF
]

# Tier 2: Mega-cap tech (always have LEAPS)
LEAPS_SAFE_TECH = [
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "GOOGL", # Alphabet
    "AMZN",  # Amazon
    "META",  # Meta
    "NVDA",  # NVIDIA
    "TSLA",  # Tesla
    "AMD",   # AMD
    "INTC",  # Intel
    "CRM",   # Salesforce
    "ORCL",  # Oracle
    "ADBE",  # Adobe
    "NFLX",  # Netflix
    "CSCO",  # Cisco
    "AVGO",  # Broadcom
    "TXN",   # Texas Instruments
    "QCOM",  # Qualcomm
    "IBM",   # IBM
    "PYPL",  # PayPal
    "SQ",    # Block
]

# Tier 3: Mega-cap financials and industrials
LEAPS_SAFE_FINANCIALS = [
    "JPM",   # JPMorgan Chase
    "BAC",   # Bank of America
    "WFC",   # Wells Fargo
    "GS",    # Goldman Sachs
    "MS",    # Morgan Stanley
    "C",     # Citigroup
    "AXP",   # American Express
    "V",     # Visa
    "MA",    # Mastercard
    "BLK",   # BlackRock
]

# Tier 4: Other mega-caps with reliable LEAPS
LEAPS_SAFE_OTHER = [
    "JNJ",   # Johnson & Johnson
    "UNH",   # UnitedHealth
    "PFE",   # Pfizer
    "MRK",   # Merck
    "ABBV",  # AbbVie
    "LLY",   # Eli Lilly
    "BMY",   # Bristol-Myers
    "CVX",   # Chevron
    "XOM",   # Exxon
    "COP",   # ConocoPhillips
    "HD",    # Home Depot
    "LOW",   # Lowe's
    "WMT",   # Walmart
    "COST",  # Costco
    "TGT",   # Target
    "DIS",   # Disney
    "CMCSA", # Comcast
    "T",     # AT&T
    "VZ",    # Verizon
    "BA",    # Boeing
    "CAT",   # Caterpillar
    "GE",    # GE
    "MMM",   # 3M
    "HON",   # Honeywell
    "UPS",   # UPS
    "FDX",   # FedEx
    "F",     # Ford
    "GM",    # GM
    "KO",    # Coca-Cola
    "PEP",   # PepsiCo
    "MCD",   # McDonald's
    "SBUX",  # Starbucks
    "NKE",   # Nike
]

# Combined LEAPS-safe universe
LEAPS_SAFE_UNIVERSE = (
    LEAPS_SAFE_ETFS +
    LEAPS_SAFE_TECH +
    LEAPS_SAFE_FINANCIALS +
    LEAPS_SAFE_OTHER
)

# Remove duplicates
LEAPS_SAFE_UNIVERSE = list(dict.fromkeys(LEAPS_SAFE_UNIVERSE))

# Validation
assert len(LEAPS_SAFE_UNIVERSE) >= 70, f"Expected at least 70 LEAPS-safe symbols, got {len(LEAPS_SAFE_UNIVERSE)}"


def is_leaps_safe(symbol: str) -> bool:
    """Check if a symbol is in the curated LEAPS-safe universe."""
    return symbol.upper() in LEAPS_SAFE_UNIVERSE


def get_leaps_safe_universe() -> list:
    """Get the curated LEAPS-safe universe."""
    return LEAPS_SAFE_UNIVERSE.copy()
