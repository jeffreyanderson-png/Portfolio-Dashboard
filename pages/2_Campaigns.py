import streamlit as st
import pandas as pd
import os
from sqlmodel import Session, select, func
from src.models import Transaction, Campaign, Strategy, Note
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

# --- TAB 1: ACTIVE CAMPAIGNS ---
with tab_active:
    with Session(engine) as session:
        campaigns = session.exec(select(Campaign).order_by(Campaign.start_date.desc())).all()
        
        if not campaigns:
            st.info("No campaigns created yet.")
        else:
            for camp in campaigns:
                # Get Strategy Name
                strat_name = "General"
                if camp.strategy_id:
                    strat = session.get(Strategy, camp.strategy_id)
                    if strat: strat_name = strat.name
                
                # Get Trades
                trades = session.exec(select(Transaction).where(Transaction.campaign_id == camp.id).order_by(Transaction.exec_date)).all()
                
                # Header
                with st.expander(f"**{camp.symbol}**: {camp.name} ({strat_name}) | {len(trades)} Trades", expanded=False):
                    
                    # --- EDITING CONTROLS ---
                    c_edit, c_view = st.columns([1, 4])
                    with c_edit:
                        is_edit_mode = st.toggle("Enable Editing", key=f"toggle_{camp.id}")
                    
                    if is_edit_mode:
                        st.caption("Uncheck 'Keep' to release a trade back to the Assembler.")
                        if trades:
                            df_camp = pd.DataFrame([t.model_dump() for t in trades])
                            df_camp.insert(0, "Keep", True) # Default to keeping
                            
                            # Editable Grid
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
                            
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if st.button("💾 Save Changes", key=f"save_{camp.id}"):
                                    # Identify rows to remove
                                    remove_ids = edited_df[edited_df["Keep"] == False]["id"].tolist()
                                    if remove_ids:
                                        for t in trades:
                                            if t.id in remove_ids:
                                                t.campaign_id = None # Release to orphan pool
                                                session.add(t)
                                        session.commit()
                                        st.success("Trades released!")
                                        st.rerun()
                                    else:
                                        st.info("No changes made.")
                            
                            with col_btn2:
                                if st.button("🗑️ Delete Campaign", key=f"del_camp_{camp.id}", type="primary"):
                                    # Release ALL trades first (Safety)
                                    for t in trades:
                                        t.campaign_id = None
                                        session.add(t)
                                    session.delete(camp)
                                    session.commit()
                                    st.warning(f"Campaign '{camp.name}' deleted. Trades are now orphans.")
                                    st.rerun()
                        else:
                            st.warning("No trades in this campaign. Safe to delete.")
                            if st.button("Delete Empty Campaign", key=f"del_empty_{camp.id}"):
                                session.delete(camp)
                                session.commit()
                                st.rerun()

                    else:
                        # Read-Only View
                        if trades:
                            df_camp = pd.DataFrame([t.model_dump() for t in trades])
                            display_cols = ['exec_date', 'side', 'qty', 'price', 'cb_amount', 'cb_description']
                            st.dataframe(df_camp[display_cols], hide_index=True, use_container_width=True)

# --- TAB 2: ASSEMBLER (Unchanged logic, simplified for brevity) ---
with tab_assembler:
    st.header("Group Orphan Trades")
    with Session(engine) as session:
        query_symbols = select(Transaction.symbol).where(Transaction.campaign_id == None).distinct()
        symbols = session.exec(query_symbols).all()
        
        if not symbols:
            st.success("All trades have been assigned! Zero orphans.")
        else:
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_symbol = st.selectbox("Select Ticker", sorted(symbols))
            
            orphans = session.exec(
                select(Transaction)
                .where(Transaction.campaign_id == None)
                .where(Transaction.symbol == selected_symbol)
                .order_by(Transaction.exec_date.desc())
            ).all()
            
            if orphans:
                df_orphans = pd.DataFrame([t.model_dump() for t in orphans])
                df_orphans.insert(0, "Select", True)
                
                edited_df = st.data_editor(
                    df_orphans[['Select', 'id', 'exec_date', 'side', 'qty', 'price', 'cb_description']],
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Select": st.column_config.CheckboxColumn("Add?")}
                )
                
                st.divider()
                c_form1, c_form2 = st.columns(2)
                with c_form1:
                    new_camp_name = st.text_input("Campaign Name", value=f"{selected_symbol} Wheel")
                with c_form2:
                    strategies = session.exec(select(Strategy)).all()
                    strat_map = {s.name: s.id for s in strategies}
                    # Default to 'The Wheel' if exists
                    default_idx = list(strat_map.keys()).index("The Wheel") if "The Wheel" in strat_map else 0
                    selected_strat = st.selectbox("Strategy", options=list(strat_map.keys()), index=default_idx)
                
                if st.button("🚀 Create Campaign", type="primary"):
                    selected_ids = edited_df[edited_df["Select"] == True]["id"].tolist()
                    if selected_ids:
                        new_campaign = Campaign(name=new_camp_name, symbol=selected_symbol, strategy_id=strat_map[selected_strat])
                        session.add(new_campaign)
                        session.commit()
                        session.refresh(new_campaign)
                        
                        trades_to_update = session.exec(select(Transaction).where(Transaction.id.in_(selected_ids))).all()
                        for t in trades_to_update:
                            t.campaign_id = new_campaign.id
                            session.add(t)
                        session.commit()
                        st.success(f"Created '{new_camp_name}'!")
                        st.rerun()
                        