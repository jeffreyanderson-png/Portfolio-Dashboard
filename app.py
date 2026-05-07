import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from sqlmodel import Session, select, create_engine, update
from src.models import Campaign, Transaction
from src.schwab_account_api import get_account_data
from src.utils import parse_occ_expiration, get_days_to_expiration, parse_occ_type_and_strike

# Ensure this matches your DB setup
DB_URL = "sqlite:///data/portfolio.db"
engine = create_engine(DB_URL)

st.set_page_config(page_title="Pilot Portfolio HUD", page_icon="✈️", layout="wide")

# --- NAVIGATION ---
st.sidebar.title("✈️ Flight Deck")
# Using a clean radio button for primary navigation
page = st.sidebar.radio("Navigation", [
    "Dashboard", 
    "Campaigns", 
    "Wheel Tracker", 
    "Advanced Options Radar",
    "401k Allocation", 
    "Data Editor", 
    "Settings"
])

# --- PAGE: DASHBOARD ---
if page == "Dashboard":
    st.title("Portfolio Dashboard")
    st.markdown("---")
    
    # 1. LIVE HUD METRICS (Schwab API)
    st.subheader("Live Account Balances")
    
    with st.spinner("Fetching live data from Schwab..."):
        acct_data = get_account_data()
        
    if acct_data:
        # Create columns based on the number of accounts found
        cols = st.columns(len(acct_data))
        
        for i, acct in enumerate(acct_data):
            info = acct.get('securitiesAccount', {})
            acct_type = info.get('type', 'Unknown')
            balances = info.get('currentBalances', {})
            
            net_liq = balances.get('liquidationValue', 0.0)
            cash = balances.get('cashBalance', balances.get('cashAvailableForTrading', 0.0))
            
            with cols[i]:
                st.metric(label=f"{acct_type} Account", value=f"${net_liq:,.2f}")
                st.caption(f"Cash Available: ${cash:,.2f}")
                
                # If margin, show margin balances
                if acct_type == 'MARGIN':
                    margin_bal = balances.get('marginBalance', 0.0)
                    if margin_bal < 0: # Schwab usually represents borrowed money as negative
                        st.caption(f"Margin Used: :red[${abs(margin_bal):,.2f}]")
    else:
        st.warning("Could not connect to Schwab API. Displaying cached database values.")
        
    st.markdown("---")
    
    # 2. ACTIVE CAMPAIGN RADAR (Database)
    st.subheader("Active Campaign Radar")
    
    with Session(engine) as session:
        # Pull every option transaction in the ledger
        option_txs = session.exec(
            select(Transaction).where(Transaction.asset_type == "OPTION")
        ).all()
        
        # Calculate net open positions by summing quantities
        open_positions = {}
        for tx in option_txs:
            sym = tx.full_symbol
            if sym not in open_positions:
                open_positions[sym] = {
                    "qty": 0.0, 
                    "campaign": tx.campaign.name if tx.campaign else "Unassigned",
                    "root": tx.root_ticker
                }
            open_positions[sym]["qty"] += tx.quantity
            
        # Filter out closed positions (qty == 0) and parse dates
        expiring_soon = []
        for sym, data in open_positions.items():
            # Rounding to handle floating point math quirks (e.g., 0.000000001)
            if round(data["qty"], 2) != 0:
                exp_date = parse_occ_expiration(sym)
                dte = get_days_to_expiration(exp_date)
                
                expiring_soon.append({
                    "Campaign": data["campaign"],
                    "Symbol": sym,
                    "Qty": data["qty"],
                    "DTE": dte,
                    "Expiration": exp_date.strftime("%Y-%m-%d") if exp_date else "Unknown"
                })
        
        # Sort by Days to Expiration (closest first)
        expiring_soon.sort(key=lambda x: x["DTE"])
        
        # Display the Radar
        if not expiring_soon:
            st.success("No active options contracts found. The skies are clear!")
        else:
            # Highlight items expiring within the next 14 days
            urgent = [opt for opt in expiring_soon if opt["DTE"] <= 14]
            
            if urgent:
                st.error(f"⚠️ You have {len(urgent)} positions expiring in the next 14 days!")
            else:
                st.info(f"You have {len(expiring_soon)} open options contracts. None are expiring immediately.")
                
            # Render a clean dataframe of all open options
            df_options = pd.DataFrame(expiring_soon)
            
            # Formatting the display dataframe
            st.dataframe(
                df_options,
                column_config={
                    "Qty": st.column_config.NumberColumn(format="%.0f"),
                    "DTE": st.column_config.ProgressColumn(
                        "Days to Exp",
                        help="Days until the contract expires",
                        format="%d",
                        min_value=0,
                        max_value=60, # Caps the progress bar visually at 60 days
                    ),
                },
                hide_index=True,
                use_container_width=True
            )   

# --- PLACEHOLDERS FOR OTHER PAGES ---
elif page == "Campaigns":
    st.title("Campaign Manager")
    st.markdown("---")
    
    # ADDED THE 4TH TAB HERE
    tab1, tab2, tab3, tab4 = st.tabs(["Active Campaigns", "Merge Campaigns", "Assign Strategies", "Split & Reassign"])
    
    with tab1:
        st.subheader("Campaign Ledger")
        with Session(engine) as session:
            campaigns = session.exec(select(Campaign).where(Campaign.status == "Active")).all()
            if campaigns:
                camp_names = sorted([c.name for c in campaigns])
                selected_camp = st.selectbox("Select a Campaign to inspect:", camp_names)
                
                if selected_camp:
                    camp = session.exec(select(Campaign).where(Campaign.name == selected_camp)).first()
                    st.write(f"**Strategy:** {camp.strategy} | **Start Date:** {camp.start_date} | **Total Transactions:** {len(camp.transactions)}")
                    
                    if camp.transactions:
                        tx_data = [{
                            "Date": tx.exec_datetime.strftime("%Y-%m-%d"),
                            "Type": tx.asset_type,
                            "Action": tx.action,
                            "Symbol": tx.full_symbol,
                            "Qty": tx.quantity,
                            "Price": tx.price,
                            "Amount": tx.amount
                        } for tx in camp.transactions]
                        st.dataframe(pd.DataFrame(tx_data), hide_index=True, use_container_width=True)
            else:
                st.info("No active campaigns found.")

    with tab2:
        st.subheader("Merge Campaigns")
        with Session(engine) as session:
            all_camps = session.exec(select(Campaign)).all()
            camp_options = sorted([c.name for c in all_camps])
            merge_selection = st.multiselect("1. Select Campaigns to Merge:", options=camp_options)
            new_name = st.text_input("2. New Unified Campaign Name:")
            
            if st.button("Execute Merge", type="primary"):
                if len(merge_selection) > 1 and new_name:
                    new_camp = Campaign(name=new_name, start_date=datetime.now().date())
                    session.add(new_camp)
                    session.commit()
                    session.refresh(new_camp) 
                    
                    old_camps = session.exec(select(Campaign).where(Campaign.name.in_(merge_selection))).all()
                    old_camp_ids = [c.id for c in old_camps]
                    
                    session.exec(update(Transaction).where(Transaction.campaign_id.in_(old_camp_ids)).values(campaign_id=new_camp.id))
                        
                    for old_camp in old_camps:
                        session.delete(old_camp)
                        
                    session.commit()
                    st.success(f"✅ Merged successfully into '{new_name}'!")
                    st.rerun()
                else:
                    st.warning("Select at least two campaigns and provide a name.")

    with tab3:
        st.subheader("Tag Campaign Strategies")
        st.write("Assign strategies to filter them onto the correct tracking dashboards.")
        with Session(engine) as session:
            camps_to_tag = session.exec(select(Campaign).where(Campaign.status == "Active")).all()
            if camps_to_tag:
                tag_col1, tag_col2 = st.columns([2, 1])
                with tag_col1:
                    camps_selected = st.multiselect("Select Campaigns:", sorted([c.name for c in camps_to_tag]))
                with tag_col2:
                    new_strategy = st.selectbox("Assign Strategy:", ["Wheel", "LEAP", "Calendar", "Spread", "Long Hold", "Unassigned"])
                
                if st.button("Update Strategy", type="primary") and camps_selected:
                    for c_name in camps_selected:
                        camp_obj = session.exec(select(Campaign).where(Campaign.name == c_name)).first()
                        camp_obj.strategy = new_strategy
                        session.add(camp_obj)
                    session.commit()
                    st.success("✅ Strategies updated!")
                    st.rerun()

    # --- NEW SPLIT & REASSIGN ENGINE ---
    with tab4:
        st.subheader("Surgical Trade Splitter")
        st.write("Select specific trades (like LEAPs or long-term holds) and kick them into a new campaign.")
        
        with Session(engine) as session:
            active_camps = session.exec(select(Campaign).where(Campaign.status == "Active")).all()
            if active_camps:
                camp_names = sorted([c.name for c in active_camps])
                
                col1, col2 = st.columns(2)
                with col1:
                    source_name = st.selectbox("1. Select Source Campaign:", camp_names)
                with col2:
                    dest_input = st.text_input("2. Destination Campaign Name:", placeholder="e.g., ASTS LEAPs")
                    
                if source_name:
                    source_camp = session.exec(select(Campaign).where(Campaign.name == source_name)).first()
                    
                    # Build the data dictionary for the interactive editor
                    tx_list = []
                    for tx in source_camp.transactions:
                        tx_list.append({
                            "Move": False, # This becomes our checkbox
                            "ID": tx.id,
                            "Date": tx.exec_datetime.strftime("%Y-%m-%d"),
                            "Action": tx.action,
                            "Qty": tx.quantity,
                            "Symbol": tx.full_symbol,
                            "Amount": tx.amount
                        })
                        
                    if tx_list:
                        st.write("**3. Select the exact trades to evict:**")
                        df_tx = pd.DataFrame(tx_list)
                        
                        # Streamlit's native interactive dataframe!
                        edited_df = st.data_editor(
                            df_tx,
                            hide_index=True,
                            column_config={
                                "Move": st.column_config.CheckboxColumn("Select", default=False),
                                "ID": None, # Hide the ugly database ID from the UI
                                "Amount": st.column_config.NumberColumn(format="$%.2f")
                            },
                            disabled=["Date", "Action", "Qty", "Symbol", "Amount"], # Lock everything except the checkbox
                            use_container_width=True
                        )
                        
                        # Extract the IDs of only the rows the user checked
                        selected_ids = edited_df[edited_df["Move"] == True]["ID"].tolist()
                        
                        if st.button("Move Selected Trades", type="primary"):
                            if not dest_input:
                                st.warning("Please type a name for the Destination Campaign.")
                            elif not selected_ids:
                                st.warning("Check at least one box to move a trade.")
                            elif dest_input == source_name:
                                st.warning("You can't move trades into the exact same campaign!")
                            else:
                                # If the destination doesn't exist yet, build it dynamically!
                                dest_camp = session.exec(select(Campaign).where(Campaign.name == dest_input)).first()
                                if not dest_camp:
                                    dest_camp = Campaign(
                                        name=dest_input, 
                                        start_date=datetime.now().date(), 
                                        strategy="Unassigned" # You can tag it as 'LEAP' later in Tab 3
                                    )
                                    session.add(dest_camp)
                                    session.commit()
                                    session.refresh(dest_camp)
                                
                                # Execute the bulk SQL update to swap the campaign IDs
                                session.exec(
                                    update(Transaction)
                                    .where(Transaction.id.in_(selected_ids))
                                    .values(campaign_id=dest_camp.id)
                                )
                                session.commit()
                                st.success(f"✅ Teleported {len(selected_ids)} trades into '{dest_input}'!")
                                st.rerun()

elif page == "Wheel Tracker":
    st.title("⚙️ The Wheel Tracker")
    st.markdown("---")
    
    with Session(engine) as session:
        # ONLY fetch campaigns explicitly tagged as "Wheel"
        wheel_camps = session.exec(
            select(Campaign).where(Campaign.status == "Active").where(Campaign.strategy == "Wheel")
        ).all()
        
        if not wheel_camps:
            st.warning("No campaigns are tagged as 'Wheel'. Go to the Campaign Manager -> Assign Strategies tab to tag them!")
        else:
            wheel_data = []
            
            for camp in wheel_camps:
                shares = 0.0
                total_equity_cost = 0.0
                total_premium = 0.0
                open_puts = 0
                open_calls = 0
                option_inventory = {} 
                
                for tx in camp.transactions:
                    if tx.asset_type == 'EQUITY':
                        shares += tx.quantity
                        # Calculate raw money spent on shares (Buys and Assignments)
                        if tx.action in ['BUY', 'ASSIGNMENT'] or tx.quantity > 0:
                            total_equity_cost += (abs(tx.quantity) * tx.price)
                        # Subtract cost if shares are sold or called away
                        elif tx.action in ['SELL'] or tx.quantity < 0:
                            total_equity_cost -= (abs(tx.quantity) * tx.price)
                            
                    elif tx.asset_type == 'OPTION':
                        # INVERTING THE MATH: Cash in is now Positive
                        total_premium += tx.amount 
                        
                        sym = tx.full_symbol
                        option_inventory[sym] = option_inventory.get(sym, 0) + tx.quantity

                for sym, qty in option_inventory.items():
                    if round(qty, 2) != 0: 
                        opt_type, _ = parse_occ_type_and_strike(sym)
                        exp_date = parse_occ_expiration(sym)
                        dte = get_days_to_expiration(exp_date)
                        
                        # THE GHOST BUSTER: If it's expired, it died worthless. Skip it.
                        if dte < 0:
                            continue
                            
                        if opt_type == 'P':
                            open_puts += abs(qty) 
                        elif opt_type == 'C':
                            open_calls += abs(qty)

                # Adjusted Math for Clean Display
                avg_cost_per_share = (total_equity_cost / shares) if shares > 0 else 0.0
                # Basis minus the cash we collected
                adj_basis_per_share = ((total_equity_cost - total_premium) / shares) if shares > 0 else 0.0

                wheel_data.append({
                    "Campaign": camp.name,
                    "Shares": shares,
                    "Open Puts": open_puts,
                    "Open Calls": open_calls,
                    "Total Premium": total_premium,
                    "Avg Cost/Share": avg_cost_per_share,
                    "Adj Basis": adj_basis_per_share
                })

            st.subheader("Active Wheel Matrix")
            st.dataframe(
                pd.DataFrame(wheel_data),
                column_config={
                    "Shares": st.column_config.NumberColumn(format="%.0f"),
                    "Open Puts": st.column_config.NumberColumn(format="%.0f"),
                    "Open Calls": st.column_config.NumberColumn(format="%.0f"),
                    "Total Premium": st.column_config.NumberColumn(format="$%.2f"),
                    "Avg Cost/Share": st.column_config.NumberColumn(format="$%.2f"),
                    "Adj Basis": st.column_config.NumberColumn(format="$%.2f")
                },
                hide_index=True,
                use_container_width=True
            )
            
            st.markdown("---")
            st.subheader("Campaign Deep Dive")
            selected_wheel = st.selectbox("Inspect specific wheel mechanics:", [c.name for c in wheel_camps])
            
            if selected_wheel:
                target_camp = next(c for c in wheel_camps if c.name == selected_wheel)
                st.write("**Currently Open Option Legs:**")
                open_legs = []
                inventory = {}
                for tx in target_camp.transactions:
                    if tx.asset_type == 'OPTION':
                        inventory[tx.full_symbol] = inventory.get(tx.full_symbol, 0) + tx.quantity
                        
                for sym, qty in inventory.items():
                    if round(qty, 2) != 0:
                        opt_type, strike = parse_occ_type_and_strike(sym)
                        exp_date = parse_occ_expiration(sym)
                        dte = get_days_to_expiration(exp_date)
                        
                        # GHOST BUSTER APPLIED TO DETAIL VIEW TOO
                        if dte < 0:
                            continue
                            
                        open_legs.append({
                            "Type": "Short Put" if opt_type == 'P' and qty < 0 else "Short Call" if opt_type == 'C' and qty < 0 else "Long Option",
                            "Strike": strike,
                            "Expiration": exp_date.strftime("%Y-%m-%d") if exp_date else "Unknown",
                            "DTE": dte,
                            "Qty": abs(qty)
                        })
                
                if open_legs:
                    st.table(pd.DataFrame(open_legs).sort_values(by="DTE"))
                else:
                    st.info("No open option legs for this campaign.")

elif page == "401k Allocation":
    st.title("401k Allocation")
    st.info("Rebalancing engine and target tracking.")

# --- NEW ADVANCED RADAR PAGE ---
elif page == "Advanced Options Radar":
    st.title("📡 Advanced Options Radar")
    st.markdown("---")
    
    with Session(engine) as session:
        # Fetch Active campaigns that are NOT Wheels and NOT Unassigned
        adv_camps = session.exec(
            select(Campaign)
            .where(Campaign.status == "Active")
            .where(Campaign.strategy.in_(["LEAP", "Calendar", "Spread", "Long Hold"]))
        ).all()
        
        if not adv_camps:
            st.info("No advanced strategies found. Tag a campaign in the Campaign Manager to see it here.")
        else:
            radar_data = []
            
            for camp in adv_camps:
                capital_deployed = 0.0
                realized_cash = 0.0
                open_inventory = {}
                
                for tx in camp.transactions:
                    if tx.asset_type in ['EQUITY', 'OPTION']:
                        # Track total cash flow
                        if tx.action in ['BUY', 'ASSIGNMENT'] or tx.quantity > 0:
                            capital_deployed += (abs(tx.quantity) * tx.price * (100 if tx.asset_type == 'OPTION' else 1))
                        else:
                            realized_cash += (abs(tx.quantity) * tx.price * (100 if tx.asset_type == 'OPTION' else 1))
                            
                        # Track open legs
                        sym = tx.full_symbol
                        open_inventory[sym] = open_inventory.get(sym, 0) + tx.quantity

                # Format the open legs for display
                active_legs = []
                for sym, qty in open_inventory.items():
                    if round(qty, 2) != 0:
                        exp_date = parse_occ_expiration(sym)
                        dte = get_days_to_expiration(exp_date) if exp_date else "N/A"
                        
                        # Only show DTE for actual options, not shares
                        if dte != "N/A" and dte < 0:
                            continue # Ghost buster
                            
                        active_legs.append(f"{sym} ({qty})")

                net_cost = capital_deployed - realized_cash

                radar_data.append({
                    "Campaign": camp.name,
                    "Strategy": camp.strategy,
                    "Net Capital Deployed": net_cost,
                    "Open Legs": ", ".join(active_legs) if active_legs else "None"
                })

            st.subheader("Tactical Overview")
            st.dataframe(
                pd.DataFrame(radar_data),
                column_config={
                    "Net Capital Deployed": st.column_config.NumberColumn(format="$%.2f")
                },
                hide_index=True,
                use_container_width=True
            )
            
            st.markdown("---")
            st.subheader("Position Inspector")
            selected_camp = st.selectbox("Inspect Strategy Details:", [c.name for c in adv_camps])
            
            if selected_camp:
                target = next(c for c in adv_camps if c.name == selected_camp)
                
                details = []
                inventory = {}
                for tx in target.transactions:
                    inventory[tx.full_symbol] = inventory.get(tx.full_symbol, 0) + tx.quantity
                        
                for sym, qty in inventory.items():
                    if round(qty, 2) != 0:
                        opt_type, strike = parse_occ_type_and_strike(sym)
                        exp_date = parse_occ_expiration(sym)
                        dte = get_days_to_expiration(exp_date)
                        
                        if exp_date and dte < 0:
                            continue
                            
                        details.append({
                            "Asset": sym,
                            "Type": "Equity" if not exp_date else ("Call" if opt_type == 'C' else "Put"),
                            "Strike": strike if strike else "N/A",
                            "Expiration": exp_date.strftime("%Y-%m-%d") if exp_date else "N/A",
                            "DTE": dte if exp_date else "N/A",
                            "Qty": qty
                        })
                
                if details:
                    st.table(pd.DataFrame(details).sort_values(by=["Asset"]))

elif page == "Data Editor":
    st.title("Database Admin Console")
    st.info("Manual ledger entries and corrections will go here.")

elif page == "Settings":
    st.title("Global Settings")
    st.info("App configuration and API token management.")
