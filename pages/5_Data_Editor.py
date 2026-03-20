import os
import sqlite3
import streamlit as st
import pandas as pd

# --- 1. Database Connection Helper ---
def get_db_connection():
    # Route to the data folder exactly like your other pages
    db_file = os.path.join("data", "portfolio.db")
    
    # Pass the file path directly to sqlite3
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

# --- 2. Load Data ---
def load_trades():
    conn = get_db_connection()
    # Pulling the ID is critical for targeted updates/deletions
    df = pd.read_sql_query("SELECT * FROM trades", conn)
    conn.close()
    return df

# --- 3. The Admin/Editor Interface ---
def show_admin_page():
    st.header("Database Management: Trades")
    st.info("Make edits directly in the table below. Click 'Commit Changes' to save to the database.")

    # Load current data
    if "current_trades" not in st.session_state:
        st.session_state.current_trades = load_trades()

    df = st.session_state.current_trades

    # Render the data editor
    # num_rows="dynamic" allows the user to add or delete rows via the UI
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="trade_db_editor", # This key is required to track the delta changes
        hide_index=True
    )

    # --- 4. Commit Changes Logic ---
    if st.button("Commit Changes", type="primary"):
        # Streamlit stores the exact changes in session_state under the editor's key
        changes = st.session_state["trade_db_editor"]
        
        edited_rows = changes.get("edited_rows", {})
        added_rows = changes.get("added_rows", [])
        deleted_rows = changes.get("deleted_rows", []) # List of index integers

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Handle Deletions
            if deleted_rows:
                # Map the dataframe index to the actual database ID
                ids_to_delete = [int(df.iloc[idx]['id']) for idx in deleted_rows]
                placeholders = ', '.join(['?'] * len(ids_to_delete))
                cursor.execute(f"DELETE FROM trades WHERE id IN ({placeholders})", ids_to_delete)

            # Handle Edits
            if edited_rows:
                for idx, updates in edited_rows.items():
                    trade_id = int(df.iloc[idx]['id'])
                    # Dynamically build the UPDATE query based on edited columns
                    set_clause = ', '.join([f"{col} = ?" for col in updates.keys()])
                    values = list(updates.values())
                    values.append(trade_id)
                    cursor.execute(f"UPDATE trades SET {set_clause} WHERE id = ?", values)

            # Handle Additions (Manual entry backup)
            if added_rows:
                for row in added_rows:
                    columns = ', '.join(row.keys())
                    placeholders = ', '.join(['?'] * len(row))
                    values = list(row.values())
                    cursor.execute(f"INSERT INTO trades ({columns}) VALUES ({placeholders})", values)

            conn.commit()
            st.success("Database updated successfully!")
            
            # Refresh the data in session state so the UI updates
            st.session_state.current_trades = load_trades()
            st.rerun()

        except Exception as e:
            conn.rollback()
            st.error(f"Error updating database: {e}")
            
        finally:
            conn.close()

# Call this function in your main app routing
show_admin_page()