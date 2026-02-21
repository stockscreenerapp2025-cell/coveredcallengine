"""
Symbol Normalization Utilities
==============================
Ensures consistent symbol formatting across all data sources.

Yahoo Finance uses dots (BRK.B), while some sources use dashes (BRK-B).
This module normalizes all symbols to Yahoo format before any operations.
"""

# Symbol alias map: source format -> Yahoo format
SYMBOL_ALIAS_MAP = {
    # Berkshire Hathaway
    "BRK-B": "BRK.B",
    "BRK/B": "BRK.B",
    "BRKB": "BRK.B",
    
    # Brown-Forman
    "BF-B": "BF.B",
    "BF/B": "BF.B",
    "BFB": "BF.B",
    
    # Common variations
    "GOOGL": "GOOGL",  # Keep as-is
    "GOOG": "GOOG",    # Keep as-is
}

# Reverse map for display purposes
YAHOO_TO_DISPLAY_MAP = {v: k.replace(".", "-") for k, v in SYMBOL_ALIAS_MAP.items() if "." in v}


def normalize_symbol(symbol: str) -> str:
    """
    Normalize a symbol to Yahoo Finance format.
    
    Args:
        symbol: Raw symbol string
        
    Returns:
        Normalized symbol (e.g., BRK-B -> BRK.B)
    """
    if not symbol:
        return symbol
    
    # Uppercase and strip
    symbol = symbol.upper().strip()
    
    # Check alias map first
    if symbol in SYMBOL_ALIAS_MAP:
        return SYMBOL_ALIAS_MAP[symbol]
    
    # General normalization: replace dash with dot for class shares
    if "-" in symbol and len(symbol.split("-")) == 2:
        parts = symbol.split("-")
        if len(parts[1]) == 1:  # Single letter class (e.g., B, A)
            return f"{parts[0]}.{parts[1]}"
    
    return symbol


def normalize_symbols(symbols: list) -> list:
    """
    Normalize a list of symbols.
    
    Args:
        symbols: List of raw symbol strings
        
    Returns:
        List of normalized symbols (deduplicated)
    """
    if not symbols:
        return []
    
    normalized = [normalize_symbol(s) for s in symbols]
    # Remove duplicates while preserving order
    return list(dict.fromkeys(normalized))


def denormalize_symbol(symbol: str) -> str:
    """
    Convert Yahoo format back to display format (optional).
    
    Args:
        symbol: Yahoo-formatted symbol
        
    Returns:
        Display-formatted symbol (e.g., BRK.B -> BRK-B)
    """
    if not symbol:
        return symbol
    
    symbol = symbol.upper().strip()
    
    if symbol in YAHOO_TO_DISPLAY_MAP:
        return YAHOO_TO_DISPLAY_MAP[symbol]
    
    # General: replace dot with dash for class shares
    if "." in symbol and len(symbol.split(".")) == 2:
        parts = symbol.split(".")
        if len(parts[1]) == 1:
            return f"{parts[0]}-{parts[1]}"
    
    return symbol


def is_class_share(symbol: str) -> bool:
    """
    Check if symbol is a class share (e.g., BRK.B, BF.B).
    """
    if not symbol:
        return False
    symbol = normalize_symbol(symbol)
    if "." in symbol:
        parts = symbol.split(".")
        return len(parts) == 2 and len(parts[1]) == 1
    return False
