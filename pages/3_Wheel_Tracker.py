import streamlit as st
import pandas as pd
import os
import hashlib
from datetime import date, datetime
from sqlmodel import Session, select, col
from src.models import Transaction, Campaign, Strategy, AccountSnapshot, PositionSnapshot
from src.dbfunctions import create_engine_func

# --- SETUP ---
st.set_page_config(page_title="Wheel Tracker", layout="wide")

@st.cache_resource
def get_db_engine():
    db_file = os.path.join("data", "portfolio.db")
    db_url = f"sqlite:///{db_file}"
    return create_engine_func(db_url)

engine = get_db_engine()

st.title("🎡 The Wheel Tracker")

# --- HELPER: GENERATE HASH ---
def generate_hash(record_dict):
    date_str = str(record_dict.get('Exec_Date', ''))
    time_str = str(record_dict.get('Exec_Time', ''))
    if time_str.count(':') == 2: time_str = time_str.rsplit(':', 1)[0]
    symbol = str(record_dict.get('Symbol', '')).upper().strip()
    side = str(record_dict.get('Side', '')).upper().strip()
    try: qty_str = f"{float(record_dict.get('Qty', 0)):.4f}"
    except: qty_str = "0.0000"
    try: price_str = f"{float(record_dict.get('Price', 0)):.4f}"
    except: price_str = "0.0000"
    raw_str = f"{date_str}|{time_str}|{symbol}|{side}|{qty_str}|{price_str}"
    return hashlib.md5(raw_str.encode()).hexdigest()

# --- HELPER: ANALYZE WHEEL ---
def analyze_wheel_stats(campaign, session):
    trades = session.exec(select(Transaction).where(Transaction.campaign_id == campaign.id)).all()
    latest_snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())).first()
    
    current_positions = []
    current_price = 0.0
    
    if latest_snap:
        current_positions = session.exec(
            select(PositionSnapshot)
            .where(PositionSnapshot.snapshot_id == latest_snap.id)
            .where(PositionSnapshot.symbol == campaign.symbol)
        ).all()
        for p in current_positions:
            if p.asset_type == 'STOCK':
                current_price = p.mark_price
                break
        if current_price == 0 and current_positions:
            current_price = current_positions[0].mark_price 

    shares_qty = 0
    open_csp_qty = 0
    open_cc_qty = 0
    long_calls_qty = 0
    long_call_synth_cost = 0.0 

    for p in current_positions:
        if p.asset_type == 'STOCK':
            shares_qty += p.qty
        elif p.asset_type == 'OPTION':
            otype = p.option_type or "Unknown"
            if otype == 'PUT' and p.qty < 0:
                open_csp_qty += abs(p.qty)
            elif otype == 'CALL':
                if p.qty < 0: open_cc_qty += abs(p.qty)
                elif p.qty > 0: 
                    long_calls_qty += p.qty
                    long_call_synth_cost += (p.strike or 0) * 100 * p.qty

    total_premiums = 0.0
    total_stock_cost = 0.0
    long_call_premium_paid = 0.0
    
    # NEW VARIABLES FOR RATIO
    options_sold_qty = 0
    gross_premium_collected = 0.0

    for t in trades:
        is_option = (t.option_type is not None)
        is_stock_trade = (not is_option)
        is_long_call_buy = (is_option and t.option_type == 'CALL' and t.qty > 0)
        
        # AGGREGATION: Track average premium on sold contracts (Positive cash flow)
        if is_option and t.cb_amount > 0:
            options_sold_qty += abs(t.qty)
            gross_premium_collected += t.cb_amount
        
        if is_stock_trade and t.qty > 0:
            total_stock_cost += abs(t.cb_amount)
        elif is_long_call_buy:
             long_call_premium_paid += abs(t.cb_amount)
        else:
            total_premiums += t.cb_amount

    total_controlled_shares = shares_qty + (long_calls_qty * 100)
    total_invested = total_stock_cost + long_call_premium_paid + long_call_synth_cost
    
    acb = 0.0
    if total_controlled_shares > 0:
        acb = (total_invested - total_premiums) / total_controlled_shares
    
    net_pl = (total_premiums - total_stock_cost - long_call_premium_paid) + (shares_qty * current_price)

    status_parts = []
    if shares_qty > 0: status_parts.append(f"{int(shares_qty)} Sh")
    if long_calls_qty > 0: status_parts.append(f"{int(long_calls_qty)} PMCC")
    if open_csp_qty > 0: status_parts.append(f"-{int(open_csp_qty)} CSP")
    if open_cc_qty > 0: status_parts.append(f"-{int(open_cc_qty)} CC")
    status_str = " | ".join(status_parts) if status_parts else "Idle"

    # AGGREGATION: Calculate the Premium to Share Ratio
    avg_premium = (gross_premium_collected / options_sold_qty) / 100 if options_sold_qty > 0 else 0.0
    share_accum_ratio = (avg_premium * 100) / current_price if current_price > 0 else 0.0

    return {
        "id": campaign.id,
        "Symbol": campaign.symbol,
        "Campaign": campaign.name,
        "Adj Cost Basis": acb,
        "Current Price": current_price,
        "Premium-to-Share Ratio": round(share_accum_ratio, 2),
        "Net P/L": net_pl,
        "Status": status_str
    }

# --- MAIN PAGE LOGIC ---
with Session(engine) as session:
    wheel_strategies = session.exec(select(Strategy.id).where(col(Strategy.name).in_(["The Wheel", "Cash Secured Put", "Covered Call"]))).all()
    
    if not wheel_strategies:
        st.error("No compatible strategies found.")
        st.stop()
        
    campaigns = session.exec(select(Campaign).where(col(Campaign.strategy_id).in_(wheel_strategies)).order_by(Campaign.start_date.desc())).all()
    
    if not campaigns:
        st.info("No active campaigns found.")
        st.stop()

    # 1. SUMMARY TABLE
    table_data = []
    for camp in campaigns:
        table_data.append(analyze_wheel_stats(camp, session))
    
    df_summary = pd.DataFrame(table_data)
    
    st.subheader("📋 Active Wheels")

    st.dataframe(
        df_summary.drop(columns=["id"]), # Hides the ID column for cleaner UI
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # 2. CAMPAIGN MANAGER
    st.subheader("🛠️ Campaign Manager")
    camp_options = {c.name: c.id for c in campaigns}
    selected_camp_name = st.selectbox("Select Campaign", list(camp_options.keys()), label_visibility="collapsed")

    selected_camp_id = camp_options[selected_camp_name]
    selected_camp = next(c for c in campaigns if c.id == selected_camp_id)

    st.divider()

    # --- HISTORY SECTION ---
    if selected_camp:
        st.subheader(f"📖 History: {selected_camp.name}")
        
        # 1. Get History
        hist_trades = session.exec(
            select(Transaction)
            .where(Transaction.campaign_id == selected_camp.id)
            .order_by(Transaction.exec_date.desc())
        ).all()
        
        # 2. Get Open Positions (for matching)
        latest_snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())).first()
        active_signatures = set()
        
        if latest_snap:
            open_pos = session.exec(
                select(PositionSnapshot)
                .where(PositionSnapshot.snapshot_id == latest_snap.id)
                .where(PositionSnapshot.symbol == selected_camp.symbol)
            ).all()
            
            for p in open_pos:
                if p.asset_type == 'OPTION':
                    p_exp_str = str(p.exp_date) if p.exp_date else "None"
                    sig = f"{p.option_type}|{float(p.strike or 0):.1f}|{p_exp_str}"
                    active_signatures.add(sig)
        
        if hist_trades:
            display_rows = []
            today_date = date.today()
            
            for t in hist_trades:
                row = t.model_dump()
                
                # A. Calculate DTE (From TODAY)
                row['DTE_Current'] = None
                if t.exp_date:
                    try:
                        d_exp = pd.to_datetime(t.exp_date).date()
                        days_left = (d_exp - today_date).days
                        if days_left >= 0:
                            row['DTE_Current'] = days_left
                    except:
                        pass

                # B. Determine Active Status
                is_active = False
                if t.option_type:
                    t_exp_str = str(t.exp_date) if t.exp_date else "None"
                    t_sig = f"{t.option_type}|{float(t.strike or 0):.1f}|{t_exp_str}"
                    if t_sig in active_signatures:
                        is_active = True
                
                row['Status'] = "🟢 Open" if is_active else "History"
                
                display_rows.append(row)

            df_hist = pd.DataFrame(display_rows)
            
            cols_to_show = ['Status', 'exec_date', 'side', 'qty', 'option_type', 'strike', 'DTE_Current', 'price', 'cb_amount']
            final_cols = [c for c in cols_to_show if c in df_hist.columns]
            
            st.dataframe(
                df_hist[final_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "exec_date": "Date",
                    "cb_amount": st.column_config.NumberColumn("Net Cash", format="$%.2f"),
                    "DTE_Current": st.column_config.NumberColumn("DTE (Today)", help="Days remaining. Blank if expired."),
                    "Status": st.column_config.TextColumn("State"),
                }
            )
        else:
            st.info("No trade history for this campaign.")
            