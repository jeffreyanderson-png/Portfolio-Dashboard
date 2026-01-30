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

# --- HELPER: GENERATE HASH (For Safety Net) ---
def generate_hash(record_dict):
    # Same logic as import_tos_csv to prevent duplicates
    raw_str = "".join(str(val) for val in record_dict.values())
    return hashlib.md5(raw_str.encode()).hexdigest()

# --- HELPER: ANALYZE WHEEL ---
def analyze_wheel_stats(campaign, session):
    # 1. FETCH DATA
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
        # Find Price
        for p in current_positions:
            if p.asset_type == 'STOCK':
                current_price = p.mark_price
                break
        if current_price == 0 and current_positions:
            current_price = current_positions[0].mark_price 

    # 2. INVENTORY CHECK (For Status Column)
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

    # 3. CASH FLOW MATH
    total_premiums = 0.0
    total_stock_cost = 0.0
    long_call_premium_paid = 0.0

    for t in trades:
        is_option = (t.option_type is not None)
        is_stock_trade = (not is_option)
        is_long_call_buy = (is_option and t.option_type == 'CALL' and t.qty > 0)
        
        if is_stock_trade and t.qty > 0:
            total_stock_cost += abs(t.cb_amount)
        elif is_long_call_buy:
             long_call_premium_paid += abs(t.cb_amount)
        else:
            total_premiums += t.cb_amount

    # 4. METRICS
    total_controlled_shares = shares_qty + (long_calls_qty * 100)
    total_invested = total_stock_cost + long_call_premium_paid + long_call_synth_cost
    
    acb = 0.0
    if total_controlled_shares > 0:
        acb = (total_invested - total_premiums) / total_controlled_shares
    
    # Net P/L = Current Value + Net Cash Flow
    # Net Cash Flow = (Premiums - Stock Cost - Long Call Cost)
    # Current Value = (Shares * Price) ... roughly ignoring option mark value for speed
    net_pl = (total_premiums - total_stock_cost - long_call_premium_paid) + (shares_qty * current_price)

    # Status String
    status_parts = []
    if shares_qty > 0: status_parts.append(f"{int(shares_qty)} Sh")
    if long_calls_qty > 0: status_parts.append(f"{int(long_calls_qty)} PMCC")
    if open_csp_qty > 0: status_parts.append(f"-{int(open_csp_qty)} CSP")
    if open_cc_qty > 0: status_parts.append(f"-{int(open_cc_qty)} CC")
    status_str = " | ".join(status_parts) if status_parts else "Idle"

    return {
        "id": campaign.id,
        "Symbol": campaign.symbol,
        "Campaign": campaign.name,
        "Adj Cost Basis": acb,
        "Current Price": current_price,
        "Net P/L": net_pl,
        "Status": status_str
    }

# --- MAIN PAGE LOGIC ---
with Session(engine) as session:
    # 1. FETCH CAMPAIGNS
    wheel_strategies = session.exec(select(Strategy.id).where(col(Strategy.name).in_(["The Wheel", "Cash Secured Put", "Covered Call"]))).all()
    
    if not wheel_strategies:
        st.error("No compatible strategies found.")
        st.stop()
        
    campaigns = session.exec(select(Campaign).where(col(Campaign.strategy_id).in_(wheel_strategies)).order_by(Campaign.start_date.desc())).all()
    
    if not campaigns:
        st.info("No active campaigns found.")
        st.stop()

    # 2. BUILD SUMMARY TABLE
    table_data = []
    for camp in campaigns:
        table_data.append(analyze_wheel_stats(camp, session))
    
    df_summary = pd.DataFrame(table_data)
    
    # 3. SELECT CAMPAIGN
    # We use a radio button masked as a selector at the top
    col_list, col_deck = st.columns([2, 1])
    
    with col_list:
        st.subheader("📋 Active Wheels")
        
        # Display the High Level Table
        st.dataframe(
            df_summary.drop(columns=["id"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Adj Cost Basis": st.column_config.NumberColumn(format="$%.2f"),
                "Current Price": st.column_config.NumberColumn(format="$%.2f"),
                "Net P/L": st.column_config.NumberColumn(format="$%.2f"),
            }
        )

    with col_deck:
        st.subheader("🛠️ Trade Deck")
        # Selector
        camp_options = {c.name: c.id for c in campaigns}
        selected_camp_name = st.selectbox("Select Campaign to Manage", list(camp_options.keys()))
        selected_camp_id = camp_options[selected_camp_name]
        selected_camp = next(c for c in campaigns if c.id == selected_camp_id)
        
        # --- MANUAL ENTRY FORM ---
        with st.form("manual_entry_form"):
            st.caption(f"Log Trade for **{selected_camp.symbol}**")
            
            c1, c2 = st.columns(2)
            with c1:
                entry_side = st.selectbox("Side", ["SELL", "BUY"])
                entry_qty = st.number_input("Qty (Contracts/Shares)", min_value=1, value=1)
            with c2:
                entry_type = st.selectbox("Type", ["PUT", "CALL", "STOCK"])
                entry_price = st.number_input("Price", min_value=0.0, step=0.01, format="%.2f")

            # Option Specifics
            entry_strike = None
            entry_exp = None
            
            if entry_type != "STOCK":
                c3, c4 = st.columns(2)
                with c3:
                    entry_strike = st.number_input("Strike", min_value=0.0, step=0.5)
                with c4:
                    entry_exp = st.date_input("Expiration")

            submitted = st.form_submit_button("💾 Log Trade", type="primary")
            
            if submitted:
                # 1. Calculate Cash Amount
                # Stock: Price * Qty
                # Option: Price * Qty * 100
                multiplier = 100 if entry_type != "STOCK" else 1
                gross_amt = entry_price * entry_qty * multiplier
                
                # Logic: Sell = Credit (+), Buy = Debit (-)
                # If Side is SELL, amount is POSITIVE
                # If Side is BUY, amount is NEGATIVE
                cb_amount = gross_amt if entry_side == "SELL" else -gross_amt
                
                # Side Logic for DB (ToS uses "TO OPEN" / "TO CLOSE" usually, but simplistic here)
                db_side = f"{entry_side}_OPEN" # simplified, user can edit later
                
                # 2. Create Transaction
                new_trade = Transaction(
                    exec_date=date.today(),
                    exec_time=datetime.now().time(),
                    symbol=selected_camp.symbol,
                    qty=entry_qty if entry_side == "BUY" else -entry_qty, # DB stores short as neg
                    price=entry_price,
                    side=db_side,
                    option_type=entry_type if entry_type != "STOCK" else None,
                    strike=entry_strike,
                    exp_date=entry_exp,
                    cb_amount=cb_amount,
                    cb_description="Manual Entry",
                    transaction_type="TRADE",
                    campaign_id=selected_camp.id,
                    row_hash="TEMP" # Will generate real hash below
                )
                
                # Generate Hash
                trade_dict = new_trade.model_dump()
                trade_dict.pop('row_hash')
                new_trade.row_hash = generate_hash(trade_dict)
                
                try:
                    session.add(new_trade)
                    session.commit()
                    st.success("Trade Logged!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving: {e}")

    st.divider()

    # --- HISTORY SECTION ---
    if selected_camp:
        st.subheader(f"📜 History: {selected_camp.name}")
        
        hist_trades = session.exec(
            select(Transaction)
            .where(Transaction.campaign_id == selected_camp.id)
            .order_by(Transaction.exec_date.desc())
        ).all()
        
        if hist_trades:
            df_hist = pd.DataFrame([t.model_dump() for t in hist_trades])
            
            # Formatting for display
            display_cols = ['exec_date', 'side', 'qty', 'option_type', 'strike', 'exp_date', 'price', 'cb_amount']
            final_cols = [c for c in display_cols if c in df_hist.columns]
            
            st.dataframe(
                df_hist[final_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "exec_date": "Date",
                    "cb_amount": st.column_config.NumberColumn("Net Cash", format="$%.2f")
                }
            )
        else:
            st.info("No trade history for this campaign.")