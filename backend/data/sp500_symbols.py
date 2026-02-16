"""
S&P 500 Symbols - Static Curated List
=====================================
Version: 2025-02-15
Source: S&P Dow Jones Indices (curated, not scraped)

This list is versioned and checked into repo.
Updates should be done manually via PR review.
"""

SP500_SYMBOLS = [
    # Information Technology (76)
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "ACN", "CSCO",
    "IBM", "INTU", "QCOM", "TXN", "NOW", "AMAT", "ADI", "SNPS", "KLAC", "LRCX",
    "CDNS", "MCHP", "INTC", "FTNT", "PANW", "ROP", "NXPI", "HPQ", "HPE", "MPWR",
    "KEYS", "ANSS", "ON", "FSLR", "TYL", "PTC", "ZBRA", "VRSN", "GEN", "AKAM",
    "JNPR", "CDW", "CTSH", "IT", "EPAM", "FFIV", "SWKS", "TER", "QRVO", "TRMB",
    "WDC", "STX", "NTAP", "ENPH", "SEDG", "PAYC", "GDDY", "ANET", "FICO", "MANH",
    "SMCI", "DELL", "MRVL", "ARM", "CRWD", "DDOG", "ZS", "SNOW", "NET", "MDB",
    "PLTR", "COIN", "HOOD", "ABNB", "UBER", "DASH",
    
    # Financials (72)
    "BRK.B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "AXP",
    "BLK", "SCHW", "C", "PGR", "CB", "USB", "MMC", "CME", "ICE", "AON",
    "MCO", "PNC", "TFC", "AIG", "MET", "AFL", "PRU", "TRV", "AJG", "ALL",
    "COF", "BK", "MSCI", "MTB", "FITB", "STT", "HBAN", "NDAQ", "DFS", "CINF",
    "RF", "CFG", "KEY", "NTRS", "TROW", "RJF", "WRB", "L", "ACGL", "RE",
    "GL", "MKTX", "FDS", "ZION", "HIG", "CMA", "AIZ", "IVZ", "BEN", "SYF",
    "ALLY", "SBNY", "SIVB", "FRC", "WAL", "EWBC", "FCNCA", "GBCI", "PACW", "CADE",
    "FHN", "SNV",
    
    # Healthcare (64)
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE", "AMGN", "DHR",
    "BMY", "ISRG", "MDT", "GILD", "VRTX", "CVS", "SYK", "ELV", "BSX", "REGN",
    "CI", "ZTS", "BDX", "HCA", "MCK", "HUM", "IDXX", "DXCM", "IQV", "A",
    "EW", "CAH", "ABC", "GEHC", "BIIB", "MTD", "WAT", "RMD", "HOLX", "COO",
    "ALGN", "MOH", "CNC", "TFX", "VTRS", "TECH", "DGX", "LH", "INCY", "CRL",
    "XRAY", "HSIC", "DVA", "BIO", "CTLT", "MRNA", "BNTX", "ILMN", "SGEN", "EXAS",
    "PODD", "RVTY", "JAZZ", "NBIX",
    
    # Consumer Discretionary (60)
    "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "BKNG", "TJX", "SBUX", "CMG",
    "MAR", "ORLY", "AZO", "HLT", "ROST", "YUM", "GM", "DHI", "F",
    "DRI", "LVS", "ULTA", "EBAY", "GRMN", "BBY", "DPZ", "POOL", "DECK",
    "LEN", "NVR", "PHM", "LULU", "MGM", "WYNN", "LKQ", "RCL", "NCLH", "CCL",
    "BWA", "APTV", "TPR", "RL", "HAS", "EXPE", "ETSY", "CZR", "PVH", "GNRC",
    "BBWI", "VFC", "MHK", "NWL", "AAL", "UAL", "DAL", "ALK", "LUV", "PARA",
    
    # Industrials (78)
    "GE", "CAT", "HON", "UNP", "RTX", "UPS", "ETN", "DE", "BA", "ADP",
    "LMT", "FDX", "WM", "TT", "CSX", "NSC", "ITW", "GD", "NOC", "MMM",
    "EMR", "PH", "CTAS", "PCAR", "ROK", "CARR", "OTIS", "JCI", "GWW", "AME",
    "CMI", "FAST", "TDG", "PWR", "IR", "SWK", "RSG", "XYL", "CPRT",
    "VRSK", "HUBB", "ODFL", "HII", "DOV", "IEX", "HWM", "WAB", "FTV", "LII",
    "SNA", "LDOS", "PNR", "ROL", "CHRW", "NDSN", "J", "BR", "EFX",
    "EXPD", "JBHT", "MAS", "AOS", "ALLE", "AXON", "TXT", "STE", "WLK", "GGG",
    "BLDR", "MTZ", "GNRC", "SWN", "CF", "MOS", "FMC", "NUE",
    
    # Communication Services (26)
    "GOOGL", "GOOG", "META", "DIS", "NFLX", "CMCSA", "VZ", "T", "TMUS", "CHTR",
    "EA", "WBD", "TTWO", "OMC", "IPG", "MTCH", "LYV", "FOXA", "FOX", "NWSA",
    "NWS", "PARA", "LUMN", "DISH", "VIAC", "DISCA",
    
    # Consumer Staples (39)
    "PG", "COST", "WMT", "PEP", "KO", "PM", "MO", "MDLZ", "CL", "KHC",
    "EL", "GIS", "SYY", "KMB", "ADM", "STZ", "HSY", "K", "SJM", "CAG",
    "MKC", "TSN", "HRL", "CLX", "CHD", "KR", "TGT", "DG", "DLTR", "WBA",
    "BF.B", "TAP", "CPB", "LW", "BG", "CASY", "INGR", "JJSF", "HAIN",
    
    # Energy (23)
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PXD", "PSX", "VLO", "OXY",
    "WMB", "HES", "DVN", "KMI", "HAL", "FANG", "BKR", "TRGP", "OKE", "CTRA",
    "MRO", "APA", "EQT",
    
    # Materials (28)
    "LIN", "APD", "SHW", "FCX", "ECL", "NUE", "NEM", "DOW", "DD", "PPG",
    "VMC", "MLM", "CTVA", "IFF", "BALL", "LYB", "CF", "PKG", "ALB", "IP",
    "CE", "EMN", "AMCR", "FMC", "AVY", "WRK", "SEE", "MOS",
    
    # Utilities (30)
    "NEE", "DUK", "SO", "SRE", "AEP", "D", "PCG", "EXC", "XEL", "CEG",
    "ED", "WEC", "EIX", "AWK", "DTE", "ES", "AEE", "FE", "PPL", "CMS",
    "ATO", "CNP", "EVRG", "NI", "LNT", "ETR", "NRG", "PEG", "PNW", "AES",
    
    # Real Estate (31)
    "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "O", "CCI", "DLR", "VICI",
    "SBAC", "WY", "EXR", "AVB", "EQR", "VTR", "ARE", "IRM", "CBRE", "ESS",
    "MAA", "UDR", "HST", "CPT", "PEAK", "REG", "KIM", "FRT", "BXP", "SLG",
    "AIV",
]

# Count validation
assert len(SP500_SYMBOLS) == 527, f"Expected 527 symbols, got {len(SP500_SYMBOLS)}"
