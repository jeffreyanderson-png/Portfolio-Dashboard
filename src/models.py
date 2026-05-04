from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
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
    symbol: str 
    start_date: date = Field(default_factory=date.today)
    status: str = Field(default="OPEN") 
    
    strategy_id: Optional[int] = Field(default=None, foreign_key="strategy.id")
    # SAFE: 'Strategy' is defined above
    strategy: Optional[Strategy] = Relationship()
    
    # REMOVED: notes, transactions

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
    exec_date: Optional[date] = None
    exec_time: Optional[time] = None
    symbol: str
    qty: float
    price: float
    side: str
    spread: Optional[str] = None
    pos_effect: Optional[str] = None
    
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    
    cb_misc_fees: float = Field(default=0.0)
    cb_commissions: float = Field(default=0.0)
    cb_amount: float = Field(default=0.0)
    cb_description: Optional[str] = None
    
    transaction_type: str = Field(default="TRADE")
    row_hash: str = Field(unique=True, index=True)
    imported_at: date = Field(default_factory=date.today)
    
    manual_review: bool = Field(default=False)
    review_reason: Optional[str] = None
    
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id")
    # SAFE: 'Campaign' is defined above
    campaign: Optional[Campaign] = Relationship()

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

class RebalanceLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rebalance_date: date
    notes: Optional[str] = None