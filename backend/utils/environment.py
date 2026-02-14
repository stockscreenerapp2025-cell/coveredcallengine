"""
Environment Configuration Utility

Provides environment detection and mock data policy enforcement.

ENVIRONMENT values:
- production: No mock data allowed, fail explicitly on data unavailability
- development: Mock data allowed as fallback
- test: Mock data allowed for automated testing
"""
import os
import logging

# Valid environment values
VALID_ENVIRONMENTS = {"production", "development", "test"}

# Get current environment (default to development for safety)
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()

# Validate environment value
if ENVIRONMENT not in VALID_ENVIRONMENTS:
    logging.warning(f"Invalid ENVIRONMENT '{ENVIRONMENT}', defaulting to 'development'")
    ENVIRONMENT = "development"


def is_production() -> bool:
    """Check if running in production environment."""
    return ENVIRONMENT == "production"


def is_development() -> bool:
    """Check if running in development environment."""
    return ENVIRONMENT == "development"


def is_test() -> bool:
    """Check if running in test environment."""
    return ENVIRONMENT == "test"


def allow_mock_data() -> bool:
    """
    Check if mock data fallback is allowed.
    
    Returns True only in development or test environments.
    Production must never return fabricated data.
    """
    return ENVIRONMENT in {"development", "test"}


class DataUnavailableError(Exception):
    """
    Exception raised when real data is unavailable and mock fallback is blocked.
    
    Used in production to signal honest data unavailability instead of
    fabricating prices or contracts.
    """
    def __init__(self, reason: str, symbol: str = None, details: str = None):
        self.reason = reason
        self.symbol = symbol
        self.details = details
        message = f"Data unavailable: {reason}"
        if symbol:
            message = f"[{symbol}] {message}"
        if details:
            message = f"{message} - {details}"
        super().__init__(message)
    
    def to_dict(self):
        """Convert to API response format."""
        return {
            "data_status": "UNAVAILABLE",
            "reason": self.reason,
            "symbol": self.symbol,
            "details": self.details,
            "is_mock": False
        }


def check_mock_fallback(
    symbol: str = None,
    reason: str = "DATA_PROVIDER_ERROR",
    details: str = None,
    log_blocked: bool = True
) -> bool:
    """
    Check if mock fallback should be used or blocked.
    
    In production: Raises DataUnavailableError
    In dev/test: Returns True (allow mock)
    
    Args:
        symbol: The symbol for which data was unavailable
        reason: Reason code for unavailability
        details: Additional details about the failure
        log_blocked: Whether to log when mock is blocked in production
    
    Returns:
        True if mock data is allowed
        
    Raises:
        DataUnavailableError in production
    """
    if allow_mock_data():
        logging.debug(f"Mock fallback allowed for {symbol or 'unknown'}: {reason}")
        return True
    
    # Production - block mock fallback
    if log_blocked:
        logging.warning(
            f"MOCK_FALLBACK_BLOCKED_PRODUCTION | symbol={symbol} | reason={reason} | details={details}"
        )
    
    raise DataUnavailableError(reason=reason, symbol=symbol, details=details)


# Log environment on module load
logging.info(f"Environment: {ENVIRONMENT} | Mock data allowed: {allow_mock_data()}")
