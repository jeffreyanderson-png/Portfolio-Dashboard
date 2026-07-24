import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.models import Campaign
from src.utils import parse_occ_expiration, get_days_to_expiration, parse_occ_type_and_strike, get_db_engine

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

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