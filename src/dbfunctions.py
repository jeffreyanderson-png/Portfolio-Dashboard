from sqlmodel import Session, select, create_engine
from sqlalchemy.exc import IntegrityError
import pandas as pd
from src.models import Transaction, AccountSnapshot, PositionSnapshot, Campaign, Note, Strategy

def create_engine_func(db_url):
    return create_engine(db_url)

def save_import_data(engine, transactions_list: list, snapshots_list: list):
    """
    Saves parsed transactions and daily snapshots/positions.
    Includes Self-Healing logic for existing trades.
    """
    stats = {
        "trades_added": 0,
        "trades_skipped": 0,
        "trades_healed": 0,
        "snapshots_processed": 0,
        "positions_added": 0
    }

    with Session(engine) as session:
        # --- 1. SNAPSHOTS & POSITIONS ---
        for snap_data in snapshots_list:
            snap_date = snap_data['snapshot_date']
            
            existing_snap = session.exec(
                select(AccountSnapshot).where(AccountSnapshot.snapshot_date == snap_date)
            ).first()
            current_snap = existing_snap
            
            if not existing_snap:
                new_snap = AccountSnapshot(
                    snapshot_date=snap_date,
                    total_cash_balance=snap_data['total_cash_balance'],
                    net_liquidating_value=snap_data['net_liquidating_value'],
                    is_net_liq_valid=snap_data['is_net_liq_valid'],
                    row_hash=f"{snap_date}_{snap_data['total_cash_balance']}"
                )
                session.add(new_snap)
                session.commit()
                session.refresh(new_snap)
                current_snap = new_snap
                stats['snapshots_processed'] += 1
            else:
                if snap_data['is_net_liq_valid'] and not current_snap.is_net_liq_valid:
                    current_snap.net_liquidating_value = snap_data['net_liquidating_value']
                    current_snap.is_net_liq_valid = True
                    session.add(current_snap)
                    session.commit()

            if snap_data['positions']:
                existing_positions = session.exec(
                    select(PositionSnapshot).where(PositionSnapshot.snapshot_id == current_snap.id)
                ).all()
                for p in existing_positions:
                    session.delete(p)
                
                for pos in snap_data['positions']:
                    exp_date_obj = None
                    if pos.get('exp_date_str'):
                        try:
                            dt = pd.to_datetime(pos['exp_date_str'], format='%d-%b-%y')
                            if pd.notna(dt):
                                exp_date_obj = dt.date()
                        except: pass

                    new_pos = PositionSnapshot(
                        snapshot_id=current_snap.id,
                        symbol=pos['symbol'],
                        description=pos['description'],
                        qty=pos['qty'],
                        mark_price=pos['mark_price'],
                        market_value=pos['market_value'],
                        asset_type=pos['asset_type'],
                        exp_date=exp_date_obj,
                        strike=pos.get('strike'),
                        option_type=pos.get('option_type')
                    )
                    session.add(new_pos)
                    stats['positions_added'] += 1
                session.commit()

        # --- 2. TRANSACTIONS ---
        for row in transactions_list:
            
            # --- DATE PARSING ---
            exec_date_obj = None
            if row.get('Exec_Date'):
                try:
                    dt = pd.to_datetime(row['Exec_Date'], format='%m/%d/%Y')
                    if pd.notna(dt): exec_date_obj = dt.date()
                except:
                    try:
                        dt = pd.to_datetime(row['Exec_Date'])
                        if pd.notna(dt): exec_date_obj = dt.date()
                    except: pass

            exec_time_obj = None
            if row.get('Exec_Time'):
                try:
                    dt = pd.to_datetime(str(row['Exec_Time']))
                    if pd.notna(dt): exec_time_obj = dt.time()
                except: pass
                
            exp_date_obj = None
            if row.get('exp_date_str'):
                try:
                    dt = pd.to_datetime(row['exp_date_str'], format='%d-%b-%y')
                    if pd.notna(dt): exp_date_obj = dt.date()
                except: pass

            # --- CREATE OBJECT (Must happen BEFORE the check) ---
            transaction = Transaction(
                exec_date=exec_date_obj,
                exec_time=exec_time_obj,
                symbol=row['Symbol'],
                qty=row['Qty'],
                price=row['Price'],
                side=row['Side'],
                spread=row.get('spread'),
                pos_effect=row.get('pos_effect'),
                exp_date=exp_date_obj,
                strike=row.get('strike'),
                option_type=row.get('option_type'),
                cb_misc_fees=row.get('cb_misc_fees', 0.0),
                cb_commissions=row.get('cb_commissions', 0.0),
                cb_amount=row.get('cb_amount', 0.0),
                cb_description=row.get('cb_description'),
                row_hash=row['row_hash'],
                transaction_type=row.get('transaction_type', 'TRADE'),

                # NEW VALIDATION FIELDS
                manual_review=row.get('manual_review', False),
                review_reason=row.get('review_reason')
            )

            # --- SELF-HEALING LOGIC ---
            # Check if this trade already exists
            existing_trade = session.exec(
                select(Transaction).where(Transaction.row_hash == transaction.row_hash)
            ).first()

            if existing_trade:
                # If we found a description now that we missed before, UPDATE it
                if not existing_trade.cb_description and transaction.cb_description:
                    existing_trade.cb_description = transaction.cb_description
                    existing_trade.cb_misc_fees = transaction.cb_misc_fees
                    existing_trade.cb_commissions = transaction.cb_commissions
                    existing_trade.cb_amount = transaction.cb_amount # Update math
                    
                    session.add(existing_trade)
                    session.commit()
                    stats['trades_healed'] += 1
                else:
                    stats['trades_skipped'] += 1
            else:
                # Insert New
                try:
                    session.add(transaction)
                    session.commit()
                    stats['trades_added'] += 1
                except IntegrityError:
                    session.rollback()
                    stats['trades_skipped'] += 1
                
    return stats
