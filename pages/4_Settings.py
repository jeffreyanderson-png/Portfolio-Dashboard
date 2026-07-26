import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.utils import get_db_engine
from src.logger import get_config, set_config, log_event, SystemLog
from datetime import datetime

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

st.title("Settings")
st.markdown("---")

tab1, tab2 = st.tabs(["API Connections", "System Logs & Config"])

# --- TAB 1: API MANAGEMENT ---
with tab1:
    st.subheader("Data Sources")
    st.write("Manage active API connections and token states.")
    
    # --- DYNAMIC API ENGINE ---
    import json
    
    # Fetch the master list of registered APIs (Defaulting to your two primary Schwab feeds)
    registered_apis_str = get_config("REGISTERED_APIS", '["Schwab (Alpine Fire)", "Alpine Wind"]')
    try:
        registered_apis = json.loads(registered_apis_str)
    except json.JSONDecodeError:
        registered_apis = ["Schwab (Alpine Fire)", "Alpine Wind"]
        
    # Dynamically render a control block for every registered API
    for api_name in registered_apis:
        # Create a safe, uppercase string to use as the database key (e.g., "ALPINE_WIND")
        safe_prefix = api_name.replace(" ", "_").replace("(", "").replace(")", "").upper()
        active_key = f"{safe_prefix}_API_ACTIVE"
        expiry_key = f"{safe_prefix}_TOKEN_EXPIRY"
        
        # Initialize default state in DB if it doesn't exist
        if not get_config(active_key):
            set_config(active_key, "False", f"Toggle for {api_name}")
            
        is_active = get_config(active_key) == "True"
        expiry = get_config(expiry_key, "Not Authenticated")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"#### {api_name}")
            toggle_state = st.checkbox("Enable Connection", value=is_active, key=f"toggle_{safe_prefix}")
            
            if toggle_state != is_active:
                set_config(active_key, str(toggle_state))
                log_event("INFO", "Settings", f"{api_name} connection state changed to {toggle_state}")
                st.rerun()
                
        with col2:
            # Color code the expiration text based on status
            if expiry == "Not Authenticated" or "Expired" in expiry:
                st.error(f"**Token Status:** {expiry}")
            else:
                st.info(f"**Access Token Expires:** {expiry}")
                
        st.markdown("---")

    # --- REGISTER NEW DATA SOURCE ---
    st.subheader("Register New Data Source")
    with st.form("new_api_form", clear_on_submit=True):
        col_in1, col_in2 = st.columns([2, 1])
        with col_in1:
            new_api_name = st.text_input("Data Source Name", placeholder="e.g., FRED Macro, CME Globex, IBKR")
        with col_in2:
            st.write("") # Vertical alignment spacing
            st.write("")
            add_api_btn = st.form_submit_button("Register Source", type="secondary")
            
        if add_api_btn:
            if not new_api_name:
                st.warning("Please enter a name for the new data source.")
            elif new_api_name in registered_apis:
                st.warning(f"'{new_api_name}' is already registered.")
            else:
                registered_apis.append(new_api_name)
                set_config("REGISTERED_APIS", json.dumps(registered_apis), "Master list of dynamic APIs")
                log_event("INFO", "Settings", f"Registered new data source: {new_api_name}")
                st.success(f"Successfully registered {new_api_name}!")
                st.rerun()

# --- TAB 2: SYSTEM LOGS ---
with tab2:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Configuration")
        
        # Logging Level
        current_level = get_config("LOG_LEVEL", "Basic")
        new_level = st.selectbox("Logging Level", ["Basic", "Verbose", "Debug"], index=["Basic", "Verbose", "Debug"].index(current_level) if current_level in ["Basic", "Verbose", "Debug"] else 0)
        if new_level != current_level:
            set_config("LOG_LEVEL", new_level, "System logging verbosity")
            st.success(f"Logging level set to {new_level}")
            
        # Max Log Size
        current_max = get_config("MAX_LOG_SIZE", "100")
        size_options = ["100", "200", "500", "1000"]
        new_max = st.selectbox("Max Log Size", size_options, index=size_options.index(current_max) if current_max in size_options else 0)
        if new_max != current_max:
            set_config("MAX_LOG_SIZE", new_max, "Maximum rows retained in SystemLog table")
            log_event("INFO", "Settings", f"Max Log Size updated to {new_max}")
            st.success(f"Log size capped at {new_max} rows")

    with col2:
        st.subheader("Live Telemetry")
        with Session(engine) as session:
            # Fetch logs in descending order (newest first)
            logs = session.exec(select(SystemLog).order_by(SystemLog.timestamp.desc())).all()
            
            if logs:
                log_data = [{
                    "Time": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "Level": log.level,
                    "Source": log.source,
                    "Message": log.message
                } for log in logs]
                
                st.dataframe(
                    pd.DataFrame(log_data),
                    column_config={
                        "Level": st.column_config.TextColumn(width="small"),
                        "Source": st.column_config.TextColumn(width="medium"),
                        "Message": st.column_config.TextColumn(width="large")
                    },
                    hide_index=True,
                    height=250, # Keeps the table compact
                    width='stretch'
                )
                
                # Log export functionality
                csv_export = pd.DataFrame(log_data).to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Log File (.txt)",
                    data=csv_export,
                    file_name=f"system_logs_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                )
            else:
                st.info("No system logs recorded yet.")
