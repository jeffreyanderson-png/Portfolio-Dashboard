import streamlit as st
from sqlmodel import Session, select
from src.models import Transaction
from src.utils import get_db_engine
from datetime import datetime
from src.models import Campaign

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

st.title("🗄️ Data Editor")
st.markdown("---")
st.write("Manual entry console for ledger adjustments, journaled shares, and non-API accounts (like Berkshire).")

with Session(engine) as session:
    # Fetch campaigns so you can assign manual trades to active buckets
    camps = session.exec(select(Campaign).where(Campaign.status == "Active")).all()
    camp_dict = {c.name: c.id for c in camps}
    camp_options = sorted(list(camp_dict.keys()))

    # Build the input form
    with st.form("manual_entry_form", clear_on_submit=True):
        st.subheader("Log New Transaction")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            exec_date = st.date_input("Execution Date", datetime.now().date())
            root_ticker = st.text_input("Ticker (e.g., BRK.B)").upper()
            asset_type = st.selectbox("Asset Type", ["EQUITY", "OPTION", "CASH", "FUTURE"])
            
        with col2:
            action = st.selectbox("Action", ["BUY", "SELL", "JOURNAL", "DIVIDEND", "ASSIGNMENT"])
            quantity = st.number_input("Quantity", value=0.0, format="%.4f")
            price = st.number_input("Price per Share", value=0.0, format="%.4f")
            
        with col3:
            # Reminder to make cash outflows negative
            amount = st.number_input("Net Amount (Cash Flow: Negative = Debit)", value=0.0, format="%.2f")
            target_camp = st.selectbox("Assign to Campaign", ["None"] + camp_options)
            broker = st.text_input("Broker/Account", value="Schwab - Berkshire")

        st.markdown("---")
        submit_button = st.form_submit_button("Log Transaction", type="primary")

        if submit_button:
            if not root_ticker:
                st.error("Ticker is required.")
            elif action in ["BUY", "SELL"] and amount == 0.0:
                st.warning("Did you forget to enter the Net Amount cash flow?")
            else:
                # Resolve the Campaign ID
                c_id = camp_dict.get(target_camp) if target_camp != "None" else None

                # Combine the date with the current time for the database timestamp
                exec_dt = datetime.combine(exec_date, datetime.now().time())

                # Create the record
                new_tx = Transaction(
                    exec_datetime=exec_dt,
                    broker=broker,
                    account_id=2, # Arbitrary ID for manual/Berkshire
                    root_ticker=root_ticker,
                    full_symbol=root_ticker, # Kept simple for manual entry
                    asset_type=asset_type,
                    action=action,
                    quantity=quantity,
                    price=price,
                    fees=0.0,
                    amount=amount,
                    campaign_id=c_id
                )
                session.add(new_tx)
                session.commit()
                
                st.success(f"✅ Successfully logged {action} of {quantity} {root_ticker}!")