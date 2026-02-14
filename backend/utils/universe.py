"""
Universe Builder - Symbol Universe Management
==============================================

Manages the scan universe with tiered symbol lists:
- Tier 1: S&P 500 constituents
- Tier 2: Nasdaq 100 (net of S&P 500 overlap)
- Tier 3: ETF whitelist (liquid options ETFs)

Configuration:
- MAX_SCAN_UNIVERSE: Maximum symbols to scan (env variable, default 700)

ETF Handling:
- is_etf(symbol): Returns True if symbol is an ETF
- ETFs skip fundamental data fetch (no 404 errors)
- ETFs use relaxed filters (no market cap, earnings checks)
"""
import os
from typing import List, Dict, Set, Tuple
import logging

logger = logging.getLogger(__name__)

# ============================================================
# ETF WHITELIST (Tier 3) - ~50 liquid options ETFs
# ============================================================
# Liquid options ETFs with good bid/ask spreads
# These skip fundamental data fetch entirely

ETF_WHITELIST: Set[str] = {
    # Major Index ETFs
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    "DIA",   # Dow Jones
    "VOO",   # Vanguard S&P 500
    "VTI",   # Vanguard Total Market
    "IVV",   # iShares S&P 500
    
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
    
    # Commodity ETFs
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "GDX",   # Gold Miners
    "GDXJ",  # Junior Gold Miners
    "XME",   # Metals & Mining
    
    # Bond ETFs
    "TLT",   # 20+ Year Treasury
    "HYG",   # High Yield Corporate
    "LQD",   # Investment Grade Corporate
    "IEF",   # 7-10 Year Treasury
    "SHY",   # 1-3 Year Treasury
    "TIP",   # TIPS
    "BND",   # Vanguard Total Bond
    
    # International
    "EEM",   # Emerging Markets
    "EFA",   # Developed Markets ex-US
    "FXI",   # China Large Cap
    "EWZ",   # Brazil
    "EWJ",   # Japan
    "VWO",   # Vanguard Emerging Markets
    
    # Volatility & Leveraged (high premium)
    "VXX",   # VIX Short-Term Futures
    "UVXY",  # 1.5x VIX Short-Term
    "SQQQ",  # 3x Inverse Nasdaq
    "TQQQ",  # 3x Nasdaq
    "SPXU",  # 3x Inverse S&P
    "SPXL",  # 3x S&P
    "SOXL",  # 3x Semiconductors
    "SOXS",  # 3x Inverse Semiconductors
    
    # Thematic / ARK
    "ARKK",  # ARK Innovation
    "ARKG",  # ARK Genomic
    "ARKW",  # ARK Next Gen Internet
    "ARKF",  # ARK Fintech
    "XBI",   # Biotech
    "SMH",   # Semiconductors
    "KWEB",  # China Internet
    
    # Small/Mid Cap
    "IJR",   # S&P SmallCap 600
    "IJH",   # S&P MidCap 400
    "MDY",   # S&P MidCap 400 (SPDR)
    "VB",    # Vanguard Small Cap
}

# ============================================================
# S&P 500 CONSTITUENTS (Tier 1) - Full 500
# ============================================================
# Complete S&P 500 list as of 2025
# Source: Standard & Poor's official constituents

SP500_SYMBOLS: List[str] = [
    # Information Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "ACN", "CSCO",
    "IBM", "INTU", "QCOM", "TXN", "NOW", "AMAT", "ADI", "SNPS", "KLAC", "LRCX",
    "CDNS", "MCHP", "INTC", "FTNT", "PANW", "ROP", "NXPI", "HPQ", "HPE", "MPWR",
    "KEYS", "ANSS", "ON", "FSLR", "TYL", "PTC", "ZBRA", "VRSN", "GEN", "AKAM",
    "JNPR", "CDW", "CTSH", "IT", "EPAM", "FFIV", "SWKS", "TER", "QRVO", "TRMB",
    "WDC", "STX", "NTAP",
    
    # Financials (Note: BRK.B for Yahoo format)
    "BRK.B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI", "AXP",
    "BLK", "SCHW", "C", "PGR", "CB", "USB", "MMC", "CME", "ICE", "AON",
    "MCO", "PNC", "TFC", "AIG", "MET", "AFL", "PRU", "TRV", "AJG", "ALL",
    "COF", "BK", "MSCI", "MTB", "FITB", "STT", "HBAN", "NDAQ", "DFS", "CINF",
    "RF", "CFG", "KEY", "NTRS", "TROW", "RJF", "WRB", "L", "ACGL", "RE",
    "GL", "MKTX", "FDS", "LNC", "ZION", "HIG", "CMA", "AIZ", "IVZ", "BEN",
    
    # Healthcare
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE", "AMGN", "DHR",
    "BMY", "ISRG", "MDT", "GILD", "VRTX", "CVS", "SYK", "ELV", "BSX", "REGN",
    "CI", "ZTS", "BDX", "HCA", "MCK", "HUM", "IDXX", "DXCM", "IQV", "A",
    "EW", "CAH", "ABC", "GEHC", "BIIB", "MTD", "WAT", "RMD", "HOLX", "COO",
    "ALGN", "MOH", "CNC", "TFX", "VTRS", "TECH", "DGX", "LH", "INCY", "CRL",
    "XRAY", "HSIC", "DVA", "BIO", "CTLT",
    
    # Consumer Discretionary (removed PARA - duplicate in Comm Services)
    "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "BKNG", "TJX", "SBUX", "CMG",
    "MAR", "ORLY", "AZO", "HLT", "ROST", "YUM", "GM", "ABNB", "DHI", "F",
    "DRI", "LVS", "ULTA", "EBAY", "GRMN", "BBY", "DPZ", "POOL", "DECK",
    "LEN", "NVR", "PHM", "LULU", "MGM", "WYNN", "LKQ", "RCL", "NCLH", "CCL",
    "BWA", "APTV", "TPR", "RL", "HAS", "EXPE", "ETSY", "CZR", "PVH", "GNRC",
    "BBWI", "VFC", "MHK", "NWL", "AAL", "UAL", "DAL", "ALK", "LUV",
    
    # Industrials
    "GE", "CAT", "HON", "UNP", "RTX", "UPS", "ETN", "DE", "BA", "ADP",
    "LMT", "FDX", "WM", "TT", "CSX", "NSC", "ITW", "GD", "NOC", "MMM",
    "EMR", "PH", "CTAS", "PCAR", "ROK", "CARR", "OTIS", "JCI", "GWW", "AME",
    "CMI", "FAST", "TDG", "PWR", "IR", "SWK", "RSG", "DAL", "XYL", "CPRT",
    "VRSK", "HUBB", "ODFL", "HII", "DOV", "IEX", "HWM", "WAB", "FTV", "LII",
    "SNA", "LDOS", "PNR", "ROL", "GNRC", "CHRW", "NDSN", "J", "BR", "EFX",
    "EXPD", "PAYC", "JBHT", "MAS", "AOS", "ALLE",
    
    # Communication Services
    "GOOGL", "GOOG", "META", "DIS", "NFLX", "CMCSA", "VZ", "T", "TMUS", "CHTR",
    "EA", "WBD", "TTWO", "OMC", "IPG", "MTCH", "LYV", "FOXA", "FOX", "NWSA",
    "NWS", "PARA",
    
    # Consumer Staples (Note: BF.B for Yahoo format)
    "PG", "COST", "WMT", "PEP", "KO", "PM", "MO", "MDLZ", "CL", "KHC",
    "EL", "GIS", "SYY", "KMB", "ADM", "STZ", "HSY", "K", "SJM", "CAG",
    "MKC", "TSN", "HRL", "CLX", "CHD", "KR", "TGT", "DG", "DLTR", "WBA",
    "BF.B", "TAP", "CPB", "LW", "BG",
    
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PXD", "PSX", "VLO", "OXY",
    "WMB", "HES", "DVN", "KMI", "HAL", "FANG", "BKR", "TRGP", "OKE", "CTRA",
    "MRO", "APA", "EQT",
    
    # Materials
    "LIN", "APD", "SHW", "FCX", "ECL", "NUE", "NEM", "DOW", "DD", "PPG",
    "VMC", "MLM", "CTVA", "IFF", "BALL", "LYB", "CF", "PKG", "ALB", "IP",
    "CE", "EMN", "AMCR", "FMC", "AVY", "WRK", "SEE", "MOS",
    
    # Utilities
    "NEE", "DUK", "SO", "SRE", "AEP", "D", "PCG", "EXC", "XEL", "CEG",
    "ED", "WEC", "EIX", "AWK", "DTE", "ES", "AEE", "FE", "PPL", "CMS",
    "ATO", "CNP", "EVRG", "NI", "LNT", "ETR", "NRG", "PEG", "PNW",
    
    # Real Estate
    "PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "O", "CCI", "DLR", "VICI",
    "SBAC", "WY", "EXR", "AVB", "EQR", "VTR", "ARE", "IRM", "CBRE", "ESS",
    "MAA", "UDR", "HST", "CPT", "PEAK", "REG", "KIM", "FRT", "BXP", "SLG",
    "AIV",
    
    # High Growth / Recent Additions
    "PLTR", "SOFI", "COIN", "HOOD", "RIVN", "LCID", "SNOW", "NET", "DDOG", "ZS",
    "CRWD", "PATH", "DOCN", "BILL", "RBLX", "U",
]

# ============================================================
# NASDAQ 100 CONSTITUENTS (Tier 2 - net of S&P overlap)
# ============================================================
# Nasdaq 100 symbols NOT already in S&P 500
# Removed: SPLK (acquired by Cisco 2024), SGEN (acquired by Pfizer 2023)

NASDAQ100_NET: List[str] = [
    # Chinese ADRs (not in S&P)
    "BIDU", "JD", "PDD", "NTES", 
    
    # Tech not yet in S&P (removed SPLK - acquired)
    "MELI", "TEAM", "WDAY", "ZM", "OKTA", "VEEV", "MDB", "DKNG",
    "PTON", "MRNA", "BNTX", "ILMN",
    
    # Other Nasdaq 100 not in S&P
    "MRVL", "KDP", "MNST", "SIRI",
]


def is_etf(symbol: str) -> bool:
    """
    Check if a symbol is an ETF.
    
    ETFs receive special handling in scans:
    - Skip fundamental data fetch (no market cap, P/E, etc.)
    - Skip earnings date checks
    - Use relaxed price band filters
    - No fundamental 404 errors logged
    
    Args:
        symbol: Stock/ETF ticker symbol
        
    Returns:
        True if symbol is in the ETF whitelist
    """
    return symbol.upper() in ETF_WHITELIST


def get_universe_config() -> Dict:
    """
    Get universe configuration from environment.
    
    Environment Variables:
    - MAX_SCAN_UNIVERSE: Maximum symbols to include (default 700)
    - UNIVERSE_INCLUDE_ETF: Include ETF whitelist (default True)
    - UNIVERSE_INCLUDE_NASDAQ: Include Nasdaq 100 net (default True)
    
    Returns:
        Configuration dictionary
    """
    return {
        "max_scan_universe": int(os.environ.get("MAX_SCAN_UNIVERSE", "700")),
        "include_etf": os.environ.get("UNIVERSE_INCLUDE_ETF", "true").lower() == "true",
        "include_nasdaq": os.environ.get("UNIVERSE_INCLUDE_NASDAQ", "true").lower() == "true",
    }


def build_scan_universe() -> Tuple[List[str], Dict[str, int]]:
    """
    Build the complete scan universe with tier counts.
    
    Tiers are added in order:
    1. S&P 500 constituents (Tier 1)
    2. Nasdaq 100 net of S&P overlap (Tier 2)
    3. ETF whitelist (Tier 3)
    
    Duplicates are removed while preserving tier priority.
    
    Returns:
        Tuple of (symbol_list, tier_counts)
        
    tier_counts format:
    {
        "sp500": 200,
        "nasdaq100_net": 50,
        "etf_whitelist": 30,
        "liquidity_expansion": 0,  # Reserved for future
        "total": 280
    }
    """
    config = get_universe_config()
    max_universe = config["max_scan_universe"]
    
    universe: List[str] = []
    seen: Set[str] = set()
    tier_counts = {
        "sp500": 0,
        "nasdaq100_net": 0,
        "etf_whitelist": 0,
        "liquidity_expansion": 0,  # Reserved for future use
        "total": 0
    }
    
    # Tier 1: S&P 500
    for symbol in SP500_SYMBOLS:
        sym_upper = symbol.upper()
        if sym_upper not in seen and len(universe) < max_universe:
            universe.append(sym_upper)
            seen.add(sym_upper)
            tier_counts["sp500"] += 1
    
    # Tier 2: Nasdaq 100 (net of S&P overlap)
    if config["include_nasdaq"]:
        for symbol in NASDAQ100_NET:
            sym_upper = symbol.upper()
            if sym_upper not in seen and len(universe) < max_universe:
                universe.append(sym_upper)
                seen.add(sym_upper)
                tier_counts["nasdaq100_net"] += 1
    
    # Tier 3: ETF whitelist
    if config["include_etf"]:
        for symbol in sorted(ETF_WHITELIST):
            sym_upper = symbol.upper()
            if sym_upper not in seen and len(universe) < max_universe:
                universe.append(sym_upper)
                seen.add(sym_upper)
                tier_counts["etf_whitelist"] += 1
    
    tier_counts["total"] = len(universe)
    
    logger.info(
        f"Universe built: {tier_counts['total']} symbols "
        f"(S&P500: {tier_counts['sp500']}, "
        f"Nasdaq100 net: {tier_counts['nasdaq100_net']}, "
        f"ETFs: {tier_counts['etf_whitelist']})"
    )
    
    return universe, tier_counts


def get_symbol_tier(symbol: str) -> str:
    """
    Get the tier classification for a symbol.
    
    Args:
        symbol: Stock/ETF ticker symbol
        
    Returns:
        Tier name: "sp500", "nasdaq100", "etf", or "unknown"
    """
    sym_upper = symbol.upper()
    
    if sym_upper in ETF_WHITELIST:
        return "etf"
    if sym_upper in SP500_SYMBOLS:
        return "sp500"
    if sym_upper in NASDAQ100_NET:
        return "nasdaq100"
    
    return "unknown"


# Pre-build universe on module load for performance
_SCAN_UNIVERSE: List[str] = []
_TIER_COUNTS: Dict[str, int] = {}


def get_scan_universe() -> List[str]:
    """
    Get the pre-built scan universe.
    
    Returns cached universe list, builds on first call.
    """
    global _SCAN_UNIVERSE, _TIER_COUNTS
    if not _SCAN_UNIVERSE:
        _SCAN_UNIVERSE, _TIER_COUNTS = build_scan_universe()
    return _SCAN_UNIVERSE


def get_tier_counts() -> Dict[str, int]:
    """
    Get tier counts for the current universe.
    
    Returns cached counts, builds universe on first call.
    """
    global _SCAN_UNIVERSE, _TIER_COUNTS
    if not _TIER_COUNTS:
        _SCAN_UNIVERSE, _TIER_COUNTS = build_scan_universe()
    return _TIER_COUNTS


def refresh_universe() -> Tuple[List[str], Dict[str, int]]:
    """
    Force rebuild of the scan universe.
    
    Use after environment variable changes.
    
    Returns:
        Tuple of (symbol_list, tier_counts)
    """
    global _SCAN_UNIVERSE, _TIER_COUNTS
    _SCAN_UNIVERSE, _TIER_COUNTS = build_scan_universe()
    return _SCAN_UNIVERSE, _TIER_COUNTS
