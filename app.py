import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime, timedelta
from src.logger import get_config, set_config, log_event

# Must be the very first Streamlit command 
st.set_page_config(page_title="Pilot Portfolio HUD", page_icon="✈️", layout="wide")

# --- DEFINE NAVIGATION PAGES ---
# Streamlit will automatically look for these files and create the nice links in the sidebar
home_page = st.Page("pages/1_Home.py", title="Home", icon="🏠", default=True)
campaign_page = st.Page("pages/2_Campaigns.py", title="Campaigns", icon="📈")
wheel_page = st.Page("pages/3_Wheel_Tracker.py", title="Wheel Tracker", icon="🎡")
settings_page = st.Page("pages/4_Settings.py", title="Settings & Telemetry", icon="⚙️")
data_editor_page = st.Page("pages/5_Data_Editor.py", title="Data Editor", icon="📝")
allocation_page = st.Page("pages/6_401k_Allocation.py", title="401k Allocation", icon="📊")
radar_page = st.Page("pages/7_Advanced_Radar.py", title="Advanced Options Radar", icon="📡")

pg = st.navigation([home_page, campaign_page, wheel_page, settings_page, data_editor_page, allocation_page, radar_page])

# --- GLOBAL AUTH GATEKEEPER (Sidebar Annunciator Panel) ---
with st.sidebar:
    st.title("✈️ Flight Deck")
    st.markdown("---")
    
    registered_apis_str = get_config("REGISTERED_APIS", '["Schwab (Alpine Fire)", "Alpine Wind"]')
    try:
        registered_apis = json.loads(registered_apis_str)
    except json.JSONDecodeError:
        registered_apis = ["Schwab (Alpine Fire)", "Alpine Wind"]
    
    auth_warnings = []

    for api_name in registered_apis:
        safe_prefix = api_name.replace(" ", "_").replace("(", "").replace(")", "").upper()
        is_active = get_config(f"{safe_prefix}_API_ACTIVE") == "True"
        
        if is_active:
            expiry_str = get_config(f"{safe_prefix}_TOKEN_EXPIRY", "Not Authenticated")
            needs_auth = False
            
            if expiry_str == "Not Authenticated" or "Expired" in expiry_str:
                needs_auth = True
            else:
                try:
                    expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() > expiry_dt:
                        needs_auth = True
                except ValueError:
                    needs_auth = True
                    
            if needs_auth:
                auth_warnings.append({"name": api_name, "prefix": safe_prefix})

    if auth_warnings:
        st.error("⚠️ **API Disconnected**")
        
        for api in auth_warnings:
            with st.expander(f"🔑 Auth {api['name']}", expanded=True):
                
                # --- SCHWAB / ALPINE FIRE AUTH FLOW ---
                if api['prefix'] == "SCHWAB_ALPINE_FIRE":
                    from src.schwab_af_api import get_auth_url, fetch_initial_token 
                    from src.auth_utils import capture_oauth_code
                    
                    st.caption("1. Click to authorize app.")
                    try:
                        auth_url = get_auth_url() 
                        st.markdown(f"[**Alpine Fire Login**]({auth_url})")
                    except Exception as e:
                        st.error(f"URL Error: {e}")
                    
                    st.caption("2. Start Local Listener.")
                    
                    if st.button("Start Local Listener", key="af_listener", type="primary", use_container_width=True):
                        with st.spinner("Waiting for Schwab authorization..."):
                            auth_code = capture_oauth_code(port=8080, timeout=120, use_https=True)
                            
                            if auth_code:
                                st.success("Code captured! Exchanging for tokens...")
                                tokens = fetch_initial_token(auth_code) 
                                
                                if tokens:
                                    new_expiry = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                                    set_config(f"{api['prefix']}_TOKEN_EXPIRY", new_expiry, "Alpine Fire API Expiry")
                                    st.success("✅ Success")
                                    time.sleep(1) 
                                    st.rerun()
                                else:
                                    st.error("Failed to fetch tokens.")
                            else:
                                st.error("Listener timed out or failed.")

                # --- ALPINE WIND AUTH FLOW ---
                elif api['prefix'] == "ALPINE_WIND":
                    from src.schwab_aw_api import get_auth_url, fetch_initial_token 
                    from src.auth_utils import capture_oauth_code
                    
                    st.caption("1. Click to authorize app.")
                    try:
                        auth_url = get_auth_url() 
                        st.markdown(f"[**Alpine Wind Login**]({auth_url})")
                    except Exception as e:
                        st.error(f"URL Error: {e}")
                    
                    st.caption("2. Start Local Listener.")
                    
                    if st.button("Start Local Listener", key="aw_listener", type="primary", use_container_width=True):
                        with st.spinner("Waiting for Schwab authorization..."):
                            auth_code = capture_oauth_code(port=8080, timeout=120, use_https=True)
                            
                            if auth_code:
                                st.success("Code captured! Exchanging for tokens...")
                                tokens = fetch_initial_token(auth_code) 
                                
                                if tokens:
                                    new_expiry = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                                    set_config(f"{api['prefix']}_TOKEN_EXPIRY", new_expiry, "Alpine Wind API Expiry")
                                    st.success("✅ Success")
                                    time.sleep(1) 
                                    st.rerun()
                                else:
                                    st.error("Failed to fetch tokens.")
                            else:
                                st.error("Listener timed out or failed.")
                else:
                    st.warning("No script linked.")

# RUN THE SELECTED PAGE
pg.run()
