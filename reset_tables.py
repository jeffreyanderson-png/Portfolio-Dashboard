from sqlmodel import SQLModel, create_engine
# Import all models so SQLModel knows about them
from src.models import Campaign, Transaction, Note, Strategy, SymbolSettings, AccountSnapshot, PositionSnapshot, Account, AssetClass, TickerMetadata, Position, RebalanceLog

DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

def reset_ledger_tables():
    print("🗑️ Dropping old ledger tables...")
    
    # Drop in reverse order of relationships to prevent foreign key errors
    Transaction.__table__.drop(engine, checkfirst=True)
    Note.__table__.drop(engine, checkfirst=True)
    Campaign.__table__.drop(engine, checkfirst=True)
    
    print("🏗️ Recreating tables with new schema...")
    # This will ONLY create tables that don't currently exist
    SQLModel.metadata.create_all(engine)
    
    print("✅ Schema reset complete! Your 401k and Snapshot data was not touched.")

if __name__ == "__main__":
    reset_ledger_tables()