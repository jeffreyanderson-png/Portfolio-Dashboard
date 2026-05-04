import streamlit as st
import pandas as pd
from datetime import date
# from sqlmodel import Session, select
# from src.models import RebalanceLog

# --- REBALANCE TRACKING BUTTON ---
st.header("Actionable Adjustments")

# Placeholder for DB query: latest_log = session.exec(select(RebalanceLog).order_by(RebalanceLog.rebalance_date.desc())).first()
last_rebalance_date = "2026-01-01" # Replace with latest_log.rebalance_date

col_btn, col_warn = st.columns([1, 3])
with col_btn:
    if st.button(f"Mark as Rebalanced\n(Last: {last_rebalance_date})"):
        # new_log = RebalanceLog(rebalance_date=date.today())
        # session.add(new_log)
        # session.commit()
        st.success("Rebalance recorded.")
        st.rerun()

# --- UNIFIED TICKER & POSITION EDITOR ---
st.subheader("Ticker Management & Balances")
st.write("Update Open Prices manually, adjust action tags, or update share counts across accounts.")

# Placeholder data simulating a pivot from your database tables
data = {
    "Ticker": ["AVUV", "AVUS", "AVDE", "VGSH"],
    "Asset Class": ["US SCV", "US LCB", "I LCB", "STB"],
    "Action Tag": ["Buy", "Hold", "Sell", "Buy"],
    "Open Price": [119.52, 120.73, 88.01, 58.47],
    "Trad 401k": [554.0, 526.9, 12.0, 164.4],
    "Roth 401k": [0.0, 34.0, 686.9, 10.0],
    "Roth IRA": [0.0, 0.0, 0.0, 0.0]
}
df_tickers = pd.DataFrame(data)

# Render the interactive data editor
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