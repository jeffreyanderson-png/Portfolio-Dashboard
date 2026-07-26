import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode

from src.models import Campaign, Transaction
from src.utils import get_db_engine, get_live_positions_dict, calculate_live_deployed_capital
from src.schwab_af_api import get_account_data

engine = get_db_engine()

st.title("🗂️ Campaign Management")
st.markdown("---")

# ==========================================
# DATABASE UTILITIES
# ==========================================
with st.expander("🛠️ Database Utilities (Merge Duplicates)"):
    st.write("If you have duplicate campaigns for the same ticker (often caused by mixing CSV imports and API syncs), click below to merge them. All trades will be consolidated into the campaign that has an assigned strategy.")
    if st.button("Merge Duplicate Campaigns", type="primary"):
        with st.spinner("Merging duplicates..."):
            with Session(engine) as session:
                all_camps = session.exec(select(Campaign)).all()
                
                camps_by_symbol = {}
                for camp in all_camps:
                    symbol = camp.name
                    if camp.transactions:
                        for tx in camp.transactions:
                            if tx.root_ticker:
                                symbol = tx.root_ticker
                                break
                    
                    if symbol not in camps_by_symbol:
                        camps_by_symbol[symbol] = []
                    camps_by_symbol[symbol].append(camp)
                
                merge_count = 0
                for sym, camp_list in camps_by_symbol.items():
                    if len(camp_list) > 1:
                        camp_list.sort(
                            key=lambda c: (c.strategy is not None and c.strategy != "Unassigned", len(c.transactions)), 
                            reverse=True
                        )
                        
                        primary_camp = camp_list[0]
                        duplicates = camp_list[1:]
                        
                        for dup in duplicates:
                            for tx in dup.transactions:
                                tx.campaign_id = primary_camp.id
                                session.add(tx)
                            session.delete(dup)
                            merge_count += 1
                
                if merge_count > 0:
                    session.commit()
                    st.success(f"Successfully merged {merge_count} duplicate campaign(s)!")
                    st.rerun()
                else:
                    st.info("No duplicates found. Your database is clean!")

tab_master, tab_orphans = st.tabs(["📊 Master Campaign List", "❓ Orphaned Transactions"])

# ==========================================
# TAB 1: MASTER CAMPAIGN LIST (Editable)
# ==========================================
with tab_master:
    st.subheader("Assign Strategies & Manage Campaigns")
    st.write("Double-click a cell in the **Strategy** column to quickly assign a strategy. Changes save automatically!")

    with st.spinner("Establishing ground truth from Schwab..."):
        try:
            acct_data = get_account_data()
            live_positions_dict = get_live_positions_dict(acct_data)
        except Exception:
            live_positions_dict = {}

    with Session(engine) as session:
        campaigns = session.exec(select(Campaign)).all()
        
        camp_data = []
        for camp in campaigns:
            campaign_symbol = camp.name
            if camp.transactions:
                for tx in camp.transactions:
                    if tx.root_ticker:
                        campaign_symbol = tx.root_ticker
                        break
                        
            if campaign_symbol in live_positions_dict:
                display_status = "Active"
                deployed_capital = calculate_live_deployed_capital(live_positions_dict[campaign_symbol])
            else:
                display_status = "Closed"
                deployed_capital = 0.0
            
            current_strategy = camp.strategy if camp.strategy else "Unassigned"

            camp_data.append({
                "ID": camp.id,
                "Symbol": campaign_symbol,
                "Status": display_status,
                "Strategy": current_strategy,
                "Deployed Capital": deployed_capital,
                "Trade Count": len(camp.transactions)
            })

    if camp_data:
        df_camps = pd.DataFrame(camp_data)
        df_camps = df_camps.sort_values(by=["Status", "Deployed Capital"], ascending=[True, False])
        
        gb = GridOptionsBuilder.from_dataframe(df_camps)
        gb.configure_column("ID", hide=True)
        gb.configure_column("Deployed Capital", type=["numericColumn", "numberColumnFilter"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})")
        
        strategies = ["Unassigned", "Wheel", "LEAP", "Covered Call", "Credit Spread", "Iron Condor", "Buy & Hold", "Earnings Play", "Dividend Capture"]
        gb.configure_column(
            "Strategy", 
            editable=True, 
            cellEditor='agSelectCellEditor', 
            cellEditorParams={'values': strategies},
            cellStyle={'backgroundColor': '#1e3a8a', 'color': 'white'} 
        )
        
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        gb.configure_default_column(resizable=True, sortable=True, filter=True)
        grid_options = gb.build()

        grid_response = AgGrid(
            df_camps,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            fit_columns_on_grid_load=True,
            theme='streamlit',
            height=600
        )

        updated_df = grid_response['data']
        
        if updated_df is not None and not updated_df.empty:
            merged_df = updated_df.merge(df_camps, on="ID", suffixes=('_new', '_old'))
            changed_rows = merged_df[merged_df['Strategy_new'] != merged_df['Strategy_old']]
            
            if not changed_rows.empty:
                with Session(engine) as session:
                    for index, row in changed_rows.iterrows():
                        camp_id = row['ID']
                        new_strategy = row['Strategy_new']
                        
                        db_camp = session.get(Campaign, camp_id)
                        if db_camp:
                            db_camp.strategy = new_strategy
                            session.add(db_camp)
                    
                    session.commit()
                
                st.success(f"Successfully updated {len(changed_rows)} campaign(s)!")
                st.rerun()

    else:
        st.info("No campaigns found in the database.")


# ==========================================
# TAB 2: ORPHANED TRANSACTIONS
# ==========================================
with tab_orphans:
    st.subheader("Orphaned Transactions Triage")
    st.write("These transactions are not currently linked to any Campaign. Check the boxes to assign them.")
    
    with Session(engine) as session:
        orphans = session.exec(select(Transaction).where(Transaction.campaign_id == None)).all()
        
        if not orphans:
            st.success("Great job! All transactions are successfully linked to a campaign.")
        else:
            orphan_data = []
            for tx in orphans:
                orphan_data.append({
                    "ID": tx.id,
                    "Date": tx.exec_datetime.strftime("%Y-%m-%d") if tx.exec_datetime else "Unknown",
                    "Asset": tx.asset_type,
                    "Symbol": tx.full_symbol,
                    "Instruction": tx.action,
                    "Qty": tx.quantity,
                    "Price": tx.price,
                    "Amount": tx.amount
                })
                
            df_orphans = pd.DataFrame(orphan_data)
            gb_orph = GridOptionsBuilder.from_dataframe(df_orphans)
            
            # Hide the ID column
            gb_orph.configure_column("ID", hide=True)
            
            # Explicitly set checkboxes to appear on the Date column (the first visible column)
            gb_orph.configure_column("Date", headerCheckboxSelection=True, checkboxSelection=True)
            
            gb_orph.configure_default_column(resizable=True, sortable=True, filter=True)
            gb_orph.configure_column("Price", type=["numericColumn"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})")
            gb_orph.configure_column("Amount", type=["numericColumn"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})")
            
            # Selection mode (we don't need use_checkbox=True here since we attached it directly to "Date" above)
            gb_orph.configure_selection('multiple')
            
            grid_resp_orphans = AgGrid(
                df_orphans,
                gridOptions=gb_orph.build(),
                update_mode=GridUpdateMode.SELECTION_CHANGED, 
                fit_columns_on_grid_load=True,
                theme='streamlit'
            )
            
            # --- ASSIGNMENT UI ---
            selected_rows = grid_resp_orphans.get('selected_rows', None)
            
            sel_ids = []
            if selected_rows is not None and len(selected_rows) > 0:
                if isinstance(selected_rows, pd.DataFrame):
                    sel_ids = selected_rows['ID'].tolist()
                else:
                    sel_ids = [row['ID'] for row in selected_rows]
            
            if sel_ids:
                st.markdown("### 🗃️ Assign Selected Transactions")
                
                all_camps = session.exec(select(Campaign).order_by(Campaign.name)).all()
                camp_options = {f"{c.name} (ID: {c.id})": c.id for c in all_camps}
                
                assign_mode = st.radio("Assignment Method:", ["Add to Existing Campaign", "Create New Campaign"], horizontal=True)
                
                if assign_mode == "Add to Existing Campaign":
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        chosen_camp = st.selectbox("Select Destination Campaign:", list(camp_options.keys()))
                    with col2:
                        st.write("") 
                        st.write("") 
                        if st.button("Link Selected", type="primary", use_container_width=True):
                            camp_id = camp_options[chosen_camp]
                            for tx_id in sel_ids:
                                tx = session.get(Transaction, tx_id)
                                if tx:
                                    tx.campaign_id = camp_id
                                    session.add(tx)
                            session.commit()
                            st.success(f"Successfully linked {len(sel_ids)} transactions!")
                            st.rerun()
                            
                elif assign_mode == "Create New Campaign":
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        new_camp_name = st.text_input("Enter New Campaign Ticker/Name:")
                    with col2:
                        st.write("") 
                        st.write("") 
                        if st.button("Create & Link", type="primary", use_container_width=True):
                            if new_camp_name:
                                new_camp = Campaign(name=new_camp_name.upper(), strategy="Unassigned")
                                session.add(new_camp)
                                session.commit()
                                session.refresh(new_camp)
                                
                                for tx_id in sel_ids:
                                    tx = session.get(Transaction, tx_id)
                                    if tx:
                                        tx.campaign_id = new_camp.id
                                        session.add(tx)
                                session.commit()
                                st.success(f"Created {new_camp_name.upper()} and linked {len(sel_ids)} transactions!")
                                st.rerun()
                            else:
                                st.error("Please enter a campaign name.")