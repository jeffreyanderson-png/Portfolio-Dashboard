import streamlit as st
import pandas as pd
import os
from datetime import date, timedelta
from sqlmodel import Session, select, func, col
from src.models import Transaction, AccountSnapshot, PositionSnapshot
from src.dbfunctions import create_engine_func

import pandas_ta_classic as ta  # Efficient technical analysis library

st.set_page_config(page_title="Dashboard", layout="wide")

@st.cache_resource
def get_db_engine():
    db_file = os.path.join("data", "portfolio.db")
    db_url = f"sqlite:///{db_file}"
    return create_engine_func(db_url)

engine = get_db_engine()

st.title("🚀 Portfolio Dashboard")

# --- HELPER: DATES ---
today = date.today()
start_of_year = date(today.year, 1, 1)
d30_start = today - timedelta(days=30)
d60_start = today - timedelta(days=60)

# --- SECTION 1: PREMIUM ENGINE (Income) ---
st.header("💸 Premium Income (Net)")

with Session(engine) as session:
    # 1. FETCH OPTION TRANSACTIONS
    # STRICT FILTER: Must be explicitly CALL or PUT.
    # We also keep the +/- 5000 limit to catch any accidental large assignments.
    
    def get_premium_sum(start_date, end_date=None):
        query = select(func.sum(Transaction.cb_amount)).where(
            col(Transaction.option_type).in_(["CALL", "PUT", "Call", "Put"]), # Handle case sensitivity
            Transaction.exec_date >= start_date,
            Transaction.cb_amount.between(-5000, 5000) 
        )
        if end_date:
            query = query.where(Transaction.exec_date < end_date)
        
        result = session.exec(query).first()
        return result if result else 0.0

    ytd_premium = get_premium_sum(start_of_year)
    last_30_premium = get_premium_sum(d30_start)
    prior_30_premium = get_premium_sum(d60_start, d30_start)
    
    delta_30 = last_30_premium - prior_30_premium

    c1, c2, c3 = st.columns(3)
    c1.metric("YTD Option Income", f"${ytd_premium:,.2f}")
    c2.metric("Last 30 Days", f"${last_30_premium:,.2f}", delta=f"{delta_30:,.2f} vs Prior")
    c3.metric("Prior 30 Days", f"${prior_30_premium:,.2f}")

    # --- DEBUG / AUDIT TOOL ---
    with st.expander("🕵️ Audit: Premium Log (Last 30 Days)"):
        st.caption("Transactions counted as 'Premium' (Filtered for CALL/PUT only):")
        audit_trades = session.exec(
            select(Transaction)
            .where(Transaction.exec_date >= d30_start)
            .where(col(Transaction.option_type).in_(["CALL", "PUT", "Call", "Put"]))
            .where(Transaction.cb_amount.between(-5000, 5000))
            .order_by(Transaction.cb_amount.desc())
            .limit(20)
        ).all()
        if audit_trades:
            st.dataframe(pd.DataFrame([t.model_dump() for t in audit_trades])[
                ['exec_date', 'symbol', 'option_type', 'side', 'cb_amount', 'cb_description']
            ])

    st.divider()

    # --- SECTION 2: CAPITAL & RISK ---
    st.header("🛡️ Capital & Risk")
    
    latest_snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())).first()
    
    if not latest_snap:
        st.warning("No data found.")
        st.stop()
        
    positions = session.exec(select(PositionSnapshot).where(PositionSnapshot.snapshot_id == latest_snap.id)).all()
    
    csp_collateral = 0.0
    stock_value = 0.0
    put_risk_total = 0.0
    
    # 3. ACTION TABLE LOGIC
    action_items = []
    
    for p in positions:
        # Capital Math
        if p.asset_type == 'STOCK':
            stock_value += (p.market_value or 0.0)
        elif p.asset_type == 'OPTION':
            otype = p.option_type or "Unknown"
            
            # Risk Math (Only Short Puts)
            if otype == 'PUT' and p.qty < 0:
                risk = (p.strike or 0) * 100 * abs(p.qty)
                csp_collateral += risk
                put_risk_total += risk

            # --- ACTION SCANNER ---
            reasons = []
            
            # Condition 1: Expiring Soon (< 7 Days)
            dte = 999
            if p.exp_date:
                dte = (pd.to_datetime(p.exp_date).date() - today).days
                if dte < 7: reasons.append(f"⏳ Expiring ({dte}d)")
            
            # Condition 2: Near Strike (10% or $0.50)
            if p.strike:
                mark = p.mark_price or 0
                dist = abs(mark - p.strike)
                # Logic: If Mark is close to Strike
                # Note: For Short Puts, "Close" means Price is dropping to Strike
                # For Short Calls, "Close" means Price is rising to Strike
                # We simplified to absolute distance here
                threshold = max(0.50, p.strike * 0.10)
                if dist <= threshold:
                    reasons.append("🎯 Near Strike")

            # Condition 3: Cheap Buyback (Mark < $0.10) for Short Positions
            if p.qty < 0 and (p.mark_price or 0) < 0.10:
                reasons.append("💰 Cheap Buyback")
            
            if reasons:
                action_items.append({
                    "Symbol": p.symbol,
                    "Qty": int(p.qty),
                    "Type": f"{otype} {p.strike}",
                    "Exp": p.exp_date,
                    "Mark": p.mark_price,
                    "Action Needed": ", ".join(reasons)
                })

    # Capital Display
    col_cap1, col_cap2, col_cap3 = st.columns(3)
    col_cap1.metric("Stock Holdings", f"${stock_value:,.2f}")
    col_cap2.metric("Cash Securing Puts", f"${csp_collateral:,.2f}")
    col_cap3.metric("Total Put Risk", f"${put_risk_total:,.0f}")
    
    st.divider()

    # --- SECTION 3: ACTION TABLE ---
    st.subheader("⚡ Action Needed")
    if action_items:
        df_action = pd.DataFrame(action_items)
        st.dataframe(
            df_action,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Mark": st.column_config.NumberColumn(format="$%.2f"),
                "Exp": st.column_config.DateColumn(format="MM/DD")
            }
        )
    else:
        st.success("No urgent actions found. Portfolio is cruising! 🚢")

       

def calculate_rsi(df, period=14):
    # Uses the standard Wilder's RSI calculation
    df['RSI'] = ta.rsi(df['close'], length=period)
    return df

def check_retest_condition(df, overbought=70, oversold=30):
    """
    Logic: Triggers an alert if the RSI was recently oversold 
    and is now performing a 'retest' of a specific level.
    """
    latest_rsi = df['RSI'].iloc[-1]
    prev_rsi = df['RSI'].iloc[-2]
    
    # Example 'Retest' Logic: RSI was below 30, rose, and is now 
    # stabilizing/dipping back toward a 40-45 level before a move higher.
    if 40 <= latest_rsi <= 48 and prev_rsi > latest_rsi:
        return True, latest_rsi
    return False, latest_rsi

# --- Streamlit UI ---
st.title("Gold Futures (/MGC) Scalp Alert")

# Mock data load - Replace with your live API feed (e.g., yfinance or TwelveData)
# df = get_live_mgc_data() 

if 'df' in locals():
    df = calculate_rsi(df)
    alert_triggered, rsi_val = check_retest_condition(df)

    if alert_triggered:
        st.error(f"🚨 RETEST ALERT: /MGC RSI at {rsi_val:.2f}")
        # Optional: Add an audio ping using HTML
        st.components.v1.html(
            """<audio autoplay><source src="https://www.soundjay.com/buttons/beep-01a.mp3" type="audio/mpeg"></audio>""",
            height=0,
        )
    else:
        st.success(f"Monitoring... Current RSI: {rsi_val:.2f}")