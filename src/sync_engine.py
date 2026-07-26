import datetime
from sqlmodel import Session, select
from sqlalchemy import create_engine
from src.models import Transaction, Campaign
from src.schwab_af_api import get_transactions, get_account_hashes

DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

def run_incremental_sync(days_back=30):
    """Pulls recent trades and safely inserts only new ones, preventing duplicates."""
    account_hashes = get_account_hashes()
    if not account_hashes:
        return False, "Could not reach Schwab API. Check tokens."

    # Define the rolling window
    end_date = datetime.datetime.now(datetime.timezone.utc)
    start_date = end_date - datetime.timedelta(days=days_back)
    
    start_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    new_trade_count = 0

    with Session(engine) as session:
        for acct in account_hashes:
            acct_hash = acct.get('hashValue')
            trades = get_transactions(acct_hash, start_str, end_date_iso=end_str)
            
            if not trades:
                continue
                
            for trade in trades:
                trade_type = trade.get('type', '')
                
                # --- THE FIX: Include Assignment/Expiration/Journal events ---
                # RECEIVE_AND_DELIVER handles the "RAD" and "EXP" events from ToS
                if trade_type not in ('TRADE', 'RECEIVE_AND_DELIVER', 'JOURNAL'):
                    continue
                
                exec_time_str = trade.get('time') or trade.get('transactionDate')
                if not exec_time_str:
                    continue
                exec_dt = datetime.datetime.fromisoformat(exec_time_str.replace('Z', '+00:00'))
                
                net_amount = trade.get('netAmount', 0.0)
                transfer_items = trade.get('transferItems', [])
                
                for item in transfer_items:
                    instrument = item.get('instrument', {})
                    full_symbol = instrument.get('symbol', 'UNKNOWN')
                    
                    if full_symbol == 'UNKNOWN':
                        continue
                        
                    # Better instruction capture for non-trades
                    instruction = item.get('instruction', item.get('positionEffect', ''))
                    if not instruction:
                        # If no instruction (common for RADs), grab the helpful description!
                        instruction = trade.get('description', 'UNKNOWN')
                        
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
                    
                    # --- MATH CALCULATION ---
                    if len(transfer_items) == 1:
                        leg_cash_flow = net_amount
                    else:
                        multiplier = 100 if asset_type == 'OPTION' else 1
                        raw_cash = amount * price * multiplier
                        if 'BUY' in instruction:
                            leg_cash_flow = -abs(raw_cash)
                        else:
                            leg_cash_flow = abs(raw_cash)

                    # --- DEDUPLICATION CHECK ---
                    # Look for an existing trade with the exact timestamp, symbol, and cash flow
                    existing_tx = session.exec(
                        select(Transaction)
                        .where(Transaction.exec_datetime == exec_dt)
                        .where(Transaction.full_symbol == full_symbol)
                        .where(Transaction.amount == leg_cash_flow)
                    ).first()

                    if existing_tx:
                        continue # We already have this trade! Skip it.

                    # --- CAMPAIGN ASSIGNMENT ---
                    campaign = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
                    if not campaign:
                        campaign = Campaign(name=root_ticker, start_date=exec_dt.date(), strategy="Unassigned")
                        session.add(campaign)
                        session.commit()
                        session.refresh(campaign)
                    
                    # --- INSERT NEW TRANSACTION ---
                    new_tx = Transaction(
                        exec_datetime=exec_dt,
                        broker="Schwab",
                        account_id=1, 
                        root_ticker=root_ticker,
                        full_symbol=full_symbol,
                        asset_type=asset_type,
                        action=instruction[:50], # Trim just in case the description is extremely long
                        quantity=amount,
                        price=price,
                        fees=0.0, 
                        amount=leg_cash_flow,
                        campaign_id=campaign.id
                    )
                    session.add(new_tx)
                    new_trade_count += 1
                    
        session.commit()
        return True, f"Sync complete. Added {new_trade_count} new transactions."