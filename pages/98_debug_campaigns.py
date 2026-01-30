from sqlmodel import Session, select
from src.models import Campaign, Strategy
from src.dbfunctions import create_engine_func
import os

db_url = f"sqlite:///{os.path.join('data', 'portfolio.db')}"
engine = create_engine_func(db_url)

with Session(engine) as session:
    print("\n--- STRATEGIES AVAILABLE ---")
    strats = session.exec(select(Strategy)).all()
    for s in strats:
        print(f"ID: {s.id} | Name: '{s.name}'")

    print("\n--- CAMPAIGNS ---")
    camps = session.exec(select(Campaign)).all()
    for c in camps:
        # Try to find the strategy name manually
        strat_name = "None"
        if c.strategy_id:
            st = session.get(Strategy, c.strategy_id)
            if st: strat_name = st.name
        
        print(f"Camp ID: {c.id} | Symbol: {c.symbol} | Strategy ID: {c.strategy_id} ({strat_name})")