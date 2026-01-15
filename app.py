import streamlit as st
import pandas as pd
from datetime import datetime
import os
import hashlib
import time
import re
from sqlmodel import SQLModel, create_engine, Session

# --- SETUP: Make sure we can find the 'src' folder ---
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# --- LOCAL IMPORTS ---
# We import these AFTER adding 'src' to the path
import dbfunctions
import import_tos_csv
from models import Transaction, AccountSnapshot # <--- IMPORT THIS!

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Pilot Portfolio Manager v2.0",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTS ---
DB_FOLDER = "data"
DB_FILE = "portfolio.db"
DB_PATH = os.path.join(DB_FOLDER, DB_FILE)
# SQLModel needs a URL format for the engine (sqlite:///path/to/db)
DB_URL = f"sqlite:///{DB_PATH}"

# --- INITIALIZATION ---
def init_db():
    """Checks if DB exists, creates folder if needed."""
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER)
    
    # Create the engine here (we will move this to dbfunctions later, 
    # but good to see it working here first)
    engine = create_engine(DB_URL)
    
    # This creates the tables if they don't exist yet
    SQLModel.metadata.create_all(engine)
    
    return engine

# --- MAIN APP LOGIC ---
def main():
    st.title("✈️ Pilot Portfolio Manager v2.0")
    # Ensure DB tables exist before we do anything else
    init_db()
    
    # Sidebar for Navigation
    page = st.sidebar.selectbox("Go to", ["Dashboard", "Import Data", "Data Inspector", "Settings"])

    if page == "Dashboard":
        st.write("### Welcome Back")
        st.info("Database not yet connected. Go to 'Import Data' to start.")
        
    elif page == "Import Data":
        st.header("Import ThinkOrSwim CSV")
        
        # 1. Create the uploader
        uploaded_file = st.file_uploader("Upload Account Statement", type=['csv'])
        
        # 2. Check if a file was actually uploaded
        if uploaded_file is not None:
            st.write(f"Filename: `{uploaded_file.name}`")
            
            # 3. Create the button INSIDE the file check block
            if st.button("Process File"):
                
                with st.spinner("Parsing file..."):
                    try:
                        # Reset file pointer to the start (critical for re-reading)
                        uploaded_file.seek(0)
                        
                        # A. Parse the file
                        df_transactions, snapshot_data = import_tos_csv.parse_file(uploaded_file)
                        
                        # Fix missing snapshot date if parser didn't find one
                        if 'snapshot_date' not in snapshot_data or not snapshot_data['snapshot_date']:
                            if not df_transactions.empty:
                                max_date_str = df_transactions['Exec_Date'].max()
                                snapshot_data['snapshot_date'] = pd.to_datetime(max_date_str).date()
                            else:
                                snapshot_data['snapshot_date'] = datetime.now().date()
                        
                        # B. Save to Database
                        # Initialize engine only when needed
                        engine = dbfunctions.create_engine(DB_URL) 
                        
                        # Call your save function
                        stats = dbfunctions.save_import_data(engine, df_transactions, snapshot_data)
                        
                        # C. Show Results
                        st.success("Import Complete!")
                        
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Trades Added", stats['trades_added'])
                        col2.metric("Duplicates Skipped", stats['trades_skipped'])
                        col3.metric("Snapshot Date", str(snapshot_data['snapshot_date']))
                        
                        if stats['snapshot_added']:
                            st.info("✅ New Account Snapshot created.")
                        else:
                            st.warning("⚠️ Snapshot for this date already existed (Skipped).")
                            
                        with st.expander("View Imported Data"):
                            st.dataframe(df_transactions)

                    except Exception as e:
                        # Print the full error to the UI so we can see it
                        st.error(f"An error occurred: {e}")
                        # Optional: Print to console for detailed traceback
                        print(e)
    elif page == "Data Inspector":
            st.header("🔍 Database Inspector")
            
            # Initialize engine
            engine = init_db()
            
            # --- TAB 1: TRANSACTIONS ---
            st.subheader("Transactions Table")
            
            # We use Pandas to read the SQL table directly - it's the easiest way to display it
            # strict=False allows reading even if some columns are weird types
            try:
                with engine.connect() as conn:
                    df_trades = pd.read_sql('SELECT * FROM "transaction" ORDER BY exec_date DESC, exec_time DESC', conn)
                    df_snaps = pd.read_sql("SELECT * FROM accountsnapshot ORDER BY snapshot_date DESC", conn)
                
                # Metric Summary
                st.metric("Total Transactions Stored", len(df_trades))
                
                # Display with Filters
                # We use st.dataframe with 'use_container_width' for a nice wide view
                st.dataframe(df_trades, use_container_width=True)
                
                st.divider()
                
                # --- TAB 2: SNAPSHOTS ---
                st.subheader("Account Snapshots")
                st.metric("Total Daily Snapshots", len(df_snaps))
                st.dataframe(df_snaps, use_container_width=True)
                
            except Exception as e:
                st.error(f"Could not read database: {e}")
                st.info("If you just deleted the DB, go to 'Import Data' to re-import your CSV.")

if __name__ == "__main__":
    main()
    
