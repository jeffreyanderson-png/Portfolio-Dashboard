import streamlit as st
from sqlmodel import Session, select
from src.models import Transaction
from src.schwab_af_api import get_account_data
from src.utils import parse_occ_expiration, get_days_to_expiration, parse_occ_type_and_strike, get_db_engine

st.title("Portfolio Dashboard")
st.markdown("---")

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

# 1. LIVE HUD METRICS (Schwab API)
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
    except Exception:
        acct_data = None
    
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
    st.warning("Could not connect to Schwab API. Displaying cached database values.")
    
st.markdown("---")

# 2. RISK MANAGEMENT: PUT OBLIGATIONS (Database)
st.subheader("Put Risk Obligations")

with Session(engine) as session:
    # Pull every option transaction in the ledger
    option_txs = session.exec(
        select(Transaction).where(Transaction.asset_type == "OPTION")
    ).all()
    
    # Calculate net open positions by summing quantities
    open_positions = {}
    for tx in option_txs:
        sym = tx.full_symbol
        open_positions[sym] = open_positions.get(sym, 0.0) + tx.quantity
        
    total_obligation = 0.0
    thirty_day_obligation = 0.0
    
    for sym, qty in open_positions.items():
        # A negative quantity means we are SHORT the option
        if round(qty, 2) < 0:
            opt_type, strike = parse_occ_type_and_strike(sym)
            
            # Only calculate risk for PUTS (obligation to buy shares)
            if opt_type == 'P' and strike:
                exp_date = parse_occ_expiration(sym)
                dte = get_days_to_expiration(exp_date)
                
                if dte >= 0:
                    # Calculation: (Strike Price) * (100 shares per contract) * (Absolute value of contracts short)
                    obligation = float(strike) * 100.0 * abs(qty)
                    total_obligation += obligation
                    
                    if dte <= 30:
                        thirty_day_obligation += obligation
                        
    # Display the Risk Metrics side-by-side
    col_risk1, col_risk2 = st.columns(2)
    with col_risk1:
        st.metric(
            label="30-Day Put Obligation", 
            value=f"${thirty_day_obligation:,.2f}",
            help="Total cash required if all short puts expiring in the next 30 days are assigned."
        )
    with col_risk2:
        st.metric(
            label="Total Put Obligation", 
            value=f"${total_obligation:,.2f}",
            help="Total cash required if every single short put currently open is assigned."
        )