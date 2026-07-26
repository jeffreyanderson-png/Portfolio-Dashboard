import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.models import Campaign, Transaction
from src.schwab_af_api import get_account_data
from src.utils import (
    parse_occ_expiration, get_days_to_expiration, parse_occ_type_and_strike, 
    get_db_engine, get_live_positions_dict, calculate_live_deployed_capital
)

engine = get_db_engine()

st.title("Portfolio Dashboard")
st.markdown("---")

# ==========================================
# 1. LIVE HUD METRICS & FETCH
# ==========================================
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.subheader("Live Account Balances")
with col_head2:
    from src.sync_engine import run_incremental_sync
    if st.button("🔄 Sync Recent Trades", use_container_width=True):
        with st.spinner("Syncing last 14 days..."):
            success, msg = run_incremental_sync(days_back=14)
            if success:
                st.success(msg)
            else:
                st.error(msg)

with st.spinner("Fetching live data from Schwab..."):
    try:
        acct_data = get_account_data()
        live_positions_dict = get_live_positions_dict(acct_data)
    except Exception:
        acct_data = None
        live_positions_dict = {}
    
if acct_data:
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
            if acct_type == 'MARGIN':
                margin_bal = balances.get('marginBalance', 0.0)
                if margin_bal < 0:
                    st.caption(f"Margin Used: :red[${abs(margin_bal):,.2f}]")
else:
    st.warning("Could not connect to Schwab API.")
    
st.markdown("---")

# ==========================================
# 2. RISK & ALLOCATION OVERVIEW
# ==========================================
col_alloc, col_risk = st.columns([3, 2])

with col_alloc:
    st.subheader("Strategy Allocation")
    
    with Session(engine) as session:
        alloc_data = []
        
        # Iterate over the live positions we hold RIGHT NOW
        for root_ticker, positions in live_positions_dict.items():
            deployed_capital = calculate_live_deployed_capital(positions)
            
            if deployed_capital > 0:
                # Look up the strategy from the database
                camp = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
                strategy = camp.strategy if camp and camp.strategy else "Unassigned"
                
                alloc_data.append({
                    "Strategy": strategy,
                    "Capital": deployed_capital
                })
        
        if alloc_data:
            df_alloc = pd.DataFrame(alloc_data)
            df_strat = df_alloc.groupby("Strategy", as_index=False)["Capital"].sum()
            df_strat["% of Total"] = (df_strat["Capital"] / df_strat["Capital"].sum()) * 100
            
            chart_col, table_col = st.columns([1, 1])
            with chart_col:
                try:
                    import plotly.express as px
                    fig = px.pie(df_strat, values='Capital', names='Strategy', hole=0.4)
                    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    fig.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True)
                except ImportError:
                    import altair as alt
                    chart = alt.Chart(df_strat).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Capital", type="quantitative"),
                        color=alt.Color(field="Strategy", type="nominal"),
                        tooltip=['Strategy', 'Capital', '% of Total']
                    )
                    st.altair_chart(chart, use_container_width=True)
                    
            with table_col:
                st.dataframe(
                    df_strat.sort_values(by="Capital", ascending=False),
                    column_config={
                        "Capital": st.column_config.NumberColumn(format="$%.2f"),
                        "% of Total": st.column_config.NumberColumn(format="%.1f%%")
                    },
                    hide_index=True,
                    use_container_width=True
                )
        else:
            st.info("No cash currently deployed in active campaigns.")

with col_risk:
    st.subheader("Put Risk Obligations")
    
    total_obligation = 0.0
    thirty_day_obligation = 0.0
    
    # Iterate purely over live, open positions
    for root_ticker, positions in live_positions_dict.items():
        for pos in positions:
            instr = pos.get('instrument', {})
            a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
            short_qty = pos.get('shortQuantity', 0)
            
            if a_type == 'OPTION' and short_qty > 0:
                sym = instr.get('symbol', '')
                opt_type, strike = parse_occ_type_and_strike(sym)
                
                if opt_type == 'P' and strike:
                    exp_date = parse_occ_expiration(sym)
                    dte = get_days_to_expiration(exp_date)
                    
                    if dte >= 0:
                        obligation = float(strike) * 100.0 * short_qty
                        total_obligation += obligation
                        if dte <= 30:
                            thirty_day_obligation += obligation
                            
    st.metric(label="30-Day Put Obligation", value=f"${thirty_day_obligation:,.2f}")
    st.metric(label="Total Put Obligation", value=f"${total_obligation:,.2f}")

# ==========================================
# 3. ACTIVE CAMPAIGN RADAR
# ==========================================
st.markdown("---")
st.subheader("Expiring Contracts Radar")

with Session(engine) as session:
    expiring_soon = []
    
    for root_ticker, positions in live_positions_dict.items():
        # Get campaign info quickly
        camp = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
        camp_name = camp.name if camp else root_ticker
        
        for pos in positions:
            instr = pos.get('instrument', {})
            a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
            
            if a_type == 'OPTION':
                sym = instr.get('symbol', '')
                long_qty = pos.get('longQuantity', 0)
                short_qty = pos.get('shortQuantity', 0)
                
                # Net quantity (positive if long, negative if short)
                net_qty = long_qty - short_qty
                
                if net_qty != 0:
                    exp_date = parse_occ_expiration(sym)
                    dte = get_days_to_expiration(exp_date)
                    
                    if dte >= 0:
                        expiring_soon.append({
                            "Campaign": camp_name,
                            "Symbol": sym,
                            "Qty": net_qty,
                            "DTE": dte,
                            "Expiration": exp_date.strftime("%Y-%m-%d") if exp_date else "Unknown"
                        })
    
    expiring_soon.sort(key=lambda x: x["DTE"])
    
    if not expiring_soon:
        st.success("No active options contracts found. The skies are clear!")
    else:
        urgent = [opt for opt in expiring_soon if opt["DTE"] <= 14]
        if urgent:
            st.error(f"⚠️ You have {len(urgent)} positions expiring in the next 14 days!")
        else:
            st.info(f"You have {len(expiring_soon)} open options contracts. None are expiring immediately.")
            
        st.dataframe(
            pd.DataFrame(expiring_soon),
            column_config={
                "Qty": st.column_config.NumberColumn(format="%.0f"),
                "DTE": st.column_config.ProgressColumn("Days to Exp", format="%d", min_value=0, max_value=60),
            },
            hide_index=True,
            use_container_width=True
        )