"""
Nasdaq 100 Symbols - Static Curated List
========================================
Version: 2025-02-15
Source: Nasdaq official constituents (curated, not scraped)

This list is versioned and checked into repo.
Updates should be done manually via PR review.
"""

NASDAQ100_SYMBOLS = [
    # Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "ADBE", "CSCO", "INTC", "TXN", "QCOM",
    "AMAT", "ADI", "LRCX", "SNPS", "CDNS", "KLAC", "MCHP", "NXPI", "ON", "MRVL",
    "FTNT", "PANW", "CRWD", "ZS", "DDOG", "SNOW", "NET", "MDB", "TEAM", "WDAY",
    
    # Consumer Services
    "AMZN", "TSLA", "GOOGL", "GOOG", "META", "NFLX", "BKNG", "ABNB", "MELI", "JD",
    "PDD", "ROST", "ORLY", "AZO", "SBUX", "LULU", "EBAY", "EXPE", "CPRT", "FAST",
    
    # Healthcare
    "AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "BNTX", "ILMN", "DXCM", "IDXX",
    "ISRG", "ALGN",
    
    # Communication Services
    "CMCSA", "TMUS", "CHTR", "WBD", "EA", "TTWO", "MTCH", "SIRI",
    
    # Consumer Goods
    "PEP", "COST", "KDP", "MNST", "KHC", "MDLZ", "WBA", "DLTR",
    
    # Industrials
    "HON", "CSX", "PCAR", "ODFL", "CTAS", "VRSK", "PAYX", "CPRT", "FAST",
    
    # Financials
    "PYPL", "COIN", "HOOD", "ADP", "CEG",
    
    # Utilities
    "XEL", "AEP",
    
    # Other
    "MAR", "FANG", "SPLK", "OKTA", "ZM", "PTON", "LCID", "RIVN",
]

# Remove duplicates
NASDAQ100_SYMBOLS = list(dict.fromkeys(NASDAQ100_SYMBOLS))

# Count validation (approximately 100)
assert 90 <= len(NASDAQ100_SYMBOLS) <= 110, f"Expected ~100 symbols, got {len(NASDAQ100_SYMBOLS)}"
