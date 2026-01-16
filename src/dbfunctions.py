from sqlmodel import Session, select, create_engine
from sqlalchemy.exc import IntegrityError
import pandas as pd
from src.models import Transaction, AccountSnapshot, PositionSnapshot, Campaign, Note, Strategy

def create_engine_func(db_url):
    return create_engine(db_url)

def parse_multi_format_date(date_str):
    """
    Parses dates like '30 JAN 26' (ToS), '16-Jan-26', or '1/16/2026'.
    """
    if not date_str or str(date_str).lower() == 'nan':
        return None
    
    # FIX: Convert "30 JAN 26" -> "30 Jan 26" for python parsing
    date_str = str(date_str).strip().title()
    
    formats = [
        '%d %b %y',  # 30 Jan 26
        '%d-%b-%y',  # 16-Jan-26
        '%m/%d/%y',  # 1/16/26
        '%m/%d/%Y',  # 01/16/2026
        '%Y-%m-%d'   # 2026-01-16
    ]
    
    for fmt in formats:
        try:
            dt = pd.to_datetime(date_str, format=fmt)
            if pd.notna(dt):
                return dt.date()
        except:
            continue
            
    # Fallback
    try:
        dt = pd.to_datetime(date_str)
        if pd.notna(dt):
            return dt.date()
    except:
        return None

def save_import_data(engine, transactions_list: list, snapshots_list: list):
    stats = {"trades_added": 0, "trades_skipped": 0, "trades_healed": 0, "snapshots_processed": 0, "positions_added": 0}

    with Session(engine) as session:
        # --- 1. SNAPSHOTS & POSITIONS ---
        for snap_data in snapshots_list:
            snap_date = snap_data['snapshot_date']
            
            existing_snap = session.exec(select(AccountSnapshot).where(AccountSnapshot.snapshot_date == snap_date)).first()
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
                existing_positions = session.exec(select(PositionSnapshot).where(PositionSnapshot.snapshot_id == current_snap.id)).all()
                for p in existing_positions: session.delete(p)
                
                for pos in snap_data['positions']:
                    # Use the new robust parser
                    exp_date_obj = parse_multi_format_date(pos.get('exp_date_str'))

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
                        option_type=pos.get('option_type'),
                        option_code=pos.get('option_code'),
                        trade_price=pos.get('trade_price'),
                        pl_open=pos.get('pl_open'),
                        pl_pct=pos.get('pl_pct')
                    )
                    session.add(new_pos)
                    stats['positions_added'] += 1
                session.commit()

        # --- 2. TRANSACTIONS ---
        for row in transactions_list:
            exec_date_obj = parse_multi_format_date(row.get('Exec_Date'))
            exec_time_obj = None
            if row.get('Exec_Time'):
                try:
                    dt = pd.to_datetime(str(row['Exec_Time']))
                    if pd.notna(dt): exec_time_obj = dt.time()
                except: pass
            
            exp_date_obj = parse_multi_format_date(row.get('exp_date_str'))

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
                manual_review=row.get('manual_review', False),
                review_reason=row.get('review_reason')
            )

            existing_trade = session.exec(select(Transaction).where(Transaction.row_hash == transaction.row_hash)).first()
            if not existing_trade:
                try:
                    session.add(transaction)
                    session.commit()
                    stats['trades_added'] += 1
                except IntegrityError:
                    session.rollback()
            else:
                 stats['trades_skipped'] += 1
                
    return stats