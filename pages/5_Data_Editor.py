import os
import sqlite3
import streamlit as st
import pandas as pd

# --- 1. Database Connection Helper ---
def get_db_connection():
    db_file = os.path.join("data", "portfolio.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

# --- 2. Load Data ---
def load_trades():
    conn = get_db_connection()
    df = pd.read_sql_query('SELECT * FROM "transaction"', conn)
    conn.close()
    return df

# --- 3. The Admin/Editor Interface ---
def show_admin_page():
    st.header("Database Management: Trades")
    st.info("Make edits directly in the table below. Click 'Commit Changes' to save to the database.")

    if "current_trades" not in st.session_state:
        st.session_state.current_trades = load_trades()

    df = st.session_state.current_trades

    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="trade_db_editor", 
        hide_index=True
    )

    # --- 4. Commit Changes Logic ---
    if st.button("Commit Changes", type="primary"):
        changes = st.session_state["trade_db_editor"]
        
        edited_rows = changes.get("edited_rows", {})
        added_rows = changes.get("added_rows", [])
        deleted_rows = changes.get("deleted_rows", []) 

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Handle Deletions
            if deleted_rows:
                ids_to_delete = [int(df.iloc[idx]['id']) for idx in deleted_rows]
                placeholders = ', '.join(['?'] * len(ids_to_delete))
                cursor.execute(f'DELETE FROM "transaction" WHERE id IN ({placeholders})', ids_to_delete)

            # Handle Edits
            if edited_rows:
                for idx, updates in edited_rows.items():
                    trade_id = int(df.iloc[idx]['id'])
                    set_clause = ', '.join([f"{col} = ?" for col in updates.keys()])
                    values = list(updates.values())
                    values.append(trade_id)
                    cursor.execute(f'UPDATE "transaction" SET {set_clause} WHERE id = ?', values)

            # Handle Additions
            if added_rows:
                for row in added_rows:
                    columns = ', '.join(row.keys())
                    placeholders = ', '.join(['?'] * len(row))
                    values = list(row.values())
                    cursor.execute(f'INSERT INTO "transaction" ({columns}) VALUES ({placeholders})', values)

            conn.commit()
            st.success("Database updated successfully!")
            
            st.session_state.current_trades = load_trades()
            st.rerun()

        except Exception as e:
            conn.rollback()
            st.error(f"Error updating database: {e}")
            
        finally:
            conn.close()

show_admin_page()
