from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import date, time

class Transaction(SQLModel, table=True):
    # --- ADD THIS LINE to update the definition if this table is already defined, don't crash.
    __table_args__ = {"extend_existing": True}
    
    # --- Primary Key ---
    # We need a unique ID for our database, even if ToS doesn't provide one.
    id: Optional[int] = Field(default=None, primary_key=True)

    # --- Account Trade History Data ---
    exec_date: date                     # Converted from String during import
    exec_time: Optional[time] = None    # Converted from String during import
    
    # --- CHANGED: Make these Optional ---
    symbol: str                         # The Ticker (e.g., "AMD", "GOOG")
    qty: float
    price: float                        # Price per Share/Contract 
    side: str                           # "BUY", "SELL"
    spread: Optional[str] = None        # Was: spread: str; e.g. data "VERTICAL", "SINGLE", "STOCK"
    pos_effect: Optional[str] = None    # Was: pos_effect: str; e.g. # "TO OPEN", "TO CLOSE"
    
    # Options Data (These will be Null/None for stock trades)
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None   # "CALL", "PUT"
    
    # --- Cash Balance Data ---
    # We use default=0.0 so we don't break if data is missing
    # Cash Data
    cb_misc_fees: float = Field(default=0.0)
    cb_commissions: float = Field(default=0.0)
    cb_amount: float = Field(default=0.0) # The Net Total of the transaction minus fees
    cb_description: Optional[str] = None

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

    # This date comes from the "Cash Balance" row (e.g., 1/13/26)
    snapshot_date: date = Field(index=True)
    
    # Cash is known every day (from 'BAL' rows)
    total_cash_balance: float = Field(default=0.0)
    
    # Net Liq is ONLY known on the statement generation date
    net_liquidating_value: Optional[float] = None 
    is_net_liq_valid: bool = Field(default=False) # True only if this matches File Date

    # Deduplication Hash
    row_hash: str = Field(unique=True, index=True)
    
    # Relationship to Positions
    positions: List["PositionSnapshot"] = Relationship(back_populates="snapshot")
    
class PositionSnapshot(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Link to the AccountSnapshot (Parent)
    snapshot_id: Optional[int] = Field(default=None, foreign_key="accountsnapshot.id")
    snapshot: Optional[AccountSnapshot] = Relationship(back_populates="positions")

    symbol: str
    description: Optional[str] = None
    qty: float
    mark_price: float
    market_value: float
    asset_type: str # "STOCK", "OPTION", "FUTURE", "ETF", etc.
    
    # Option Specifics
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None # Call/Put