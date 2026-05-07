import os
from datetime import datetime, timezone
from sqlmodel import Session, select, create_engine
from src.models import Transaction, Campaign
from src.schwab_account_api import get_account_hashes, get_transactions

DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

def rebuild_ledger_from_api():
    print("🚀 Starting Schwab API Ledger Flush...")
    
    start_str = "2026-01-01T00:00:00.000Z"
    end_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    account_hashes = get_account_hashes()
    if not account_hashes:
        print("❌ Could not reach Schwab Hash API.")
        return
        
    with Session(engine) as session:
        for acct in account_hashes:
            acct_hash = acct.get('hashValue')
            acct_num = acct.get('accountNumber', 'Unknown') 
            
            print(f"\n📥 Fetching activity for account ending in *{acct_num[-4:]}...")
            
            trades = get_transactions(acct_hash, start_str, end_date_iso=end_str)
            
            if not trades:
                print("   No activity found or error occurred.")
                continue
                
            trade_count = 0
                
            for trade in trades:
                # Schwab's main transaction type
                trade_type = trade.get('type', '')
                
                # We only want to process actual trades, not cash transfers/dividends
                if trade_type != 'TRADE':
                    continue
                
                exec_time_str = trade.get('time') or trade.get('transactionDate')
                if not exec_time_str:
                    continue
                exec_dt = datetime.fromisoformat(exec_time_str.replace('Z', '+00:00'))
                
                net_amount = trade.get('netAmount', 0.0)
                
                # Schwab puts the actual tickers moved in a list called transferItems
                transfer_items = trade.get('transferItems', [])
                
                for item in transfer_items:
                    instrument = item.get('instrument', {})
                    full_symbol = instrument.get('symbol', 'UNKNOWN')
                    
                    # Skip if it's an empty leg
                    if full_symbol == 'UNKNOWN':
                        continue
                        
                    instruction = item.get('instruction', item.get('positionEffect', 'UNKNOWN'))
                    amount = item.get('amount', 0.0)
                    price = item.get('price', 0.0)
                    asset_type = instrument.get('assetType', 'UNKNOWN')
                    
                    # --- FIX: EXACT CASH FLOW CALCULATION ---
                    if len(transfer_items) == 1:
                        # Single leg trade uses the exact Schwab bank sweep amount
                        leg_cash_flow = net_amount
                    else:
                        # Multi-leg roll: We must manually calculate the cash per leg
                        multiplier = 100 if asset_type == 'OPTION' else 1
                        raw_cash = amount * price * multiplier
                        
                        # Align cash direction: Buys are debits (-), Sells are credits (+)
                        if 'BUY' in instruction:
                            leg_cash_flow = -abs(raw_cash)
                        else:
                            leg_cash_flow = abs(raw_cash)

                    # Determine Root Ticker
                    if asset_type == 'OPTION':
                        root_ticker = instrument.get('underlyingSymbol', full_symbol[:6].strip())
                    elif asset_type == 'FUTURE':
                        # Strip the ":X" first, then remove the 3-character date code
                        clean_future = full_symbol.split(':')[0]
                        root_ticker = clean_future[:-3] 
                    else:
                        root_ticker = full_symbol
                        
                    # Skip junk sweep transactions
                    if root_ticker == 'CURRENCY_USD':
                        continue
                    
                    # --- AUTO-CAMPAIGN ASSIGNMENT ---
                    campaign = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
                    
                    if not campaign:
                        print(f"   [+] Creating new Campaign: {root_ticker}")
                        campaign = Campaign(
                            name=root_ticker,
                            start_date=exec_dt.date()
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
                        fees=0.0, # We will handle fee math later
                        amount=leg_cash_flow, # <-- CHANGED THIS LINE amount=net_amount if len(transfer_items) == 1 else (amount * price),
                        campaign_id=campaign.id
                    )
                    session.add(new_tx)
                    trade_count += 1
                    
        session.commit()
        print(f"\n✅ API Flush Complete! Ledger updated with new transactions.")

if __name__ == "__main__":
    rebuild_ledger_from_api()