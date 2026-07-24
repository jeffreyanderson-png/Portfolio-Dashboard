import os
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, select, create_engine
from src.models import Transaction, Campaign
from src.schwab_account_api import get_account_hashes, get_transactions

DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

def generate_date_chunks(start_year, start_month, start_day):
    """Slices the timeline into 180-day chunks to bypass Schwab's 1-year limit."""
    start_date = datetime(start_year, start_month, start_day, tzinfo=timezone.utc)
    end_date = datetime.now(timezone.utc)
    
    chunks = []
    current_start = start_date
    while current_start < end_date:
        current_end = current_start + timedelta(days=180)
        if current_end > end_date:
            current_end = end_date
            
        # Format to Schwab's required ISO-8601 string
        start_str = current_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = current_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        chunks.append((start_str, end_str))
        current_start = current_end + timedelta(seconds=1)
        
    return chunks

def execute_deep_backfill():
    print("Initiating Deep Historical Backfill (Jan 1, 2025 -> Present)...")
    
    account_hashes = get_account_hashes()
    if not account_hashes:
        print("Could not reach Schwab Hash API.")
        return
        
    date_chunks = generate_date_chunks(2025, 1, 1)
    
    with Session(engine) as session:
        for acct in account_hashes:
            acct_hash = acct.get('hashValue')
            acct_num = acct.get('accountNumber', 'Unknown') 
            
            print(f"\nProcessing Account ending in *{acct_num[-4:]}...")
            trade_count = 0
            
            for start_str, end_str in date_chunks:
                print(f"  -> Pulling chunk: {start_str[:10]} to {end_str[:10]}")
                trades = get_transactions(acct_hash, start_str, end_date_iso=end_str)
                
                if not trades:
                    continue
                    
                for trade in trades:
                    trade_type = trade.get('type', '')
                    if trade_type != 'TRADE':
                        continue
                    
                    exec_time_str = trade.get('time') or trade.get('transactionDate')
                    if not exec_time_str:
                        continue
                    exec_dt = datetime.fromisoformat(exec_time_str.replace('Z', '+00:00'))
                    
                    net_amount = trade.get('netAmount', 0.0)
                    transfer_items = trade.get('transferItems', [])
                    
                    for item in transfer_items:
                        instrument = item.get('instrument', {})
                        full_symbol = instrument.get('symbol', 'UNKNOWN')
                        
                        if full_symbol == 'UNKNOWN':
                            continue
                            
                        instruction = item.get('instruction', item.get('positionEffect', 'UNKNOWN'))
                        amount = item.get('amount', 0.0)
                        price = item.get('price', 0.0)
                        asset_type = instrument.get('assetType', 'UNKNOWN')
                        
                        if asset_type == 'OPTION':
                            root_ticker = instrument.get('underlyingSymbol', full_symbol[:6].strip())
                        elif asset_type == 'FUTURE':
                            clean_future = full_symbol.split(':')[0]
                            root_ticker = clean_future[:-3] 
                        else:
                            root_ticker = full_symbol
                            
                        if root_ticker == 'CURRENCY_USD':
                            continue
                        
                        # --- EXACT CASH FLOW CALCULATION ---
                        if len(transfer_items) == 1:
                            leg_cash_flow = net_amount
                        else:
                            multiplier = 100 if asset_type == 'OPTION' else 1
                            raw_cash = amount * price * multiplier
                            if 'BUY' in instruction:
                                leg_cash_flow = -abs(raw_cash)
                            else:
                                leg_cash_flow = abs(raw_cash)
                        
                        # --- CAMPAIGN ASSIGNMENT ---
                        campaign = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
                        
                        if not campaign:
                            campaign = Campaign(
                                name=root_ticker,
                                start_date=exec_dt.date(),
                                strategy="Unassigned"
                            )
                            session.add(campaign)
                            session.commit()
                            session.refresh(campaign)
                        
                        # --- BUILD TRANSACTION ---
                        new_tx = Transaction(
                            exec_datetime=exec_dt,
                            broker="Schwab",
                            account_id=1, 
                            root_ticker=root_ticker,
                            full_symbol=full_symbol,
                            asset_type=asset_type,
                            action=instruction,
                            quantity=amount,
                            price=price,
                            fees=0.0, 
                            amount=leg_cash_flow,
                            campaign_id=campaign.id
                        )
                        session.add(new_tx)
                        trade_count += 1
                        
            print(f"  Inserted {trade_count} trades for account *{acct_num[-4:]}.")
                        
        session.commit()
        print("\nDeep Backfill Complete! Ledger updated.")

if __name__ == "__main__":
    execute_deep_backfill()
    