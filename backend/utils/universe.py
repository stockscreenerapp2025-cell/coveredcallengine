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
# ETF WHITELIST (Tier 3)
# ============================================================
# Liquid options ETFs with good bid/ask spreads
# These skip fundamental data fetch entirely

ETF_WHITELIST: Set[str] = {
    # Major Index ETFs
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    "DIA",   # Dow Jones
    
    # Sector ETFs
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
    
    # Bond ETFs
    "TLT",   # 20+ Year Treasury
    "HYG",   # High Yield Corporate
    "LQD",   # Investment Grade Corporate
    
    # International
    "EEM",   # Emerging Markets
    "EFA",   # Developed Markets ex-US
    "FXI",   # China Large Cap
    
    # Volatility & Leveraged (high premium)
    "VXX",   # VIX Short-Term Futures
    "UVXY",  # 1.5x VIX Short-Term
    "SQQQ",  # 3x Inverse Nasdaq
    "TQQQ",  # 3x Nasdaq
    "SPXU",  # 3x Inverse S&P
    "SPXL",  # 3x S&P
    
    # Thematic / ARK
    "ARKK",  # ARK Innovation
    "ARKG",  # ARK Genomic
    "ARKW",  # ARK Next Gen Internet
    "ARKF",  # ARK Fintech
    
    # Small/Mid Cap
    "IJR",   # S&P SmallCap 600
    "IJH",   # S&P MidCap 400
    "MDY",   # S&P MidCap 400 (SPDR)
}

# ============================================================
# S&P 500 CONSTITUENTS (Tier 1)
# ============================================================
# Top 200+ liquid S&P 500 stocks by options volume
# Full S&P 500 list - curated for options liquidity

SP500_SYMBOLS: List[str] = [
    # Mega Cap Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    
    # Large Cap Tech
    "AMD", "INTC", "MU", "QCOM", "AVGO", "TXN", "ADI", "MCHP", "AMAT", "LRCX",
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "INTU", "CDNS", "SNPS", "KLAC", "NXPI",
    "IBM", "HPQ", "HPE", "CSCO", "PANW", "FTNT", "ZS", "CRWD", "NET", "DDOG",
    
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
    "AXP", "V", "MA", "PYPL", "BLK", "SCHW", "CME", "ICE", "SPGI", "MCO",
    "MET", "PRU", "AIG", "ALL", "TRV", "CB", "AFL", "PGR", "MMC", "AON",
    
    # Healthcare
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "GILD", "AMGN", "REGN",
    "VRTX", "ISRG", "DXCM", "BSX", "MDT", "SYK", "ZBH", "ABT", "TMO", "DHR",
    "CVS", "CI", "HUM", "ELV", "CNC", "MCK", "CAH", "ABC",
    
    # Consumer Discretionary
    "HD", "LOW", "NKE", "SBUX", "MCD", "YUM", "DPZ", "CMG", "ORLY", "AZO",
    "TJX", "ROST", "BBY", "ULTA", "LULU", "DRI", "MAR", "HLT", "ABNB",
    "F", "GM", "TSLA", "RIVN",
    
    # Consumer Staples
    "WMT", "COST", "TGT", "DG", "DLTR", "KO", "PEP", "MDLZ", "KHC", "GIS",
    "K", "HSY", "PG", "CL", "KMB", "CHD", "CLX", "EL", "PM", "MO", "STZ",
    
    # Communication Services
    "DIS", "NFLX", "CMCSA", "CHTR", "TMUS", "VZ", "T", "PARA", "WBD", "FOX",
    "FOXA", "EA", "TTWO", "ATVI", "MTCH", "SNAP", "PINS",
    
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "HAL", "MPC", "VLO",
    "PSX", "PXD", "FANG", "HES", "MRO", "APA", "BKR",
    
    # Industrials
    "CAT", "DE", "BA", "HON", "GE", "RTX", "LMT", "NOC", "GD", "TDG",
    "UPS", "FDX", "CSX", "UNP", "NSC", "UAL", "DAL", "AAL", "LUV", "ALK",
    "WM", "RSG", "ROK", "EMR", "ETN", "IR", "PH", "ITW", "SWK", "MMM",
    
    # Materials
    "LIN", "APD", "SHW", "ECL", "DD", "DOW", "LYB", "PPG", "NEM", "FCX",
    "NUE", "STLD", "CF", "MOS", "ALB", "FMC",
    
    # Real Estate
    "AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "AVB", "EQR",
    "DLR", "ARE", "VTR", "BXP", "SLG",
    
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "ED", "WEC",
    "ES", "AWK", "AEE", "CMS", "DTE", "ETR", "FE", "PPL", "PEG", "EIX",
    
    # High Growth / Volatility
    "PLTR", "SOFI", "COIN", "HOOD", "RBLX", "U", "PATH", "DOCN", "BILL",
]

# ============================================================
# NASDAQ 100 CONSTITUENTS (Tier 2 - net of S&P overlap)
# ============================================================
# Nasdaq 100 symbols NOT in S&P 500 (to avoid duplicates)

NASDAQ100_NET: List[str] = [
    # Tech not in S&P 500
    "MRVL", "ON", "TEAM", "WDAY", "ZM", "OKTA", "DDOG", "SPLK", "VEEV",
    "ANSS", "CPRT", "FAST", "IDXX", "ODFL", "PAYX", "VRSK", "CSGP",
    "SIRI", "WBA", "DLTR", "EBAY", "EXPE", "JD", "LCID", "MELI", "PDD",
    "PTON", "SGEN", "VRSN", "XEL", "ZS",
    
    # Biotech
    "BIIB", "ILMN", "MRNA", "BNTX", "ALGN", "DXCM",
    
    # Chinese ADRs in Nasdaq
    "BIDU", "NTES", "BABA",
    
    # Other Nasdaq 100
    "ADP", "CEG", "CTAS", "CSX", "FANG", "GILD", "HON", "KDP", "KHC",
    "MAR", "MCHP", "MDLZ", "MNST", "NXPI", "PCAR", "REGN", "ROST",
    "SBUX", "TMUS", "VRSK", "WBD",
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
