import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

st.set_page_config(page_title="401k Allocation", layout="wide")

# --- MATH ENGINES ---

def calculate_bond_allocation(slider_val):
    """Interpolates bond allocations across a 0-100 duration slider."""
    x_points = [0, 25, 50, 75, 100]
    tips_y = [50.0, 25.0, 10.0,  0.0,  0.0]
    stb_y  = [40.0, 50.0, 40.0, 20.0,  0.0]
    itb_y  = [10.0, 20.0, 35.0, 60.0, 70.0]
    reit_y = [ 0.0,  5.0, 15.0, 20.0, 30.0]
    
    tips_pct = np.interp(slider_val, x_points, tips_y) / 100.0
    stb_pct = np.interp(slider_val, x_points, stb_y) / 100.0
    itb_pct = np.interp(slider_val, x_points, itb_y) / 100.0
    reit_pct = np.interp(slider_val, x_points, reit_y) / 100.0
    
    total = tips_pct + stb_pct + itb_pct + reit_pct
    return tips_pct/total, stb_pct/total, itb_pct/total, reit_pct/total

def generate_target_dict(equity_pct, bond_pct, commodity_pct, cash_pct, us_pct, small_pct, value_pct, bond_duration):
    """Translates macro parameters into specific asset class targets."""
    targets = {}
    e_weight, b_weight, c_weight = equity_pct / 100.0, bond_pct / 100.0, commodity_pct / 100.0
    
    # Equities
    em_weight = e_weight * (1.0 / 9.0)
    core_e_weight = e_weight * (8.0 / 9.0)
    us_w, intl_w = us_pct / 100.0, 1.0 - (us_pct / 100.0)
    small_w, large_w = small_pct / 100.0, 1.0 - (small_pct / 100.0)
    value_w, blend_w = value_pct / 100.0, 1.0 - (value_pct / 100.0)
    
    targets['US LCB'] = core_e_weight * (us_w * large_w * blend_w)
    targets['US LCV'] = core_e_weight * (us_w * large_w * value_w)
    targets['US SCB'] = core_e_weight * (us_w * small_w * blend_w)
    targets['US SCV'] = core_e_weight * (us_w * small_w * value_w)
    targets['I LCB'] = core_e_weight * (intl_w * large_w * blend_w)
    targets['I LCV'] = core_e_weight * (intl_w * large_w * value_w)
    targets['I SCB'] = core_e_weight * (intl_w * small_w * blend_w)
    targets['I SCV'] = core_e_weight * (intl_w * small_w * value_w)
    targets['EM'] = em_weight
    
    # Bonds
    tips_w, stb_w, itb_w, reit_w = calculate_bond_allocation(bond_duration)
    targets['TIPS'] = b_weight * tips_w
    targets['STB'] = b_weight * stb_w
    targets['ITB'] = b_weight * itb_w
    targets['US REIT'] = b_weight * reit_w
    
    # Commodities & Cash
    targets['Commodities'] = c_weight * 0.80
    targets['Gold'] = c_weight * 0.20
    targets['Cash'] = cash_pct / 100.0
    
    return targets

def calculate_rebalance(df_tickers, class_targets, new_contribution):
    """Executes the distribution logic while respecting Action Tags."""
    account_cols = ["Trad 401k", "Roth 401k", "Roth IRA"]
    df_tickers['Total Shares'] = df_tickers[account_cols].sum(axis=1)
    df_tickers['Current $'] = df_tickers['Total Shares'] * df_tickers['Open Price']
    
    total_portfolio_value = df_tickers['Current $'].sum() + new_contribution
    df_tickers['Target $'] = 0.0
    
    for asset_class, group in df_tickers.groupby('Asset Class'):
        target_pct = class_targets.get(asset_class, 0.0)
        class_target_dollars = total_portfolio_value * target_pct
        
        buy_tickers = group[group['Action Tag'] == 'Buy']
        hold_tickers = group[group['Action Tag'] == 'Hold']
        sell_tickers = group[group['Action Tag'] == 'Sell']
        
        # Process Tags
        df_tickers.loc[sell_tickers.index, 'Target $'] = 0.0
        hold_value = hold_tickers['Current $'].sum()
        df_tickers.loc[hold_tickers.index, 'Target $'] = hold_tickers['Current $']
        
        remaining_target_dollars = class_target_dollars - hold_value
        
        if not buy_tickers.empty:
            if remaining_target_dollars > 0:
                dollars_per_buy = remaining_target_dollars / len(buy_tickers)
                df_tickers.loc[buy_tickers.index, 'Target $'] = dollars_per_buy
            else:
                df_tickers.loc[buy_tickers.index, 'Target $'] = 0.0
                
    df_tickers['Difference $'] = df_tickers['Target $'] - df_tickers['Current $']
    df_tickers['Share Adj'] = np.where(df_tickers['Open Price'] > 0, (df_tickers['Difference $'] / df_tickers['Open Price']).round(0), 0)
    
    # Calculate Drift (Current Weight vs Target Weight)
    df_tickers['Current Weight'] = df_tickers['Current $'] / total_portfolio_value
    df_tickers['Target Weight'] = df_tickers['Target $'] / total_portfolio_value
    df_tickers['Drift %'] = df_tickers['Current Weight'] - df_tickers['Target Weight']
    
    output_cols = ['Ticker', 'Asset Class', 'Action Tag', 'Current $', 'Target $', 'Difference $', 'Share Adj', 'Drift %']
    return df_tickers[output_cols]

# --- UI LAYOUT ---

st.title("🎯 401k Target Allocation")

# Inputs
col_cash, col_btn = st.columns([1, 1])
with col_cash:
    new_contribution = st.number_input("New Contribution ($) - e.g., Bi-weekly Paycheck", min_value=0.0, value=0.0, step=100.0)
with col_btn:
    st.write("") # Spacing
    if st.button("Mark as Rebalanced\n(Last: 2026-01-01)"): # Replace with DB lookup
        st.success("Rebalance recorded.")

st.divider()

st.header("Macro Asset Allocation")
col1, col2, col3, col4 = st.columns(4)
with col1: equity_pct = st.number_input("Equities (%)", min_value=0.0, max_value=100.0, value=60.0, step=1.0)
with col2: bond_pct = st.number_input("Bonds (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0)
with col3: commodity_pct = st.number_input("Commodities (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)
with col4:
    cash_pct = 100.0 - (equity_pct + bond_pct + commodity_pct)
    if cash_pct < 0: st.error(f"Cash: {cash_pct:.1f}% (Exceeds 100%)")
    else: st.metric("Cash (%)", f"{cash_pct:.1f}%")

st.header("Geographic & Style Tilts")
col_eq1, col_eq2, col_eq3, col_eq4 = st.columns(4)
with col_eq1: us_pct = st.slider("US (%)", min_value=0, max_value=100, value=50, step=1)
with col_eq2: small_pct = st.slider("Small Cap Tilt (%)", min_value=0, max_value=100, value=50, step=1)
with col_eq3: value_pct = st.slider("Value Tilt (%)", min_value=0, max_value=100, value=50, step=1)
with col_eq4: bond_duration = st.slider("Bond Duration (0=Short, 100=Long)", min_value=0, max_value=100, value=25, step=1)

st.divider()

st.subheader("Ticker Management & Balances")

# Initial Data (Replace with Pandas pivot from your SQL DB)
data = {
    "Ticker": ["AVUV", "AVUS", "AVDE", "VGSH", "SPAXX"],
    "Asset Class": ["US SCV", "US LCB", "I LCB", "STB", "Cash"],
    "Action Tag": ["Buy", "Hold", "Sell", "Buy", "Hold"],
    "Open Price": [119.52, 120.73, 88.01, 58.47, 1.00],
    "Trad 401k": [554.0, 526.9, 12.0, 164.4, 0.0],
    "Roth 401k": [0.0, 34.0, 686.9, 10.0, 5000.0],
    "Roth IRA": [0.0, 0.0, 0.0, 0.0, 0.0]
}
df_tickers = pd.DataFrame(data)

edited_df = st.data_editor(
    df_tickers,
    column_config={
        "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
        "Asset Class": st.column_config.TextColumn("Asset Class", disabled=True),
        "Action Tag": st.column_config.SelectboxColumn("Action", options=["Buy", "Hold", "Sell"], required=True),
        "Open Price": st.column_config.NumberColumn("Open Price ($)", format="$%.2f"),
        "Trad 401k": st.column_config.NumberColumn("Trad 401k Shares", step=1),
        "Roth 401k": st.column_config.NumberColumn("Roth 401k Shares", step=1),
        "Roth IRA": st.column_config.NumberColumn("Roth IRA Shares", step=1)
    },
    hide_index=True,
    use_container_width=True
)

st.divider()

st.subheader("Actionable Adjustments")

# Run the engines
targets = generate_target_dict(equity_pct, bond_pct, commodity_pct, cash_pct, us_pct, small_pct, value_pct, bond_duration)
results_df = calculate_rebalance(edited_df, targets, new_contribution)

# Highlight Drift function
def highlight_drift(val):
    if val > 0.05 or val < -0.05:
        return 'background-color: rgba(255, 75, 75, 0.2); color: #ff4b4b;'
    return ''

# Format output for clean display
styled_results = results_df.style\
    .format({'Current $': '${:,.2f}', 'Target $': '${:,.2f}', 'Difference $': '${:,.2f}', 'Drift %': '{:.2%}'})\
    .map(highlight_drift, subset=['Drift %'])

st.dataframe(styled_results, hide_index=True, use_container_width=True)
