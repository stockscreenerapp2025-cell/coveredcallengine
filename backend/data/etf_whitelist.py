"""
ETF Whitelist - Static Curated List
====================================
Version: 2025-02-15
Source: Most liquid options ETFs (curated for covered call/PMCC strategies)

This list is versioned and checked into repo.
Updates should be done manually via PR review.

ETFs bypass market cap requirements but must exist in us_symbol_master.
ETFs skip fundamental data fetch (no earnings, no P/E, etc.)
"""

ETF_WHITELIST = [
    # Major Index ETFs (most liquid)
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    "DIA",   # Dow Jones
    "VOO",   # Vanguard S&P 500
    "VTI",   # Vanguard Total Market
    "IVV",   # iShares S&P 500
    "VTV",   # Vanguard Value
    "VUG",   # Vanguard Growth
    "RSP",   # Equal Weight S&P 500
    
    # Sector ETFs (Select Sector SPDRs)
    "XLF",   # Financials
    "XLE",   # Energy
    "XLK",   # Technology
    "XLV",   # Healthcare
    "XLI",   # Industrials
    "XLB",   # Materials
    "XLU",   # Utilities
    "XLP",   # Consumer Staples
    "XLY",   # Consumer Discretionary
    "XLRE",  # Real Estate
    "XLC",   # Communication Services
    
    # Semiconductor/Tech Sector
    "SMH",   # VanEck Semiconductor
    "SOXX",  # iShares Semiconductor
    "XBI",   # Biotech
    "IBB",   # iShares Biotech
    "KWEB",  # China Internet
    "HACK",  # Cybersecurity
    "SKYY",  # Cloud Computing
    
    # Commodity ETFs
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "GDX",   # Gold Miners
    "GDXJ",  # Junior Gold Miners
    "XME",   # Metals & Mining
    "XOP",   # Oil & Gas Exploration
    "OIH",   # Oil Services
    
    # Bond ETFs
    "TLT",   # 20+ Year Treasury
    "HYG",   # High Yield Corporate
    "LQD",   # Investment Grade Corporate
    "IEF",   # 7-10 Year Treasury
    "SHY",   # 1-3 Year Treasury
    "TIP",   # TIPS
    "BND",   # Vanguard Total Bond
    "AGG",   # iShares Core Aggregate Bond
    "JNK",   # High Yield Bond
    "EMB",   # Emerging Market Bond
    
    # International
    "EEM",   # Emerging Markets
    "EFA",   # Developed Markets ex-US
    "FXI",   # China Large Cap
    "EWZ",   # Brazil
    "EWJ",   # Japan
    "VWO",   # Vanguard Emerging Markets
    "VEA",   # Vanguard Developed Markets
    "IEMG",  # iShares Core Emerging Markets
    "INDA",  # India
    "EWT",   # Taiwan
    
    # Volatility & Leveraged (high premium)
    "VXX",   # VIX Short-Term Futures
    "UVXY",  # 1.5x VIX Short-Term
    "SVXY",  # Short VIX
    "SQQQ",  # 3x Inverse Nasdaq
    "TQQQ",  # 3x Nasdaq
    "SPXU",  # 3x Inverse S&P
    "SPXL",  # 3x S&P
    "SOXL",  # 3x Semiconductors
    "SOXS",  # 3x Inverse Semiconductors
    "LABU",  # 3x Biotech
    "LABD",  # 3x Inverse Biotech
    "NUGT",  # 2x Gold Miners
    "DUST",  # 2x Inverse Gold Miners
    "TNA",   # 3x Small Cap
    "TZA",   # 3x Inverse Small Cap
    
    # Thematic / ARK
    "ARKK",  # ARK Innovation
    "ARKG",  # ARK Genomic
    "ARKW",  # ARK Next Gen Internet
    "ARKF",  # ARK Fintech
    "ARKQ",  # ARK Autonomous Tech
    
    # Dividend/Income
    "DVY",   # Select Dividend
    "VYM",   # Vanguard High Dividend
    "SCHD",  # Schwab US Dividend
    "HDV",   # iShares Core High Dividend
    "SDY",   # S&P High Yield Dividend
    
    # Small/Mid Cap
    "IJR",   # S&P SmallCap 600
    "IJH",   # S&P MidCap 400
    "MDY",   # S&P MidCap 400 (SPDR)
    "VB",    # Vanguard Small Cap
    "VO",    # Vanguard Mid Cap
    "SLY",   # S&P 600 Small Cap
    
    # Real Estate
    "VNQ",   # Vanguard Real Estate
    "IYR",   # iShares US Real Estate
    "XLRE",  # Real Estate Select Sector
]

# Remove duplicates
ETF_WHITELIST = list(dict.fromkeys(ETF_WHITELIST))

# Count validation
assert len(ETF_WHITELIST) >= 90, f"Expected at least 90 ETFs, got {len(ETF_WHITELIST)}"
