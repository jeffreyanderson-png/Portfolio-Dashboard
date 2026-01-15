from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import date, time, datetime

# --- 1. CONFIGURATION TABLES ---
class Strategy(SQLModel, table=True):
    """Defines the high-level strategy types (e.g., 'The Wheel', 'Calendar Spread')"""
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True) 
    description: Optional[str] = None
    
    # Back-populates
    campaigns: List["Campaign"] = Relationship(back_populates="strategy")
    symbol_defaults: List["SymbolSettings"] = Relationship(back_populates="default_strategy")

class SymbolSettings(SQLModel, table=True):
    """Stores user defaults for specific symbols"""
    __table_args__ = {"extend_existing": True}
    symbol: str = Field(primary_key=True) # "GOOG", "ASTS"
    
    # Default Strategy for this symbol
    default_strategy_id: Optional[int] = Field(default=None, foreign_key="strategy.id")
    default_strategy: Optional[Strategy] = Relationship(back_populates="symbol_defaults")
    
    notes: Optional[str] = None # General notes on the ticker

# --- 2. CAMPAIGN MANAGEMENT ---
class Campaign(SQLModel, table=True):
    """A specific instance of a strategy (e.g., 'GOOG Wheel Jan 2026')"""
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str 
    symbol: str # The primary ticker this campaign focuses on
    start_date: date = Field(default_factory=date.today)
    status: str = Field(default="OPEN") # OPEN, CLOSED, ARCHIVED
    
    # Link to the Strategy Definition
    strategy_id: Optional[int] = Field(default=None, foreign_key="strategy.id")
    strategy: Optional[Strategy] = Relationship(back_populates="campaigns")
    
    # Data Links
    notes: List["Note"] = Relationship(back_populates="campaign")
    transactions: List["Transaction"] = Relationship(back_populates="campaign")

class Note(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)
    content: str
    
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id")
    campaign: Optional[Campaign] = Relationship(back_populates="notes")

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
    
    # NEW: Link to Campaign (The "Bucket")
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
    positions: List["PositionSnapshot"] = Relationship(back_populates="snapshot")

class PositionSnapshot(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: Optional[int] = Field(default=None, foreign_key="accountsnapshot.id")
    snapshot: Optional[AccountSnapshot] = Relationship(back_populates="positions")
    
    symbol: str
    description: Optional[str] = None
    qty: float
    mark_price: float
    market_value: float
    asset_type: str
    exp_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    
    # Cached Strategy Name (Optional, for quick filtering on the dashboard without joining)
    # Alternatively, we could link Position -> Campaign, but positions are ephemeral snapshots.
    # For now, let's keep it simple.
