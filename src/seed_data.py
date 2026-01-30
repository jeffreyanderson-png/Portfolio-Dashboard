from sqlmodel import Session, select, create_engine, SQLModel
from src.models import Strategy

# Define your core strategies here
DEFAULT_STRATEGIES = [
    "The Wheel",
    "Calendar Spread",
    "LEAPS",
    "Vertical Spread",
    "Buy & Hold",
    "Cash Secured Put",
    "Covered Call",
    "Iron Condor",
    "Lotto Ticket" 
]

#def seed_strategies(db_url="sqlite:///portfolio.db"):
def seed_strategies(db_url):
    if not db_url.startswith("sqlite"):
        db_url = f"sqlite:///{db_url}"
        
    engine = create_engine(db_url)
    
    # --- CREATE TABLES IF THEY DON'T EXIST ---
    # This checks the database structure and builds missing tables (like 'strategy')
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        changes_made = False # <--- THE KEY FIX
        
        for strat_name in DEFAULT_STRATEGIES:
            existing = session.exec(select(Strategy).where(Strategy.name == strat_name)).first()
            
            if not existing:
                print(f"   [+] Adding: {strat_name}")
                session.add(Strategy(name=strat_name))
                changes_made = True 
        
        if changes_made:
            session.commit() # Only write if data changed
            print("✅ Seeding Complete! (Changes Saved)")
        else:
            print("✅ Database up to date. (Skipping write)")

if __name__ == "__main__":
    seed_strategies("sqlite:///data/portfolio.db")
    