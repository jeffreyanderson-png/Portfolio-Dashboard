from datetime import datetime, date

def parse_occ_expiration(occ_string):
    """
    Extracts the expiration date from a standard 21-character OCC option string.
    Format: Root (6) + YYMMDD (6) + Type (1) + Strike (8)
    """
    # Basic validation to ensure it's a standard OCC string
    if not occ_string or len(occ_string) != 21:
        return None
        
    try:
        # Extract the YYMMDD block
        date_str = occ_string[6:12]
        # Convert to a Python date object
        exp_date = datetime.strptime(date_str, "%y%m%d").date()
        return exp_date
    except ValueError:
        return None

def get_days_to_expiration(exp_date):
    """Returns the number of days between today and the expiration date."""
    if not exp_date:
        return 999 # Safe fallback
    today = date.today()
    delta = exp_date - today
    return delta.days

def parse_occ_type_and_strike(occ_string):
    """
    Extracts the Option Type (C/P) and Strike Price from an OCC string.
    Format: Root (6) + YYMMDD (6) + Type (1) + Strike (8)
    """
    if not occ_string or len(occ_string) != 21:
        return None, None
        
    try:
        opt_type = occ_string[12] # 'C' for Call, 'P' for Put
        # The strike is the last 8 digits, divided by 1000
        strike = int(occ_string[13:]) / 1000.0
        return opt_type, strike
    except (ValueError, IndexError):
        return None, None
    