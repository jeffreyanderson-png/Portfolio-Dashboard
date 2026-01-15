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

def seed_strategies(db_url="sqlite:///portfolio.db"):
    engine = create_engine(db_url)
    
    # --- CRITICAL FIX: CREATE TABLES IF THEY DON'T EXIST ---
    # This checks the database structure and builds missing tables (like 'strategy')
    SQLModel.metadata.create_all(engine)
    
    print("🌱 Seeding Database with Default Strategies...")
    
    with Session(engine) as session:
        for strat_name in DEFAULT_STRATEGIES:
            # Check if exists to prevent duplicates
            existing = session.exec(select(Strategy).where(Strategy.name == strat_name)).first()
            
            if not existing:
                print(f"   [+] Adding: {strat_name}")
                session.add(Strategy(name=strat_name))
            else:
                pass
        
        session.commit()
    print("✅ Seeding Complete!")

if __name__ == "__main__":
    seed_strategies()