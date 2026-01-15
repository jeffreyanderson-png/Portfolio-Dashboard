from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import date, time

class Transaction(SQLModel, table=True):
    # --- ADD THIS LINE to update the definition if this table is already defined, don't crash.
    __table_args__ = {"extend_existing": True}
    
    # --- Primary Key ---
    # We need a unique ID for our database, even if ToS doesn't provide one.
    id: Optional[int] = Field(default=None, primary_key=True)

    # --- Account Trade History Data ---
    exec_date: date          # Converted from String during import
    exec_time: time          # Converted from String during import
    
    # --- CHANGED: Make these Optional ---
    spread: Optional[str] = None      # Was: spread: str; e.g. data "VERTICAL", "SINGLE", "STOCK"
    side: str               # "BUY", "SELL"
    qty: int                # changed to int, may need to be a float for fractional shares in the future
    pos_effect: Optional[str] = None  # Was: pos_effect: str; e.g. # "TO OPEN", "TO CLOSE"
    symbol: str              # The Ticker (e.g., "AMD", "GOOG")
    
    # Optional fields (These will be Null/None for stock trades)
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None # "CALL", "PUT"
    
    price: float             # The price per share/contract

    # --- Cash Balance Data ---
    # We use default=0.0 so we don't break if data is missing
    cb_misc_fees: float = Field(default=0.0) 
    cb_commissions: float = Field(default=0.0)
    cb_description: Optional[str] = None
    cb_amount: float = Field(default=0.0) # The Net Total of the transaction minus fees

    # In src/models.py inside class Transaction:
    transaction_type: str = Field(default="TRADE") # e.g., "TRADE", "ASSIGNMENT"

    # --- Deduplication ---
    # We enforce uniqueness here. If we try to save a row with the same hash, 
    # the database will reject it (or we can handle it in code).
    row_hash: str = Field(unique=True, index=True)

    # --- Metadata ---
    # Good practice to track when you actually imported this row
    imported_at: date = Field(default_factory=date.today)
 
class AccountSnapshot(SQLModel, table=True):
    # --- ADD THIS LINE to update the definition if this table is already defined, don't crash.
    __table_args__ = {"extend_existing": True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_date: date
    net_liquidating_value: float = Field(default=0.0) # From Account Summary
    total_cash_balance: float = Field(default=0.0)    # From Cash Balance 'TOTAL' row
    
    # We can add a hash here too if we want to prevent duplicate daily entries
    row_hash: str = Field(unique=True, index=True)