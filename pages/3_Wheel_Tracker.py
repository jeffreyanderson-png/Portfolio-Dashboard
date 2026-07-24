import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.utils import parse_occ_expiration, get_days_to_expiration, parse_occ_type_and_strike, get_db_engine
from src.models import Campaign

st.title("Portfolio Dashboard")
st.markdown("---")

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

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
            total_equity_cash = 0.0
            total_premium = 0.0
            open_puts = 0
            open_calls = 0
            option_inventory = {} 
            
            for tx in camp.transactions:
                # 1. Enforce strict cash flow direction on the raw amount (capturing exact Schwab fees)
                if 'BUY' in tx.action or tx.action == 'ASSIGNMENT':
                    actual_cash = -abs(tx.amount)
                elif 'SELL' in tx.action:
                    actual_cash = abs(tx.amount)
                else:
                    actual_cash = -abs(tx.amount) if tx.quantity > 0 else abs(tx.amount)
                    
                if tx.asset_type == 'EQUITY':
                    shares += tx.quantity
                    total_equity_cash += actual_cash
                        
                elif tx.asset_type == 'OPTION':
                    total_premium += actual_cash 
                    
                    sym = tx.full_symbol
                    option_inventory[sym] = option_inventory.get(sym, 0) + tx.quantity

            for sym, qty in option_inventory.items():
                if round(qty, 2) != 0: 
                    opt_type, _ = parse_occ_type_and_strike(sym)
                    exp_date = parse_occ_expiration(sym)
                    dte = get_days_to_expiration(exp_date)
                    
                    if dte < 0:
                        continue
                        
                    if opt_type == 'P':
                        open_puts += abs(qty) 
                    elif opt_type == 'C':
                        open_calls += abs(qty)

            # Math for Clean Display
            avg_cost_per_share = abs(total_equity_cash) / shares if shares > 0 else 0.0
            
            # Net Cash Flow = Equity Cash (Negative Debits) + Premium (Positive Credits)
            net_cash = total_equity_cash + total_premium
            adj_basis_per_share = -(net_cash / shares) if shares > 0 else 0.0

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
                "Avg Cost/Share": st.column_config.NumberColumn("Unadj Basis (Schwab)", format="$%.2f"),
                "Adj Basis": st.column_config.NumberColumn("True Breakeven (Adj)", format="$%.2f")
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