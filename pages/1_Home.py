import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.models import Campaign#, Transaction
from src.schwab_af_api import get_account_data
from src.utils import (
    parse_occ_expiration, get_days_to_expiration, get_db_engine, get_live_positions_dict, calculate_live_deployed_capital, auto_classify_strategy#, parse_occ_type_and_strike
)

engine = get_db_engine()

st.title("Portfolio Dashboard")
st.markdown("---")

col_head1, col_head2 = st.columns([3, 1])
with col_head1: 
    st.subheader("Live Account Balances")
with col_head2:
    from src.sync_engine import run_incremental_sync
    if st.button("🔄 Sync Recent Trades", width='stretch'):
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
        audit_data = [] # For our diagnostic table
        
        for root_ticker, positions in live_positions_dict.items():
            deployed_capital = calculate_live_deployed_capital(positions)
            
            if deployed_capital > 0:
                camp = session.exec(select(Campaign).where(Campaign.name == root_ticker)).first()
                
                # AUTO-CLASSIFIER: If user hasn't set a specific strategy, use the context-aware default
                if camp and camp.strategy and camp.strategy != "Unassigned":
                    strategy = camp.strategy
                else:
                    strategy = auto_classify_strategy(positions)
                
                alloc_data.append({"Strategy": strategy, "Capital": deployed_capital})
                audit_data.append({"Ticker": root_ticker, "Auto-Strategy": auto_classify_strategy(positions), "Manual Override": camp.strategy if camp else "None", "Deployed Capital": deployed_capital})
        
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
                    st.plotly_chart(fig, width='stretch')
                except ImportError:
                    st.error("Please install plotly for charts")
                    
            with table_col:
                st.dataframe(df_strat.sort_values(by="Capital", ascending=False), column_config={"Capital": st.column_config.NumberColumn(format="$%.2f"), "% of Total": st.column_config.NumberColumn(format="%.1f%%")}, hide_index=True, width='stretch')
        else:
            st.info("No cash currently deployed.")

with col_risk:
    st.subheader("Expiring Contracts Radar")
    expiring_soon = []
    
    for root_ticker, positions in live_positions_dict.items():
        camp_name = root_ticker
        for pos in positions:
            instr = pos.get('instrument', {})
            if instr.get('assetType', instr.get('type', 'UNKNOWN')) == 'OPTION':
                sym = instr.get('symbol', '')
                net_qty = pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)
                
                if net_qty != 0:
                    exp_date = parse_occ_expiration(sym)
                    dte = get_days_to_expiration(exp_date)
                    if dte >= 0:
                        expiring_soon.append({"Campaign": camp_name, "Symbol": sym, "Qty": net_qty, "DTE": dte})
    
    expiring_soon.sort(key=lambda x: x["DTE"])
    
    if not expiring_soon:
        st.success("No active options contracts found.")
    else:
        st.dataframe(pd.DataFrame(expiring_soon), column_config={"Qty": st.column_config.NumberColumn(format="%.0f"), "DTE": st.column_config.ProgressColumn("Days to Exp", format="%d", min_value=0, max_value=60)}, hide_index=True, width='stretch')

# THE AUDIT TABLE
with st.expander("🕵️ Capital Deployed Audit (How is this calculated?)"):
    st.write("This table shows the exact math behind the capital deployed for each position, factoring in spreads to reduce naked risk.")
    if audit_data:
        st.dataframe(pd.DataFrame(audit_data).sort_values(by="Deployed Capital", ascending=False), column_config={"Deployed Capital": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, width='stretch')