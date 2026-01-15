from sqlmodel import Session, select, create_engine
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import pandas as pd
# FIX: Removed the '.' before models
from models import Transaction, AccountSnapshot

def save_import_data(engine, df_transactions: pd.DataFrame, snapshot_dict: dict): # Main function to save parsed data to the DB.
    # Returns a status dictionary with counts of added/skipped records.
    
    stats = {
        "trades_added": 0,
        "trades_skipped": 0,
        "snapshot_added": False
    }

    with Session(engine) as session:
        # --- 1. SAVE SNAPSHOT ---
        # Check if we already have a snapshot for this date
        # We also use pd.to_datetime here just to be safe
        snap_date = pd.to_datetime(snapshot_dict['snapshot_date']).date()
        
        existing_snap = session.exec(
            select(AccountSnapshot).where(AccountSnapshot.snapshot_date == snap_date)
        ).first()

        if not existing_snap:
            # Create new snapshot
            new_snap = AccountSnapshot(
                snapshot_date=snap_date,
                net_liquidating_value=snapshot_dict['net_liquidating_value'],
                total_cash_balance=snapshot_dict['total_cash_balance'],
                # Generate a simple hash for the snapshot to enforce uniqueness if needed
                row_hash=f"{snap_date}_{snapshot_dict['net_liquidating_value']}"
            )
            session.add(new_snap)
            stats['snapshot_added'] = True
        
        # --- 2. SAVE TRANSACTIONS ---
        # Iterate through the DataFrame rows
        for _, row in df_transactions.iterrows():
            
            # --- FIX 1: EXECUTION DATE (MM/DD/YYYY) ---
            # We explicitly look for 4-digit year (%Y)
            try:
                exec_date_obj = pd.to_datetime(row['Exec_Date'], format='%m/%d/%Y').date()
            except:
                # Fallback if format is weird, but try to keep it simple
                exec_date_obj = pd.to_datetime(row['Exec_Date']).date()

            # --- FIX 2: TIME ---
            # We treat it as a string first to strip the .000000 visual noise if needed
            try:
                exec_time_obj = pd.to_datetime(str(row['Exec_Time'])).time()
            except:
                exec_time_obj = None

            # --- FIX 3: EXPIRATION DATE (DD-Mon-YY) ---
            # ToS format: "16-Jan-26"
            exp_date_obj = None
            raw_exp = str(row.get('exp_date_str', ''))
            if raw_exp.strip() != '' and raw_exp.lower() != 'nan':
                try:
                    # %b = Abbreviated Month (Jan), %y = 2-digit Year (26)
                    exp_date_obj = pd.to_datetime(raw_exp, format='%d-%b-%y').date()
                except:
                    # Fallback for weird ones
                    exp_date_obj = None

            # Map DataFrame columns to Model fields
            # We use .get() to handle cases where a column might be missing safely
            transaction = Transaction(
                exec_date=exec_date_obj,  # Uses the %Y parser
                exec_time=exec_time_obj,
                symbol=row['Symbol'],
                qty=row['Qty'],
                price=row['Price'],
                side=row['Side'],
                spread=row.get('spread'),     
                pos_effect=row.get('pos_effect'),
                
                # Option Fields
                exp_date=exp_date_obj,    # Uses the %y parser
                strike=row.get('strike'),
                option_type=row.get('option_type'), # Call/Put
                
                # Cash Fields
                cb_misc_fees=row.get('cb_misc_fees', 0.0),
                cb_commissions=row.get('cb_commissions', 0.0),
                cb_amount=row.get('cb_amount', 0.0),
                cb_description=row.get('cb_description'), 
                
                row_hash=row['row_hash'],
                # Handling the "Type" we added in the parser
                transaction_type=row.get('transaction_type', 'TRADE') 
            )
            
            try:
                session.add(transaction)
                session.commit() # Try to commit this single row
                stats['trades_added'] += 1
            except IntegrityError as e:
                # --- NEW DEBUGGING LINES ---
                # This will print the specific reason to your VS Code Terminal
                print(f"⚠️ REJECTED ROW: {row['Symbol']} on {row['Exec_Date']}")
                print(f"   Reason: {e}") 
                # ---------------------------

                # This error means the row_hash already exists.
                session.rollback() # Cancel the failed insert
                stats['trades_skipped'] += 1
                
        # Final commit for the snapshot (if any)
        session.commit()

    return stats
