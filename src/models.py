from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date, time, datetime

# --- 1. CONFIGURATION TABLES ---
class Strategy(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True) 
    description: Optional[str] = None
    
    # REMOVED: campaigns, symbol_defaults (Breaks circular dependency)

class SymbolSettings(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    symbol: str = Field(primary_key=True)
    
    default_strategy_id: Optional[int] = Field(default=None, foreign_key="strategy.id")
    # SAFE: 'Strategy' is defined above, so we use the Class directly (No quotes)
    default_strategy: Optional[Strategy] = Relationship()
    notes: Optional[str] = None

# --- 2. CAMPAIGN MANAGEMENT ---
class Campaign(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str 
    status: str = Field(default="Active") # Active, Closed, Paused
    strategy: str = Field(default="Unassigned") # <-- ADD THIS LINE
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    
    transactions: List["src.models.Transaction"] = Relationship(back_populates="campaign") # type: ignore

class Note(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)
    content: str
    
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id")
    # SAFE: 'Campaign' is defined above
    campaign: Optional[Campaign] = Relationship()

# --- 3. CORE DATA ---
class Transaction(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    
    exec_datetime: datetime  
    settle_date: Optional[date] = None
    
    broker: str = Field(default="Schwab") 
    account_id: int # (Will link to your main account table)
    
    root_ticker: str  
    full_symbol: str  
    asset_type: str   # EQUITY, OPTION, FUTURE
    
    action: str       # BUY, SELL
    
    quantity: float   
    price: float
    fees: float       
    amount: float     
    
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id")
    campaign: Optional[Campaign] = Relationship(back_populates="transactions")

class AccountSnapshot(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_date: date = Field(index=True)
    total_cash_balance: float = Field(default=0.0) 
    net_liquidating_value: Optional[float] = None 
    is_net_liq_valid: bool = Field(default=False) 
    row_hash: str = Field(unique=True, index=True)
    
    # REMOVED: positions

class PositionSnapshot(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: Optional[int] = Field(default=None, foreign_key="accountsnapshot.id")
    # SAFE: 'AccountSnapshot' is defined above
    snapshot: Optional[AccountSnapshot] = Relationship()
    
    symbol: str
    description: Optional[str] = None
    qty: float
    mark_price: float
    market_value: float
    asset_type: str
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    
    option_code: Optional[str] = None
    trade_price: Optional[float] = None
    pl_open: Optional[float] = None
    pl_pct: Optional[float] = None

# --- 401K ALLOCATION MODELS ---
# (Ensure you have 'from datetime import date' at the top of your file if not already there)

class Account(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    account_name: str  # e.g., "Trad 401k", "Roth 401k", "Roth IRA"
    tax_status: str    # e.g., "Tax-Deferred", "Tax-Free", "Taxable"

class AssetClass(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    class_name: str             # e.g., "US SCV", "EM", "STB"
    base_target_percent: float  # e.g., 10.0 for 10%
    region: str                 # e.g., "US", "International", "Emerging"
    cap_size: str               # e.g., "Large", "Mid", "Small", "N/A"
    style: str                  # e.g., "Value", "Blend", "Growth", "N/A"
    asset_type: str             # e.g., "Equity", "Bond", "Commodity"

class TickerMetadata(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    ticker: str = Field(primary_key=True) # e.g., "AVUV"
    asset_class_id: int = Field(foreign_key="assetclass.id")
    action_tag: str = Field(default="Buy") # "Buy", "Hold", or "Sell"

class Position(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id")
    ticker: str = Field(foreign_key="tickermetadata.ticker")
    shares: float

class RebalanceLog(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    rebalance_date: date
    notes: Optional[str] = None
