import streamlit as st
import pandas as pd
import os
from sqlmodel import Session, select, func
from src.models import Transaction, Campaign, Strategy
from src.dbfunctions import create_engine_func

st.set_page_config(page_title="Campaign Manager", layout="wide")

@st.cache_resource
def get_db_engine():
    db_file = os.path.join("data", "portfolio.db")
    db_url = f"sqlite:///{db_file}"
    return create_engine_func(db_url)

engine = get_db_engine()

st.title("🎯 Campaign Manager")

tab_active, tab_assembler = st.tabs(["📊 Active Campaigns", "🧩 Trade Assembler"])

# ==============================================================================
# TAB 1: ACTIVE CAMPAIGNS (Manage, Rename, Archive)
# ==============================================================================
with tab_active:
    with Session(engine) as session:
        # Filter for Archived
        col_filter, col_spacer = st.columns([1, 5])
        show_archived = col_filter.checkbox("Show Archived/Closed")
        
        query = select(Campaign).order_by(Campaign.start_date.desc())
        if not show_archived:
            query = query.where(Campaign.status == "OPEN")
            
        campaigns = session.exec(query).all()
        
        if not campaigns:
            st.info("No active campaigns found. Check the Assembler tab or 'Show Archived'.")
        else:
            for camp in campaigns:
                # Basic info
                strat_name = "General"
                if camp.strategy_id:
                    strat = session.get(Strategy, camp.strategy_id)
                    if strat: strat_name = strat.name
                
                trade_count = session.exec(select(func.count(Transaction.id)).where(Transaction.campaign_id == camp.id)).one()
                
                # Card Header
                status_icon = "🟢" if camp.status == "OPEN" else "🔒"
                label = f"{status_icon} **{camp.symbol}**: {camp.name} ({strat_name}) | {trade_count} Trades"
                
                with st.expander(label, expanded=False):
                    
                    # --- EDIT TOOLS ---
                    c_edit_toggle, c_tools = st.columns([1, 3])
                    is_edit_mode = c_edit_toggle.toggle("Enable Editing", key=f"edit_{camp.id}")
                    
                    if is_edit_mode:
                        st.markdown("#### 🛠️ Campaign Settings")
                        
                        # 1. RENAME
                        new_name = st.text_input("Rename Campaign", value=camp.name, key=f"name_{camp.id}")
                        if new_name != camp.name:
                            camp.name = new_name
                            session.add(camp)
                            session.commit()
                            st.toast("Renamed!")
                        
                        # 2. ARCHIVE / DELETE
                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            # Archive Toggle
                            if camp.status == "OPEN":
                                if st.button("🔒 Archive (Close)", key=f"arch_{camp.id}"):
                                    camp.status = "CLOSED"
                                    session.add(camp)
                                    session.commit()
                                    st.rerun()
                            else:
                                if st.button("🟢 Re-Open", key=f"open_{camp.id}"):
                                    camp.status = "OPEN"
                                    session.add(camp)
                                    session.commit()
                                    st.rerun()
                        
                        with btn_col2:
                            # Hard Delete
                            if st.button("🗑️ Delete Campaign", key=f"del_{camp.id}", type="primary"):
                                # Release trades first
                                trades = session.exec(select(Transaction).where(Transaction.campaign_id == camp.id)).all()
                                for t in trades:
                                    t.campaign_id = None
                                    session.add(t)
                                session.delete(camp)
                                session.commit()
                                st.warning("Campaign deleted. Trades released to Assembler.")
                                st.rerun()

                        st.divider()
                        st.markdown("#### 📝 Manage Transactions")
                        st.caption("Uncheck 'Keep' to release a trade back to the orphan pool.")
                        
                        # 3. MANAGE TRADES
                        trades = session.exec(select(Transaction).where(Transaction.campaign_id == camp.id).order_by(Transaction.exec_date)).all()
                        if trades:
                            df_camp = pd.DataFrame([t.model_dump() for t in trades])
                            df_camp.insert(0, "Keep", True)
                            
                            edited_df = st.data_editor(
                                df_camp,
                                key=f"editor_{camp.id}",
                                column_config={
                                    "Keep": st.column_config.CheckboxColumn("Keep?", width="small"),
                                    "id": st.column_config.NumberColumn("ID", disabled=True),
                                    "exec_date": st.column_config.DateColumn("Date", disabled=True),
                                    "symbol": st.column_config.TextColumn("Symbol", disabled=True),
                                    "cb_description": st.column_config.TextColumn("Description", disabled=True),
                                },
                                hide_index=True,
                                use_container_width=True
                            )
                            
                            if st.button("💾 Save Trade Changes", key=f"save_trades_{camp.id}"):
                                remove_ids = edited_df[edited_df["Keep"] == False]["id"].tolist()
                                if remove_ids:
                                    for t in trades:
                                        if t.id in remove_ids:
                                            t.campaign_id = None
                                            session.add(t)
                                    session.commit()
                                    st.success(f"Released {len(remove_ids)} trades!")
                                    st.rerun()

                    else:
                        # READ ONLY VIEW
                        trades = session.exec(select(Transaction).where(Transaction.campaign_id == camp.id).order_by(Transaction.exec_date)).all()
                        if trades:
                            df_camp = pd.DataFrame([t.model_dump() for t in trades])
                            display_cols = ['exec_date', 'side', 'qty', 'price', 'cb_amount', 'cb_description']
                            # Filter safe columns
                            final_cols = [c for c in display_cols if c in df_camp.columns]
                            st.dataframe(df_camp[final_cols], hide_index=True, use_container_width=True)


# ==============================================================================
# TAB 2: ASSEMBLER (The Fix for Orphan Trades)
# ==============================================================================
with tab_assembler:
    st.header("🧩 Trade Assembler")
    
    with Session(engine) as session:
        # 1. Select Symbol
        query_symbols = select(Transaction.symbol).where(Transaction.campaign_id == None).distinct()
        symbols = session.exec(query_symbols).all()
        
        if not symbols:
            st.success("Zero orphan trades found! Clean board.")
        else:
            c_sel1, c_sel2 = st.columns(2)
            with c_sel1:
                selected_symbol = st.selectbox("Select Ticker", sorted(symbols))
            
            # 2. Get Orphans
            orphans = session.exec(
                select(Transaction)
                .where(Transaction.campaign_id == None)
                .where(Transaction.symbol == selected_symbol)
                .order_by(Transaction.exec_date.desc())
            ).all()
            
            # 3. The Assembler Table
            df_orphans = pd.DataFrame([t.model_dump() for t in orphans])
            df_orphans.insert(0, "Select", True)
            
            st.caption(f"Found {len(orphans)} unassigned trades for {selected_symbol}.")
            edited_df = st.data_editor(
                df_orphans[['Select', 'id', 'exec_date', 'side', 'qty', 'price', 'cb_description']],
                hide_index=True,
                use_container_width=True,
                column_config={"Select": st.column_config.CheckboxColumn("Include?")}
            )
            
            st.divider()
            
            # 4. ACTION TABS
            selected_ids = edited_df[edited_df["Select"] == True]["id"].tolist()
            
            tab_existing, tab_new = st.tabs(["➕ Add to Existing Campaign", "🚀 Create New Campaign"])
            
            # --- SUB-TAB: ADD TO EXISTING ---
            with tab_existing:
                exist_camps = session.exec(select(Campaign).where(Campaign.symbol == selected_symbol)).all()
                
                if not exist_camps:
                    st.warning(f"No existing campaigns found for {selected_symbol}. Create one in the next tab.")
                else:
                    camp_map = {f"{c.name} ({c.status})": c.id for c in exist_camps}
                    target_camp_name = st.selectbox("Select Target Campaign", list(camp_map.keys()), key="target_select")
                    target_camp_id = camp_map[target_camp_name]
                    
                    if st.button("➕ Append Selected Trades", type="primary", disabled=len(selected_ids)==0, key="btn_append"):
                        trades = session.exec(select(Transaction).where(Transaction.id.in_(selected_ids))).all()
                        for t in trades:
                            t.campaign_id = target_camp_id
                            session.add(t)
                        session.commit()
                        st.success(f"Added {len(trades)} trades to campaign!")
                        st.rerun()

            # --- SUB-TAB: CREATE NEW ---
            with tab_new:
                c_form1, c_form2 = st.columns(2)
                with c_form1:
                    new_camp_name = st.text_input("Name", value=f"{selected_symbol} Wheel")
                with c_form2:
                    strategies = session.exec(select(Strategy)).all()
                    strat_map = {s.name: s.id for s in strategies}
                    def_idx = list(strat_map.keys()).index("The Wheel") if "The Wheel" in strat_map else 0
                    selected_strat = st.selectbox("Strategy", list(strat_map.keys()), index=def_idx, key="strat_select")
                
                if st.button("🚀 Create & Assign Selected Trades", type="primary", disabled=len(selected_ids)==0, key="btn_create"):
                    new_campaign = Campaign(name=new_camp_name, symbol=selected_symbol, strategy_id=strat_map[selected_strat], status="OPEN")
                    session.add(new_campaign)
                    session.commit()
                    session.refresh(new_campaign)
                    
                    trades = session.exec(select(Transaction).where(Transaction.id.in_(selected_ids))).all()
                    for t in trades:
                        t.campaign_id = new_campaign.id
                        session.add(t)
                    session.commit()
                    st.success(f"Created '{new_camp_name}'!")
                    st.rerun()