import streamlit as st
import pandas as pd
from sqlmodel import Session, select, func
from datetime import date, timedelta
from src.models import AccountSnapshot, PositionSnapshot, Transaction
from src.dbfunctions import create_engine_func

# --- SETUP ---
st.set_page_config(page_title="Dashboard", layout="wide")
DB_URL = "sqlite:///portfolio.db"
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
        st.stop()
        
    # Get P/L Metrics (Realized)
    # This matches 'cb_amount' from transactions table
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
    # We need to query positions for this snapshot
    positions = session.exec(
        select(PositionSnapshot).where(PositionSnapshot.snapshot_id == latest_snap.id)
    ).all()
    
    if positions:
        df_pos = pd.DataFrame([p.model_dump() for p in positions])
        
        # A. Option Buckets (DTE)
        # We need to calculate DTE dynamically relative to TODAY (or snapshot date)
        if 'exp_date' in df_pos.columns:
            df_options = df_pos[df_pos['asset_type'] == 'OPTION'].copy()
            if not df_options.empty:
                # Convert exp_date to datetime if needed
                df_options['exp_date'] = pd.to_datetime(df_options['exp_date']).dt.date
                df_options['dte'] = (df_options['exp_date'] - latest_snap.snapshot_date).dt.days
                
                # Buckets
                def bucket_dte(d):
                    if d < 30: return "< 30 Days"
                    elif d <= 180: return "30-180 Days"
                    return "> 180 Days"
                
                df_options['bucket'] = df_options['dte'].apply(bucket_dte)
                
                # Chart Data
                chart_data = df_options.groupby(['bucket', 'option_type'])['market_value'].sum().unstack().fillna(0)
                
                # B. Cash at Risk (Short Puts)
                # Logic: Short Put Risk = Strike * Qty * 100 (if Qty is negative)
                # Note: ToS positions Qty is signed? Usually Long is +1, Short is -1.
                # Let's verify with your data. Assuming Short = Negative Qty.
                df_csp = df_options[
                    (df_options['option_type'] == 'PUT') & 
                    (df_options['qty'] < 0)
                ].copy()
                
                df_csp['risk'] = df_csp['strike'] * df_csp['qty'].abs() * 100
                total_risk = df_csp['risk'].sum()
                
                # 15-30 Day Risk
                risk_near = df_csp[
                    (df_csp['dte'] >= 15) & (df_csp['dte'] <= 30)
                ]['risk'].sum()

                # DISPLAY ROW 2
                c1, c2 = st.columns([2, 1])
                
                with c1:
                    st.subheader("Option Exposure (Market Value)")
                    st.bar_chart(chart_data)
                    
                with c2:
                    st.subheader("Cash Secured Put Risk")
                    st.metric("Total Assignment Risk", f"${total_risk:,.0f}")
                    st.metric("Risk Expiring (15-30 Days)", f"${risk_near:,.0f}")
                    st.progress(min(total_risk / (latest_snap.total_cash_balance + 1), 1.0), text="Cash Utilization %")

    st.markdown("---")

    # --- SECTION 3: ATTENTION LIST ---
    st.subheader("⚠️ Attention Needed")
    
    if positions and not df_options.empty:
        # Filter 1: Expiring Soon (< 14 Days)
        near_exp = df_options[df_options['dte'] < 14].copy()
        
        # Filter 2: Near Strike (Within 10%)
        # Logic: abs(Mark - Strike) / Strike < 0.10
        # Only relevant for Short positions usually? Let's show all.
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
                