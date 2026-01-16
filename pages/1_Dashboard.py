import streamlit as st
import pandas as pd
import os 
from sqlmodel import Session, select, func
from datetime import date, timedelta
from src.models import AccountSnapshot, PositionSnapshot, Transaction
from src.dbfunctions import create_engine_func

# --- SETUP ---
st.set_page_config(page_title="Dashboard", layout="wide")

@st.cache_resource
def get_db_engine():
    db_file = os.path.join("data", "portfolio.db")
    db_url = f"sqlite:///{db_file}"
    return create_engine_func(db_url)

engine = get_db_engine()

st.title("🚀 Options Command Center")

# --- SECTION 1: HIGH LEVEL METRICS ---
with Session(engine) as session:
    latest_snap = session.exec(
        select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())
    ).first()
    
    if not latest_snap:
        st.error("No data found. Please import a file on the Home page.")
        st.stop()
        
    today = date.today()
    ytd_start = date(today.year, 1, 1)
    d30_start = today - timedelta(days=30)
    d7_start = today - timedelta(days=7)
    
    def get_pl(start_date):
        query = select(func.sum(Transaction.cb_amount)).where(Transaction.exec_date >= start_date)
        result = session.exec(query).first()
        return result if result else 0.0

    col1, col2, col3, col4, col5 = st.columns(5)
    
    valid_color = "normal" if latest_snap.is_net_liq_valid else "off"
    nlv_label = "Net Liquidating Value"
    if not latest_snap.is_net_liq_valid: nlv_label += " (Est.)"
        
    col1.metric(nlv_label, f"${latest_snap.net_liquidating_value:,.2f}")
    col2.metric("Cash Balance", f"${latest_snap.total_cash_balance:,.2f}")
    col3.metric("YTD Realized P/L", f"${get_pl(ytd_start):,.2f}")
    col4.metric("30-Day Realized", f"${get_pl(d30_start):,.2f}")
    col5.metric("7-Day Realized", f"${get_pl(d7_start):,.2f}")

    st.markdown("---")

    # --- SECTION 2: RISK & ALLOCATION ---
    positions = session.exec(
        select(PositionSnapshot).where(PositionSnapshot.snapshot_id == latest_snap.id)
    ).all()
    
    if positions:
        df_pos = pd.DataFrame([p.model_dump() for p in positions])
        
        # FIX 1: FILTER JUNK ROWS (Totals) 
        df_pos = df_pos[~df_pos['symbol'].astype(str).str.contains("TOTAL", case=False, na=False)]

        # FIX 2: FORCE NUMERIC
        cols_to_numeric = ['qty', 'mark_price', 'market_value', 'strike']
        for col in cols_to_numeric:
            if col in df_pos.columns:
                df_pos[col] = pd.to_numeric(df_pos[col], errors='coerce').fillna(0.0)

        if 'exp_date' in df_pos.columns:
            df_options = df_pos[df_pos['asset_type'] == 'OPTION'].copy()
            if not df_options.empty:
                
                # Timestamp Logic 
                df_options['exp_date'] = pd.to_datetime(df_options['exp_date'])
                snap_date_ts = pd.to_datetime(latest_snap.snapshot_date)
                df_options['dte'] = (df_options['exp_date'] - snap_date_ts).dt.days
                
                def bucket_dte(d):
                    if d < 30: return "< 30 Days"
                    elif d <= 180: return "30-180 Days"
                    return "> 180 Days"
                
                df_options['bucket'] = df_options['dte'].apply(bucket_dte)
                chart_data = df_options.groupby(['bucket', 'option_type'])['market_value'].sum().unstack().fillna(0)
                
                # Cash Secured Put Risk
                df_csp = df_options[(df_options['option_type'] == 'PUT') & (df_options['qty'] < 0)].copy()
                total_risk = df_csp['risk'] = (df_csp['strike'] * df_csp['qty'].abs() * 100).sum() if not df_csp.empty else 0
                risk_near = df_csp[(df_csp['dte'] >= 15) & (df_csp['dte'] <= 30)]['risk'].sum() if not df_csp.empty else 0

                c1, c2 = st.columns([2, 1])
                with c1:
                    st.subheader("Option Exposure")
                    st.bar_chart(chart_data)
                with c2:
                    st.subheader("Put Assignment Risk")
                    st.metric("Total", f"${total_risk:,.0f}")
                    st.metric("15-30 Days", f"${risk_near:,.0f}")

    st.markdown("---")

    # --- SECTION 3: ATTENTION LIST ---
    st.subheader("⚠️ Attention Needed")
    
    if positions and 'df_options' in locals() and not df_options.empty:
        near_exp = df_options[df_options['dte'] < 14].copy()
        
        # FIX 3: Initialize to 999.0 so 0-strike rows don't qualify
        df_options['strike_dist_pct'] = 999.0 
        mask_nonzero = df_options['strike'] > 0
        
        df_options.loc[mask_nonzero, 'strike_dist_pct'] = (
            (df_options.loc[mask_nonzero, 'mark_price'] - df_options.loc[mask_nonzero, 'strike']).abs() 
            / df_options.loc[mask_nonzero, 'strike']
        ) * 100
        
        near_strike = df_options[df_options['strike_dist_pct'] < 10.0].copy()
        
        tab1, tab2 = st.tabs(["Expiring Soon (<14d)", "Close to Strike (<10%)"])
        
        with tab1:
            if not near_exp.empty:
                st.dataframe(near_exp[['symbol', 'description', 'qty', 'dte', 'market_value']], use_container_width=True)
            else:
                st.info("No options expiring in the next 14 days.")
                
        with tab2:
            if not near_strike.empty:
                st.dataframe(near_strike[['symbol', 'description', 'qty', 'mark_price', 'strike', 'strike_dist_pct']], use_container_width=True)
            else:
                st.info("No options currently within 10% of strike price.")
                