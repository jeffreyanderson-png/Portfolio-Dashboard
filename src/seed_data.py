from sqlmodel import Session, select, create_engine, SQLModel
from src.models import Account, AssetClass, TickerMetadata, RebalanceLog, Strategy
from datetime import date

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

def seed_401k_data(engine):
    with Session(engine) as session:
        # 1. Check if accounts already exist to prevent duplicate seeding
        existing = session.exec(select(Account)).first()
        if existing:
            return

        # 2. Seed Accounts
        accounts = [
            Account(account_name="Trad 401k", tax_status="Tax-Deferred"),
            Account(account_name="Roth 401k", tax_status="Tax-Free"),
            Account(account_name="Roth IRA", tax_status="Tax-Free")
        ]
        session.add_all(accounts)

        # 3. Seed Asset Classes (Using base percentages from your spreadsheet)
        asset_classes = [
            # Equities (10% target each within the Equity block)
            AssetClass(class_name="I LCB", base_target_percent=10.0, region="International", cap_size="Large", style="Blend", asset_type="Equity"),
            AssetClass(class_name="I SCB", base_target_percent=10.0, region="International", cap_size="Small", style="Blend", asset_type="Equity"),
            AssetClass(class_name="I SCV", base_target_percent=10.0, region="International", cap_size="Small", style="Value", asset_type="Equity"),
            AssetClass(class_name="EM", base_target_percent=10.0, region="Emerging", cap_size="N/A", style="Blend", asset_type="Equity"),
            AssetClass(class_name="US LCV", base_target_percent=10.0, region="US", cap_size="Large", style="Value", asset_type="Equity"),
            AssetClass(class_name="US SCB", base_target_percent=10.0, region="US", cap_size="Small", style="Blend", asset_type="Equity"),
            AssetClass(class_name="US LCB", base_target_percent=10.0, region="US", cap_size="Large", style="Blend", asset_type="Equity"),
            AssetClass(class_name="US SCV", base_target_percent=10.0, region="US", cap_size="Small", style="Value", asset_type="Equity"),
            AssetClass(class_name="I LCV", base_target_percent=10.0, region="International", cap_size="Large", style="Value", asset_type="Equity"),
            AssetClass(class_name="US REIT", base_target_percent=10.0, region="US", cap_size="N/A", style="N/A", asset_type="Equity"),
            
            # Bonds (Percentages within the Fixed Income block)
            AssetClass(class_name="ITB", base_target_percent=50.0, region="US", cap_size="N/A", style="N/A", asset_type="Bond"),
            AssetClass(class_name="STB", base_target_percent=30.0, region="US", cap_size="N/A", style="N/A", asset_type="Bond"),
            AssetClass(class_name="TIPS", base_target_percent=10.0, region="US", cap_size="N/A", style="N/A", asset_type="Bond"),
            
            # Commodities
            AssetClass(class_name="Commodities", base_target_percent=80.0, region="Global", cap_size="N/A", style="N/A", asset_type="Commodity"),
            AssetClass(class_name="Gold", base_target_percent=20.0, region="Global", cap_size="N/A", style="N/A", asset_type="Commodity")
        ]
        session.add_all(asset_classes)
        session.commit() # Commit to generate IDs for foreign keys

        # 4. Map Tickers to Asset Classes
        # Fetch the newly created classes to map their IDs
        db_classes = session.exec(select(AssetClass)).all()
        class_map = {c.class_name: c.id for c in db_classes}

        tickers = [
            TickerMetadata(ticker="AVDE", asset_class_id=class_map["I LCB"], action_tag="Buy"),
            TickerMetadata(ticker="AVDS", asset_class_id=class_map["I SCB"], action_tag="Buy"),
            TickerMetadata(ticker="AVDV", asset_class_id=class_map["I SCV"], action_tag="Buy"),
            TickerMetadata(ticker="AVEM", asset_class_id=class_map["EM"], action_tag="Buy"),
            TickerMetadata(ticker="AVLV", asset_class_id=class_map["US LCV"], action_tag="Buy"),
            TickerMetadata(ticker="AVSC", asset_class_id=class_map["US SCB"], action_tag="Buy"),
            TickerMetadata(ticker="AVUS", asset_class_id=class_map["US LCB"], action_tag="Buy"),
            TickerMetadata(ticker="AVUV", asset_class_id=class_map["US SCV"], action_tag="Buy"),
            TickerMetadata(ticker="DFIV", asset_class_id=class_map["I LCV"], action_tag="Buy"),
            TickerMetadata(ticker="VNQ", asset_class_id=class_map["US REIT"], action_tag="Buy"),
            TickerMetadata(ticker="SPTI", asset_class_id=class_map["ITB"], action_tag="Buy"),
            TickerMetadata(ticker="VGSH", asset_class_id=class_map["STB"], action_tag="Buy"),
            TickerMetadata(ticker="VTIP", asset_class_id=class_map["TIPS"], action_tag="Buy"),
            TickerMetadata(ticker="HGER", asset_class_id=class_map["Commodities"], action_tag="Buy"),
            TickerMetadata(ticker="USG", asset_class_id=class_map["Gold"], action_tag="Buy")
        ]
        session.add_all(tickers)
        
        # 5. Initialize a baseline rebalance log
        initial_log = RebalanceLog(rebalance_date=date(2026, 1, 1), notes="Initial baseline from Excel")
        session.add(initial_log)

        session.commit()            