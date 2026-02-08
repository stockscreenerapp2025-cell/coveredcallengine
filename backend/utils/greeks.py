import math

def norm_cdf(x):
    """Cumulative distribution function for the standard normal distribution"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x):
    """Probability density function for the standard normal distribution"""
    return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

def calculate_greeks(
    S: float,      # Underlying Price
    K: float,      # Strike Price
    T: float,      # Time to Expiration (in years)
    r: float,      # Risk-Free Rate (decimal, e.g. 0.05 for 5%)
    sigma: float,  # Volatility (decimal, e.g. 0.20 for 20%)
    option_type: str = "call"
) -> dict:
    """
    Calculate Option Greeks using Black-Scholes model.
    Returns dictionary with delta, gamma, theta, vega, rho.
    """
    try:
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return {
                "delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0
            }
        
        # d1 and d2 calculations
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        if option_type.lower() == "call":
            delta = norm_cdf(d1)
            rho = K * T * math.exp(-r * T) * norm_cdf(d2)
            theta = (-S * norm_pdf(d1) * sigma / (2 * math.sqrt(T)) 
                     - r * K * math.exp(-r * T) * norm_cdf(d2))
        else:
            delta = norm_cdf(d1) - 1
            rho = -K * T * math.exp(-r * T) * norm_cdf(-d2)
            theta = (-S * norm_pdf(d1) * sigma / (2 * math.sqrt(T)) 
                     + r * K * math.exp(-r * T) * norm_cdf(-d2))
            
        gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
        vega = S * norm_pdf(d1) * math.sqrt(T)
        
        # Scale Theta and Vega to "per day" and "per 1% vol" typically used in trading
        theta = theta / 365.0
        vega = vega / 100.0
        
        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
            "rho": round(rho, 4)
        }
        
    except Exception as e:
        return {
            "delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0
        }

def calculate_implied_volatility(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "call"
) -> float:
    """
    Calculate Implied Volatility using Newton-Raphson method.
    """
    MAX_ITER = 100
    PRECISION = 1.0e-5
    sigma = 0.5  # Initial guess
    
    for i in range(MAX_ITER):
        greeks = calculate_greeks(S, K, T, r, sigma, option_type)
        if option_type == "call":
            price_est = S * norm_cdf((math.log(S/K) + (r + 0.5*sigma**2)*T)/(sigma*math.sqrt(T))) - K * math.exp(-r*T) * norm_cdf((math.log(S/K) + (r + 0.5*sigma**2)*T)/(sigma*math.sqrt(T)) - sigma*math.sqrt(T))
        else:
            price_est = K * math.exp(-r*T) * norm_cdf(-((math.log(S/K) + (r + 0.5*sigma**2)*T)/(sigma*math.sqrt(T)) - sigma*math.sqrt(T))) - S * norm_cdf(-((math.log(S/K) + (r + 0.5*sigma**2)*T)/(sigma*math.sqrt(T))))
            
        vega = greeks["vega"] * 100 # Undo scaling for calculation
        
        diff = price - price_est
        
        if abs(diff) < PRECISION:
            return sigma
            
        if abs(vega) < 1.0e-5: # Avoid division by zero
            break
            
        sigma = sigma + diff / vega
        
    return sigma
