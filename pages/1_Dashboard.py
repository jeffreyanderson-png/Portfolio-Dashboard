import streamlit as st
import pandas as pd
import os 
from sqlmodel import Session, select, func
from datetime import date, timedelta
from src.models import AccountSnapshot, PositionSnapshot, Transaction
from src.dbfunctions import create_engine_func

# --- SETUP ---
st.set_page_config(page_title="Dashboard", layout="wide")

# FIX: Point to the 'data' folder, just like app.py does
DB_FILE = os.path.join("data", "portfolio.db")
DB_URL = f"sqlite:///{DB_FILE}"

engine = create_engine_func(DB_URL)

st.title("🚀 Options Command Center")

# --- SECTION 1: HIGH LEVEL METRICS ---
with Session(engine) as session:
    # Get Latest Snapshot
    latest_snap = session.exec(
        select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())
    ).first()
    
    if not latest_snap:
        st.error("No data found. Please import a file on the Home page.")
        # Optional: Add a debug message to help verify path
        st.caption(f"Looking for database at: {os.path.abspath(DB_FILE)}")
        st.stop()
        
    # Get P/L Metrics (Realized)
    today = date.today()
    ytd_start = date(today.year, 1, 1)
    d30_start = today - timedelta(days=30)
    d7_start = today - timedelta(days=7)
    
    def get_pl(start_date):
        query = select(func.sum(Transaction.cb_amount)).where(Transaction.exec_date >= start_date)
        result = session.exec(query).first()
        return result if result else 0.0

    pl_ytd = get_pl(ytd_start)
    pl_30 = get_pl(d30_start)
    pl_7 = get_pl(d7_start)

    # --- ROW 1: SCORECARD ---
    col1, col2, col3, col4, col5 = st.columns(5)
    
    # Net Liq
    valid_color = "normal" if latest_snap.is_net_liq_valid else "off"
    nlv_label = "Net Liquidating Value"
    if not latest_snap.is_net_liq_valid:
        nlv_label += " (Est. from Cash Date)"
        
    col1.metric(nlv_label, f"${latest_snap.net_liquidating_value:,.2f}")
    col2.metric("Cash Balance", f"${latest_snap.total_cash_balance:,.2f}")
    col3.metric("YTD Realized P/L", f"${pl_ytd:,.2f}", delta_color="normal")
    col4.metric("30-Day Realized", f"${pl_30:,.2f}")
    col5.metric("7-Day Realized", f"${pl_7:,.2f}")

    st.markdown("---")

    # --- SECTION 2: RISK & ALLOCATION ---
    positions = session.exec(
        select(PositionSnapshot).where(PositionSnapshot.snapshot_id == latest_snap.id)
    ).all()
    
    if positions:
        df_pos = pd.DataFrame([p.model_dump() for p in positions])
        
        # A. Option Buckets (DTE)
        if 'exp_date' in df_pos.columns:
            df_options = df_pos[df_pos['asset_type'] == 'OPTION'].copy()
            if not df_options.empty:
                # FIX: Convert BOTH to Pandas Timestamp for safe subtraction
                df_options['exp_date'] = pd.to_datetime(df_options['exp_date'])
                snap_date_ts = pd.to_datetime(latest_snap.snapshot_date)
                
                # Calculate Days to Expiration
                df_options['dte'] = (df_options['exp_date'] - snap_date_ts).dt.days
                
                # For display, we can convert back to date objects if needed, 
                # but let's keep it as timestamp for the math logic.
                
                def bucket_dte(d):
                    if d < 30: return "< 30 Days"
                    elif d <= 180: return "30-180 Days"
                    return "> 180 Days"
                
                df_options['bucket'] = df_options['dte'].apply(bucket_dte)
                
                # Market Value Chart
                chart_data = df_options.groupby(['bucket', 'option_type'])['market_value'].sum().unstack().fillna(0)
                
                # B. Cash at Risk (Short Puts)
                df_csp = df_options[
                    (df_options['option_type'] == 'PUT') & 
                    (df_options['qty'] < 0)
                ].copy()
                
                total_risk = 0.0
                risk_near = 0.0
                
                if not df_csp.empty:
                    # Fix: Ensure strike is numeric
                    df_csp['strike'] = pd.to_numeric(df_csp['strike'], errors='coerce').fillna(0)
                    df_csp['qty'] = pd.to_numeric(df_csp['qty'], errors='coerce').fillna(0)
                    
                    df_csp['risk'] = df_csp['strike'] * df_csp['qty'].abs() * 100
                    total_risk = df_csp['risk'].sum()
                    risk_near = df_csp[(df_csp['dte'] >= 15) & (df_csp['dte'] <= 30)]['risk'].sum()

                c1, c2 = st.columns([2, 1])
                
                with c1:
                    st.subheader("Option Exposure (Market Value)")
                    st.bar_chart(chart_data)
                    
                with c2:
                    st.subheader("Cash Secured Put Risk")
                    st.metric("Total Assignment Risk", f"${total_risk:,.0f}")
                    st.metric("Risk Expiring (15-30 Days)", f"${risk_near:,.0f}")
                    if latest_snap.total_cash_balance > 0:
                        util_pct = min(total_risk / latest_snap.total_cash_balance, 1.0)
                        st.progress(util_pct, text=f"Cash Utilization: {util_pct:.1%}")

    st.markdown("---")

    # --- SECTION 3: ATTENTION LIST ---
    st.subheader("⚠️ Attention Needed")
    
    if positions and 'df_options' in locals() and not df_options.empty:
        # Filter 1: Expiring Soon (< 14 Days)
        near_exp = df_options[df_options['dte'] < 14].copy()
        
        # Filter 2: Near Strike (Within 10%)
        df_options['strike_dist_pct'] = ((df_options['mark_price'] - df_options['strike']).abs() / df_options['strike']) * 100
        near_strike = df_options[df_options['strike_dist_pct'] < 10.0].copy()
        
        tab1, tab2 = st.tabs(["Expiring Soon (<14d)", "Close to Strike (<10%)"])
        
        with tab1:
            if not near_exp.empty:
                st.dataframe(near_exp[['symbol', 'description', 'qty', 'exp_date', 'dte', 'market_value']])
            else:
                st.info("No options expiring in the next 14 days.")
                
        with tab2:
            if not near_strike.empty:
                st.dataframe(near_strike[['symbol', 'description', 'qty', 'mark_price', 'strike', 'strike_dist_pct']])
            else:
                st.info("No options currently within 10% of strike price.")
