import streamlit as st
import pandas as pd
#from datetime import datetime
import sys
import os
#import hashlib
#import time
#import re
from sqlmodel import SQLModel, create_engine, Session

# --- SETUP: Make sure we can find the 'src' folder --- 
#import sys 
#sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# --- LOCAL IMPORTS ---
import src.dbfunctions as dbfunctions
import src.import_tos_csv as import_tos_csv
from src.models import Transaction, AccountSnapshot
from src import seed_data
from src.dbfunctions import create_engine_func # Ensure you have this import 

# --- CONSTANTS ---
DB_FOLDER = "data"
DB_FILE = "portfolio.db"
DB_PATH = os.path.join(DB_FOLDER, DB_FILE)
# SQLModel needs a URL format for the engine (sqlite:///path/to/db)
DB_URL = f"sqlite:///{DB_PATH}"
VER_STR = "2.3"

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Pilot Portfolio Manager v" + VER_STR,
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZATION --- 
@st.cache_resource # <--- THIS STOPS THE RE-RUNS
def init_db():
    """Checks if DB exists, creates folder if needed."""
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER)
    
    # --- INITIALIZATION ---
    engine = create_engine_func(DB_URL)

    # 1. Create Tables (Idempotent - won't break if they exist)
    SQLModel.metadata.create_all(engine)
    
    # 2. Seed Data (Now safe to run because tables exist)
    seed_data.seed_strategies(DB_URL)
    
    return engine

# --- MAIN APP LOGIC ---
def main():
    st.title("✈️ Pilot Portfolio Manager v" + VER_STR)
    # Ensure DB tables exist before we do anything else 
    init_db()
    
    # Sidebar for Navigation
    #page = st.sidebar.selectbox("Go to", ["Dashboard", "Import Data", "Data Inspector", "Settings"])
    page = st.sidebar.selectbox("Go to", ["Import Data", "Data Inspector", "Settings"])

    #if page == "Dashboard":
    #    st.write("### Welcome Back")
    #    st.info("Database not yet connected. Go to 'Import Data' to start.")
        
    #elif page == "Import Data":
    if page == "Import Data":
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
                        # Note: Now returns two LISTS
                        transactions_list, snapshots_list = import_tos_csv.parse_file(uploaded_file)
                        
                        # Convert transactions to DataFrame for display/metrics
                        df_transactions = pd.DataFrame(transactions_list)

                        # B. Save to Database
                        engine = dbfunctions.create_engine(DB_URL) 
                        
                        # Pass the lists directly to the new dbfunctions logic
                        stats = dbfunctions.save_import_data(engine, transactions_list, snapshots_list)
                        
                        # C. Show Results
                        st.success("Import Complete!")
                        
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Trades Added", stats['trades_added'])
                        col2.metric("Snapshots Processed", stats['snapshots_processed'])
                        col3.metric("Positions Added", stats['positions_added'])
                        col4.metric("Tradses Healed", stats['trades_healed'])
                        
                        # (Remove the old snapshot date warning logic, it's handled per-row now)
                            
                        with st.expander("View Imported Data"):
                            if not df_transactions.empty:
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
    
