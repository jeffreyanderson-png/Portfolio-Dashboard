import streamlit as st
import pandas as pd
from datetime import datetime
from sqlmodel import Session, select, update
from src.models import Campaign, Transaction
from src.utils import get_db_engine

st.title("Campaign Manager")
st.markdown("---")

# Retrieve the global engine (it will create it if it doesn't exist, or reuse the existing one)
engine = get_db_engine()

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