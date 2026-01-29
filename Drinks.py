import streamlit as st
from streamlit_option_menu import option_menu
import sqlite3
import qrcode
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF for PDF generation
import os
import io
import base64
import cv2
from pyzbar.pyzbar import decode
import datetime
from datetime import datetime
from datetime import date
import calendar


from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas


# ---------------- SESSION STATE INIT ----------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'menu' not in st.session_state:
    st.session_state.menu = "Landing"
if 'username' not in st.session_state:
    st.session_state.username = ""

# Initialize session state variables
if "item_name" not in st.session_state:
    st.session_state.item_name = ""

if "category" not in st.session_state:
    st.session_state.category = ""

if "quantity" not in st.session_state:
    st.session_state.quantity = 1   # sensible default

if "fridge_no" not in st.session_state:
    st.session_state.fridge_no = ""


# ---------------- DATABASE FUNCTIONS ----------------
def get_connection():
    return sqlite3.connect('inventory.db')

def create_tables():
    conn = get_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,  
        item_name TEXT,
        category TEXT,
        quantity REAL,
        fridge_no INTEGER
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        item_name TEXT,
        quantity REAL,
        selling_price REAL,
        total_sale REAL,
        cost REAL,
        profit REAL,
        date TEXT,
        customer_id INTEGER,
        overridden INTEGER DEFAULT 0,
        FOREIGN KEY (item_id) REFERENCES items(item_id)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        email TEXT,
        address TEXT, 
        group_id INTEGER
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        category TEXT,
        action TEXT,
        quantity REAL,
        unit_cost REAL,
        selling_price REAL,
        user TEXT,
        timestamp TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pricing_tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    min_qty REAL NOT NULL,
    max_qty REAL,  -- NULL means no upper limit
    price_per_unit REAL NOT NULL,
    label TEXT,
    FOREIGN KEY (item_id) REFERENCES items(item_id)
    )
    """)
    # Pricing groups (optional, for bulk rules)
    # e.g. multiplier = 0.9 for 10% cheaper, 1.2 for 20% higher
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pricing_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        multiplier REAL   
    )
    """)

    # Customer-specific overrides
    conn.execute("""
    CREATE TABLE IF NOT EXISTS customer_price_list (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        item_id INTEGER,
        custom_price REAL
    )
    """)
    conn.commit()
    conn.close()

def view_items():
    conn = get_connection()
    df = pd.read_sql_query('SELECT * FROM items', conn)
    conn.close()
    return df

def view_pricing():
    conn = get_connection()
    df = pd.read_sql_query('SELECT * FROM pricing_tiers',conn)
    conn.close()
    return df

def view_sales():
    conn = get_connection()
    df = pd.read_sql_query('SELECT * FROM sales', conn)
    conn.close()
    return df

def view_sales_by_customer (customer_id):
    conn = get_connection()
    query = f'SELECT * FROM sales WHERE customer_id = {customer_id}'
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def view_customers():
    conn = get_connection()
    df = pd.read_sql_query('SELECT * FROM customers', conn)
    conn.close()
    return df

def get_price_list():
    conn = get_connection()
    df = pd.read_sql("""
        SELECT cpl.id, c.name AS customer_name, i.item_name AS item_name, cpl.custom_price,
               cpl.customer_id, cpl.item_id
        FROM customer_price_list cpl
        JOIN customers c ON cpl.customer_id = c.id
        JOIN items i ON cpl.item_id = i.item_id
    """, conn)
    conn.close()
    return df

def add_price(customer_id, item_id, custom_price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO customer_price_list (customer_id, item_id, custom_price) VALUES (?, ?, ?)",
                   (customer_id, item_id, custom_price))
    conn.commit()

def update_price(record_id, custom_price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customer_price_list SET custom_price = ? WHERE id = ?", (custom_price, record_id))
    conn.commit()

def delete_price(record_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM customer_price_list WHERE id = ?", (record_id,))
    conn.commit()


# ---------- Group Pricing -----
def get_base_price(item_id, qty):
    conn = get_connection()
    cur = conn.cursor()
    # Find the tier that matches qty
    cur.execute("""
        SELECT price_per_unit 
        FROM pricing_tiers 
        WHERE item_id=? 
          AND min_qty <= ? 
          AND (max_qty IS NULL OR max_qty=0 OR max_qty >= ?)
        ORDER BY min_qty DESC
        LIMIT 1
    """, (item_id, qty, qty))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_customer_adjusted_price(customer_id, item_id, qty):
    base_price = get_base_price(item_id, qty)
    if base_price is None:
        return None

    conn = get_connection()
    cur = conn.cursor()

    # Check for override first
    cur.execute("""
        SELECT custom_price 
        FROM customer_price_list 
        WHERE customer_id=? AND item_id=?
    """, (customer_id, item_id))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]

    # Otherwise check group multiplier
    cur.execute("""
        SELECT g.multiplier 
        FROM customers c 
        JOIN pricing_groups g ON c.group_id = g.id 
        WHERE c.id=?
    """, (customer_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        return base_price * row[0]
    else:
        return base_price

# ----------------------------------
def view_sales_by_customers(customer_id=None):
    conn = get_connection()
    
    if customer_id:
        query = 'SELECT * FROM sales WHERE customer_id = ?'
        df = pd.read_sql_query(query, conn, params=(customer_id,))
    else:
        query = 'SELECT * FROM sales'
        df = pd.read_sql_query(query, conn)
    
    conn.close()
    return df

def view_audit_log(start_date=None, end_date=None):
    conn = get_connection()
    if start_date and end_date:
        query = """
        SELECT * FROM audit_log
        WHERE DATE(timestamp) BETWEEN ? AND ?
        ORDER BY timestamp DESC
        """
        df = pd.read_sql_query(query, conn, params=(start_date, end_date))
    else:
        df = pd.read_sql_query('SELECT * FROM audit_log ORDER BY timestamp DESC', conn)
    conn.close()
    return df


# ---------------- Pagination Utility ----------------
def paginate_dataframe(df, page_size=20):
    total_rows = len(df)
    if total_rows == 0:
        return df, 1
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return df.iloc[start_idx:end_idx], total_pages

# ---------------- CRUD FUNCTIONS ----------------
def add_or_update_item(item_id, item_name, category, quantity, fridge_no, user):
    conn = get_connection()
    cursor = conn.cursor()
    if item_id == None:
        cursor.execute('SELECT item_id, item_name, quantity, fridge_no FROM items WHERE item_name=? AND category=? AND fridge_no=?', (item_name, category, fridge_no))
    else:
        cursor.execute('SELECT item_id, item_name, quantity, fridge_no FROM items WHERE item_id=? AND category=? AND fridge_no=?', (item_id, category, fridge_no))
    existing = cursor.fetchone()
    if existing:
        # existing is a tuple (item_id, item_name, quantity)
        existing_id, existing_name, current_qty, fridge_no = existing
        new_quantity = current_qty + quantity

        cursor.execute('UPDATE items SET quantity=?, fridge_no=? WHERE item_id=?',
                       (new_quantity, fridge_no, existing[0]))
        action = "Update"
        # Log into audit any changes
        cursor.execute('INSERT INTO audit_log (item_name, category, action, quantity, unit_cost, selling_price, user, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME("now"))',
                    (existing_name, category, action, quantity, 0.00, 0.00, user))

    else:
        cursor.execute('INSERT INTO items (item_name, category, quantity, fridge_no) VALUES (?, ?, ?, ?)',
                       (item_name, category, quantity, fridge_no))
        new_item_id = cursor.lastrowid   # ✅ get the auto-generated item_id
        action = "Add"
        # Log into audit any changes
        cursor.execute('INSERT INTO audit_log (item_name, category, action, quantity, unit_cost, selling_price, user, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME("now"))',
                    (item_name, category, action, quantity, 0.00, 0.00, user))
    conn.commit()
    conn.close()

def delete_item(item_id, user):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT item_name, category, quantity FROM items WHERE item_id=?', (item_id,))
    item_details = cursor.fetchone()
    if item_details:
        cursor.execute('INSERT INTO audit_log (item_name, category, action, quantity, unit_cost, selling_price, user, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME("now"))',
                       (item_details[0], item_details[1], "Delete", item_details[2], 0.00, 0.00, user))
        cursor.execute('DELETE FROM items WHERE item_id=?', (item_id,))
    conn.commit()
    conn.close()

# Get total quantity based on item_name
def get_total_qty(selected_item_name):
    conn = get_connection()
    conn.row_factory = sqlite3.Row   # ensure dict-like access
    cursor = conn.cursor()

    # Get all records for this item_name (could be multiple fridges)
    cursor.execute("SELECT * FROM items WHERE item_name=?", (selected_item_name,))
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return "Item not found."

    # ✅ Sum total quantity across all fridges
    total_quantity = sum(row['quantity'] for row in rows)
    conn.close()
    return total_quantity

# Record sales
def record_sale(item_id, quantity, user, customer_id, override_total=None):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get item details
    cursor.execute("SELECT * FROM items WHERE item_id=?", (item_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return "Item not found."

    item_name = row['item_name']
    category = row['category']

    # Get all fridge records for this item_name
    cursor.execute("SELECT * FROM items WHERE item_name=?", (item_name,))
    rows = cursor.fetchall()
    total_quantity = sum(r['quantity'] for r in rows)
    if total_quantity < quantity:
        conn.close()
        return "Not enough stock."

    # Get pricing tier
    cursor.execute("""
        SELECT price_per_unit 
        FROM pricing_tiers
        WHERE item_id = ?
          AND min_qty <= ?
          AND (max_qty IS NULL OR max_qty = 0 OR ? <= max_qty)
        ORDER BY min_qty DESC
        LIMIT 1
    """, (item_id, quantity, quantity))
    tier = cursor.fetchone()
    if tier is None:
        conn.close()
        return f"No pricing tier found for {quantity} units of item {item_id}."

    price_per_unit = tier['price_per_unit']
    selling_price = override_total if override_total is not None else price_per_unit
    total_sale = quantity * selling_price
    overridden_flag = 1 if override_total is not None else 0
    cost = 0.0
    profit = 0.0

    # Deduct stock across fridges
    qty_to_deduct = quantity
    deduction_log = []
    for r in rows:
        if qty_to_deduct <= 0:
            break
        available = r['quantity']
        deduct = min(available, qty_to_deduct)
        new_qty = available - deduct
        cursor.execute("UPDATE items SET quantity=? WHERE item_id=?", (new_qty, r['item_id']))
        qty_to_deduct -= deduct
        deduction_log.append(f"Fridge {r['fridge_no']}: deducted {deduct}, new qty={new_qty}")

    # Insert into sales
    cursor.execute("""
        INSERT INTO sales 
        (item_id, item_name, quantity, selling_price, total_sale, cost, profit, date, customer_id, overridden) 
        VALUES (?, ?, ?, ?, ?, ?, ?, DATE('now'), ?, ?)
    """, (item_id, item_name, quantity, selling_price, total_sale, cost, profit, customer_id, overridden_flag))

    # Insert into audit log
    cursor.execute("""
        INSERT INTO audit_log 
        (item_name, category, action, quantity, unit_cost, selling_price, user, timestamp) 
        VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME('now'))
    """, (item_name, category, "Sale", quantity, cost, selling_price, user))

    conn.commit()
    conn.close()

    return f"Sale recorded. Deduction details:\n" + "\n".join(deduction_log)

# ---------------- Excel/CSV import file for Stock Add/Update ----------------
def import_items_and_add_or_insert():
    # Prompt user for file path
    file_path = input("Please enter the full path to your Excel or CSV file: ").strip()

    # Determine file type and read accordingly
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext == '.csv':
        df = pd.read_csv(file_path)
    elif file_ext == '.xlsx':
        df = pd.read_excel(file_path, engine='openpyxl')
    elif file_ext == '.xls':
        df = pd.read_excel(file_path, engine='xlrd')
    else:
        raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")

    # Connect to the database
    conn = get_connection()
    cursor = conn.cursor()

    # Process each item in the file
    for _, row in df.iterrows():
        item = row['item']
        category = row['category']
        #unit_cost = row['unit_cost']
        #selling_price = row['selling_price']
        quantity = row['quantity']

        # Check if item exists
        cursor.execute("SELECT stock_quantity FROM items WHERE item_id = ?", (item_id,))
        result = cursor.fetchone()

        if result:
            # Item exists, update stock quantity
            current_quantity = result[0]
            new_quantity = current_quantity + quantity
            cursor.execute("UPDATE items SET stock_quantity = ? WHERE item_id = ?", (new_quantity, item_id))
        else:
            # Item does not exist, insert new item
            cursor.execute("""
                INSERT INTO items (item_id, category, quantity)
                VALUES (?, ?, ?, ?, ?)
            """, (item_id, category, quantity))

    # Commit changes and close connection
    conn.commit()
    conn.close()
    print("Items updated or inserted successfully.")

# ------------ Update Pricing Tiers manually -----
def update_pricing_tiers_ui():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Step 1: Select item
    cursor.execute("SELECT item_id, item_name FROM items")
    items = cursor.fetchall()

    # Build dictionary with combined display string
    item_dict = {f"{iid} - {name}": iid for iid, name in items}
    #item_dict = {name: iid for iid, name in items}

    st.subheader("🔧 Update Pricing Tiers")
    selected_item = st.selectbox("Select Item", list(item_dict.keys()))

    if selected_item:
        item_id = item_dict[selected_item]   # retrieve the actual item_id
        st.write(f"Selected Item ID: {item_id}")

        # Step 2: Show existing tiers
        cursor.execute("SELECT id, min_qty, max_qty, price_per_unit, label FROM pricing_tiers WHERE item_id=?", (item_id,))
        tiers = cursor.fetchall()

        if tiers:
            st.write("Existing Pricing Tiers:")
            for tier in tiers:
                tier_id, min_qty, max_qty, price_per_unit, label = tier
                with st.expander(f"Tier {tier_id} ({label})"):
                    new_min = st.number_input("Min Qty", value=min_qty, key=f"min_{tier_id}")
                    new_max = st.number_input("Max Qty (0 = no limit)", value=max_qty if max_qty is not None else 0, key=f"max_{tier_id}")
                    new_price = st.number_input("Price per Unit", value=price_per_unit, format="%,.2f", key=f"price_{tier_id}")
                    new_label = st.text_input("Label", value=label, key=f"label_{tier_id}")

                    if st.button(f"Update Tier {tier_id}", key=f"update_{tier_id}"):
                        cursor.execute("""
                            UPDATE pricing_tiers
                            SET min_qty=?, max_qty=?, price_per_unit=?, label=?
                            WHERE id=?
                        """, (new_min, None if new_max == 0 else new_max, new_price, new_label.strip().upper(), tier_id))
                        conn.commit()
                        st.success(f"Tier {tier_id} updated successfully!")

        else:
            st.info("No pricing tiers found for this item.")

    conn.close()

# ---------------- VAlidate if special price for customer exists -------
def validate_special_price_exist(selected_customer, selected_item):
    """
    Returns True if the special pricing for a customer exists
    """

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customer_price_list WHERE customer_id=? and item_id=?", (selected_customer, selected_item))
    rows = cur.fetchall()
    if rows:
        conn.close()
        #st.write("Found")
        return True
    else:
        conn.close()
        #st.write("Not found")
        return False    

# ---------------- manage_special_customer_pricing() -----
def manage_special_customer_pricing():
    
    # Show current price list
    st.subheader("Manage Special Customer Price List")
    st.dataframe(get_price_list())

    st.markdown("---")

    # ✅ Collapsible Add/Update section
    with st.expander("➕ Add / Update Special Customer Pricing", expanded=False):
        # Dropdowns for customer and item
        customers_df = view_customers()
        items_df = view_items()

        customer_options = ["Select customer"] + [f"{row['id']} - {row['name']}" for _, row in customers_df.iterrows()]
        item_options = ["Select item"] + [f"{row['item_id']} - {row['item_name']}" for _, row in items_df.iterrows()]

        selected_customer = st.selectbox("Customer", customer_options, index=0)
        selected_item = st.selectbox("Item", item_options, index=0)

        custom_price = st.number_input("Custom Price", min_value=0.0, format="%.2f")

        if st.button("Save Special Price"):

            # Extract IDs from selected options
            customer_id = None
            item_id = None

            if selected_customer != "Select customer":
                customer_id = int(selected_customer.split(" - ")[0])

            if selected_item != "Select item":
                item_id = int(selected_item.split(" - ")[0])

            conn = get_connection()
            cursor = conn.cursor()
            if validate_special_price_exist(customer_id, item_id):   # if existing, means it's an update
                cursor.execute(
                    "UPDATE customer_price_list SET custom_price=? WHERE customer_id=? and item_id=?",
                    (custom_price, customer_id, item_id)
                )
                conn.commit()
                conn.close()
                st.success(f"Updated existing special pricing for {customer_id}.")
                st.rerun()
            else:
                add_price(customer_id, item_id, custom_price)
                st.success(f"Added new special pricing for {customer_id}.")
                st.rerun()


    # ✅ Collapsible Delete section
    with st.expander("🗑️ Delete Special Customer Pricing", expanded=False):
        st.subheader("Delete a Special Customer Price")
        # Delete requires selecting an existing record
        price_list_df = get_price_list()
        if not price_list_df.empty:
            record_options_del = ["Select record"] + [f"{row['id']} - {row['customer_name']} - {row['item_name']}" 
                                                    for _, row in price_list_df.iterrows()]
            selected_record_del = st.selectbox("Select record to delete", record_options_del, index=0)
            if selected_record_del != "Select record":
                record_id = int(selected_record_del.split(" - ")[0])
                if st.button("Delete Price"):
                    delete_price(record_id)
                    st.success("Price deleted.")



# ----------------- Manage Pricing Tiers -------------
def manage_pricing_tiers():
    st.title("Manage Pricing Tiers")

    # Select item first
    items_df = view_items()
    if items_df.empty:
        st.warning("No items found.")
        return

    item_label = st.selectbox(
        "Select Item",
        items_df.apply(lambda row: f"{row['item_id']} - {row['item_name']}", axis=1)
    )
    item_id = int(item_label.split(" - ")[0])
    item_name = item_label.split(" - ")[1]

    # Show existing tiers
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pricing_tiers WHERE item_id=? ORDER BY min_qty", (item_id,))
    tiers = cursor.fetchall()
    conn.close()

    if tiers:
        st.subheader("Existing Pricing Tiers")
        tiers_df = pd.DataFrame(tiers, columns=tiers[0].keys())
        # Format nicely
        st.write(f"Max qty - {tiers_df["max_qty"]}")
        tiers_df["max_qty"] = tiers_df["max_qty"].fillna("∞")
        tiers_df["price_per_unit"] = tiers_df["price_per_unit"].map(lambda x: f"{x:.2f}")
        st.dataframe(tiers_df, width='stretch')
    else:
        st.info("No pricing tiers defined for this item yet.")

    st.markdown("---")

    # ✅ Collapsible Add/Update section
    with st.expander("➕ Add / Update Pricing Tier", expanded=False):
        min_qty = st.number_input("Minimum Quantity", min_value=1)
        max_qty = st.number_input("Maximum Quantity (0 = unlimited)", min_value=0)
        price_per_unit = st.number_input("Price per Unit", min_value=0.0, format="%.2f")
        label = st.text_input("Tier Label (optional)", value=item_name)

        if st.button("Save Tier"):
            conn = get_connection()
            cursor = conn.cursor()
            if validate_if_exist(item_id, min_qty, max_qty):   # if existing, means it's an update
                if max_qty == 0 or max_qty is None:
                    cursor.execute(
                        "UPDATE pricing_tiers SET price_per_unit=?, label=? WHERE item_id=? AND min_qty=? AND max_qty IS NULL",
                        (price_per_unit, label.strip().upper(), item_id, min_qty)
                    )
                else:
                    cursor.execute(
                        "UPDATE pricing_tiers SET price_per_unit=?, label=? WHERE item_id=? AND min_qty=? AND max_qty=?",
                        (price_per_unit, label.strip().upper(), item_id, min_qty, max_qty)
                    )
                conn.commit()
                conn.close()
                st.success(f"Updated existing pricing tier for {item_id}.")
                st.rerun()
            else:
                cursor.execute(
                    "INSERT INTO pricing_tiers (item_id, min_qty, max_qty, price_per_unit, label) VALUES (?, ?, ?, ?, ?)",
                    (item_id, min_qty, None if max_qty == 0 else max_qty, price_per_unit, label.strip().upper())
                )                
                conn.commit()
                conn.close()
                st.success("Added new Pricing tier successfully!")
                st.rerun()


    # ✅ Collapsible Delete section
    if tiers:
        with st.expander("🗑️ Delete a Tier", expanded=False):
            st.subheader("Delete a Tier")
            tier_to_delete = "Select Tier to Delete" 
            # tier_ids = [f"{t['id']} (min {t['min_qty']}, max {t['max_qty'] or '∞'})" for t in tiers]
            tier_ids = ["Select Tier to Delete"] + [
                f"{t['id']} (min {t['min_qty']}, max {t['max_qty'] or '∞'})" for t in tiers
            ]
            tier_to_delete = st.selectbox("Select Tier to Delete", tier_ids)
            if st.button("Delete Tier"):
                tier_id = int(tier_to_delete.split()[0])
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM pricing_tiers WHERE id=?", (tier_id,))
                conn.commit()
                conn.close()
                st.success("Tier deleted successfully!")
                st.rerun()

# -------------- Validate no overlap on tiers -----------------
def validate_if_exist(item_id, min_qty, max_qty):
    """
    Returns True if the proposed [min_qty, max_qty] does NOT overlap
    with any existing tier for the item. Treats None as infinity.
    """
    st.write(f"item id = {item_id}, {min_qty}, {max_qty}")
    conn = get_connection()
    cur = conn.cursor()
    if max_qty == 0 or max_qty is None:
        cur.execute("SELECT id, min_qty, max_qty FROM pricing_tiers WHERE item_id=? and min_qty=? AND max_qty IS NULL", (item_id, min_qty))
    else:
        cur.execute("SELECT id, min_qty, max_qty FROM pricing_tiers WHERE item_id=? and min_qty=? and max_qty=?", (item_id, min_qty, max_qty))
    rows = cur.fetchall()
    if rows:
        conn.close()
        st.write("Found")
        return True
    else:
        conn.close()
        st.write("Not found")
        return False

# --------------- Validate if customer exists --------------
def validate_if_customer_exist(name):
    """
    Docstring for validate_if_customer_exist
    
    :param name: Description
    """

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM CUSTOMERS WHERE name=?", (name.upper(),))
    rows = cur.fetchall()
    if rows:
        conn.close()
        return True
    else:
        conn.close()
        return False

# --------------- Generate Purchase Order ----------------
def generate_po_pdf(order_date, customer_id, pickup_date):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # --- Generate PO Number ---
    cursor.execute("CREATE TABLE IF NOT EXISTS po_sequence (date TEXT, seq INTEGER)")
    cursor.execute("SELECT seq FROM po_sequence WHERE date=?", (order_date,))
    row = cursor.fetchone()
    if row:
        seq = row['seq'] + 1
        cursor.execute("UPDATE po_sequence SET seq=? WHERE date=?", (seq, order_date))
    else:
        seq = 1
        cursor.execute("INSERT INTO po_sequence (date, seq) VALUES (?, ?)", (order_date, seq))
    conn.commit()
    po_number = f"PO-{order_date.replace('-', '')}-{seq:03d}"

    # --- Vendor Info ---
    vendor = {
        "name": "KPrime Supplies",
        "address": "Blk 3 Lot 5 West Wing Villas, North Belton QC",
        "phone": "+63 995 744 9953",
        "email": "kprimefoodinc@gmail.com"
    }

    # --- Buyer Info ---
    cursor.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
    customer = cursor.fetchone()
    buyer = {
        "name": customer['name'],
        "address": customer['address'],
        "phone": customer['phone'],
        "email": customer['email']
    }
    safe_name = buyer['name'].replace(" ", "_").replace("/", "_")
    filename = f"PO_{order_date.replace('-', '')}_{safe_name}.pdf"

    # --- Order Details ---
    sales_df = pd.read_sql_query(
        "SELECT item_id, item_name, SUM(quantity) as total_qty, selling_price "
        "FROM sales WHERE date=? AND customer_id=? GROUP BY item_name, selling_price",
        conn,
        params=(order_date, customer_id)
    )
    conn.close()

    # --- Build PDF ---
    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=40)
    styles = getSampleStyleSheet()
    elements = []

    # Header
    elements.append(Paragraph("PURCHASE ORDER (PO)", styles['Title']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"PO Number: {po_number}", styles['Normal']))
    elements.append(Paragraph(f"Date: {datetime.strptime(order_date, '%Y-%m-%d').strftime('%d %b %Y')}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Vendor
    elements.append(Paragraph("<b>Vendor/Supplier:</b>", styles['Heading2']))
    elements.append(Paragraph(f"{vendor['name']}", styles['Normal']))
    elements.append(Paragraph(f"{vendor['address']}", styles['Normal']))
    elements.append(Paragraph(f"Tel: {vendor['phone']}", styles['Normal']))
    elements.append(Paragraph(f"Email: {vendor['email']}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Buyer
    elements.append(Paragraph("<b>Buyer:</b>", styles['Heading2']))
    elements.append(Paragraph(f"{buyer['name']}", styles['Normal']))
    elements.append(Paragraph(f"{buyer['address']}", styles['Normal']))
    elements.append(Paragraph(f"Tel: {buyer['phone']}", styles['Normal']))
    elements.append(Paragraph(f"Email: {buyer['email']}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Order Details Table
    data = [["Item No.", "Description", "Quantity", "Unit Price (PHP)", "Total (PHP)"]]
    subtotal = 0
    for idx, row in sales_df.iterrows():
        total = row['total_qty'] * row['selling_price']
        subtotal += total
        data.append([
            idx+1,
            row['item_name'],
            row['total_qty'],
            f"{row['selling_price']:,.2f}",
            f"{total:,.2f}"
        ])

    table = Table(data, colWidths=[50, 200, 60, 100, 100], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(2,1),(2,-1),'RIGHT'),   # Quantity column right aligned
        ('ALIGN',(3,1),(4,-1),'RIGHT'),   # Unit Price and Total right aligned
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')
    ]))
    elements.append(table)
    elements.append(Spacer(1, 12))

    # Totals
    elements.append(Paragraph(f"Subtotal: PHP {subtotal:,.2f}", styles['Normal']))
    elements.append(Paragraph("GST: PHP 0.00 (No GST)", styles['Normal']))
    elements.append(Paragraph(f"Total Amount: PHP {subtotal:,.2f}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Pickup Date
    elements.append(Paragraph(f"Pickup Date: {pickup_date}", styles['Normal']))
    elements.append(Spacer(1, 32))
    elements.append(Paragraph("Authorized By:", styles['Normal']))
    elements.append(Paragraph("(Signature & Name)", styles['Normal']))

    # Build PDF
    doc.build(elements)
    return filename


# ---------------- PDF Generation for SOA ----------------

# Blk 3 Lot 5 West Wing Villas, North Belton QC
# -*- coding: utf-8 -*-

def generate_soa_pdf(customer_name, customer_id, start_date, end_date, soa_df):

    # Ensure start_date and end_date are strings
    if not isinstance(start_date, str):
        start_date = start_date.strftime("%Y-%m-%d")
    if not isinstance(end_date, str):
        end_date = end_date.strftime("%Y-%m-%d")

    # --- File name ---
    safe_name = customer_name.replace(" ", "_").replace("/", "_")
    filename = f"SOA_{start_date.replace('-', '')}_{end_date.replace('-', '')}_{safe_name}.pdf"

    # --- Build PDF ---
    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=40)
    styles = getSampleStyleSheet()
    elements = []

    # Header
    elements.append(Paragraph("STATEMENT OF ACCOUNT (SOA)", styles['Title']))
    elements.append(Paragraph(f"Customer: {customer_name} (ID: {customer_id})", styles['Normal']))
    elements.append(Paragraph(f"Period: {start_date} to {end_date}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Table Header
    data = [["Date", "Item", "Quantity", "Unit Price (PHP)", "Total (PHP)"]]

    # Table Rows
    total_amount = 0
    total_qty = 0
    for idx, row in soa_df.iterrows():
        qty = row['quantity']
        price = row['selling_price']
        total = row['total_sale']
        total_amount += total
        total_qty += qty

        data.append([
            str(row['date']),
            str(row['item_name']),
            qty,
            f"{price:,.2f}",
            f"{total:,.2f}"
        ])

    # Create Table
    table = Table(data, colWidths=[80, 180, 50, 90, 90], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(2,1),(2,-1),'RIGHT'),   # Quantity column right aligned
        ('ALIGN',(3,1),(4,-1),'RIGHT'),   # Unit Price and Total right aligned
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')
    ]))
    elements.append(table)
    elements.append(Spacer(1, 12))

    # Summary
    transaction_count = len(soa_df)
    elements.append(Paragraph(f"Transactions: {transaction_count}", styles['Normal']))
    elements.append(Paragraph(f"Total Quantity: {total_qty}", styles['Normal']))
    elements.append(Paragraph(f"Total Amount: PHP {total_amount:,.2f}", styles['Normal']))
    elements.append(Spacer(1, 24))

    # Footer
    elements.append(Paragraph("Thank you for choosing Steak Haven - Premium Quality Meat", styles['Normal']))

    # Build PDF
    doc.build(elements)
    return filename

# --- Add Price History Table Creation ---
def create_price_history_table2():
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, old_quantity INTEGER, new_price_quantity INTEGER, old_unit_cost REAL, old_selling_price REAL, new_unit_cost REAL, new_selling_price REAL, changed_by TEXT, timestamp TEXT)")
    conn.commit()
    conn.close()

# ---------------- Upload Tiered Pricing ----------------
def upload_tiered_pricing(uploaded_file):
    if uploaded_file is None:
        st.error("No file uploaded.")
        return

    # Determine file type and read accordingly
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    if file_ext == '.csv':
        df = pd.read_csv(uploaded_file)
    elif file_ext == '.xlsx':
        df = pd.read_excel(uploaded_file, engine='openpyxl')
    elif file_ext == '.xls':
        df = pd.read_excel(uploaded_file, engine='xlrd')
    else:
        raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")

    # Connect to the database
    conn = get_connection()
    cursor = conn.cursor()

    # Process each pricing tier in the file
    for _, row in df.iterrows():
        item_id = row['item_id']
        min_qty = row['min_qty']
        max_qty = row['max_qty'] if not pd.isna(row['max_qty']) else None
        price_per_unit = row['price_per_unit']
        label = row['label']

        # Check if record exists
        cursor.execute("""
            SELECT id FROM pricing_tiers
            WHERE item_id = ? AND min_qty = ? AND (max_qty IS ? OR max_qty = ?) AND label = ?
        """, (item_id, min_qty, max_qty, max_qty, label))
        existing = cursor.fetchone()

        if existing:
            # Update price_per_unit if record exists
            cursor.execute("""
                UPDATE pricing_tiers
                SET price_per_unit = ?
                WHERE id = ?
            """, (price_per_unit, existing[0]))
        else:
            # Insert new record if not found
            cursor.execute("""
                INSERT INTO pricing_tiers (item_id, min_qty, max_qty, price_per_unit, label)
                VALUES (?, ?, ?, ?, ?)
            """, (item_id, min_qty, max_qty, price_per_unit, label.strip().upper()))

    # Commit changes and close connection
    conn.commit()
    conn.close()
    st.success("Pricing Tiers updated or inserted successfully!")

# ---------------- CREATE TABLES ----------------
create_tables()
#create_price_history_table()

# ---------------- LOGOUT FUNCTION ----------------
def logout():
    st.session_state.logged_in = False
    st.session_state.menu = "Landing"
    st.session_state.username = ""

# ---------------- LOGIN PAGE ----------------
if not st.session_state.logged_in:
    if os.path.exists("icon.jpeg"):
        st.image("icon.jpeg", width=250)
    st.title("Welcome to Steak Haven Inventory")
    st.write("Your choice for premium quality meat")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "admin" and password == "1234":
            st.session_state.logged_in = True
            st.session_state.menu = "Home"
            st.session_state.username = username
            try:
                st.rerun()
            except AttributeError:
                st.rerun()
        else:
            st.error("Invalid credentials")

# ---------------- MAIN APP ----------------
elif st.session_state.logged_in:
    if os.path.exists("icon.jpeg"):
        st.sidebar.image("icon.jpeg", width=150)
    st.sidebar.title("Menu")
    st.sidebar.button("Logout", on_click=logout)
    st.sidebar.header("Settings")
    stock_threshold = st.sidebar.number_input("Set Stock Alert Threshold", min_value=0, value=5)

    with st.sidebar:
        # Main menu
        main_menu = option_menu(
            "Main Menu",
            ["Home", "Inventory", "Pricing", "Customer", "Reports"],
            icons=["house", "box", "list", "people", "bar-chart"],
            menu_icon="cast",
            default_index=0
        )

        # Submenu depending on main menu
        if main_menu == "Home":
            menu = option_menu("Home", ["Home"], icons=["house"])
        elif main_menu == "Inventory":
            menu = option_menu("Inventory", [
                "View Inventory",
                "Manage Stock",
                "File Upload (Items)",
                "Delete All Inventory"
            ], icons=["plus-circle", "list", "pencil", "upload", "trash"])
        elif main_menu == "Pricing":
            menu = option_menu("Pricing", [
                "View Pricing Tiers",
                "File Upload (Pricing)",
                "Manage Pricing Tiers",
                "Special Customer Prices"
            ], icons=["list", "upload", "pencil", "people"])
        elif main_menu == "Customer":
            menu = option_menu("Customer", [
                "Manage Customers",
                "View Sale for a Customer",
                "Add Customer",
                "Record Sale",
                "Customer Statement of Account",
                "Delete All Customers",
                "Special Pricing"
            ], icons=["person-plus", "people", "gear", "clipboard", "file-text", "trash", "people"])
        elif main_menu == "Reports":
            menu = option_menu("Reports", [
                "Profit/Loss Report",
                "View Audit Log",
                "Generate Purchase Order",
                "Price Change Impact Report"
            ], icons=["graph-up", "book", "file-earmark-text", "bar-chart"])

    st.session_state.menu = menu
    st.write(f"Selected: {main_menu} → {menu}")

## Aileen Added

    # ---------------- HOME ----------------
    if menu == "Home":
        st.title("Dashboard")
        items_df = view_items()
        sales_df = view_sales()
        if not items_df.empty:
            st.subheader("Inventory Summary")
            st.metric("Total Items", len(items_df))
            #st.metric("Total Stock Value", f"${(items_df['quantity'] * items_df['unit_cost']).sum():,.2f}")
            fig = px.bar(items_df, x='category', y='quantity', color='category', title="Stock by Category")
            st.plotly_chart(fig)
        if not sales_df.empty:
            st.subheader("Sales Summary")
            #st.metric("Total Sales", f"${sales_df['total_sale'].sum():,.2f}")
            #st.metric("Total Profit", f"${sales_df['profit'].sum():,.2f}")
            fig2 = px.line(sales_df, x='date', y='profit', title="Profit Trend Over Time")
            st.plotly_chart(fig2)

    # ---------------- ADD/UPDATE STOCK ----------------
    elif menu == "Manage Stock":
        st.title("Manage Stock")

        items_df = view_items()
        if items_df.empty:
            st.warning("No items found.")
        else:
            # Show current inventory list
            st.subheader("Current Inventory")
            #st.dataframe(items_df[['item_id','item_name','category','quantity','fridge_no']])

            styled_inventory = items_df[['item_id', 'item_name', 'category', 'quantity', 'fridge_no']].style.format({
                'quantity': '{:,.2f}'
            })
            st.dataframe(styled_inventory, width='stretch')

        # --- Collapsible section: Add/Update Stock ---
        with st.expander("➕ Add or Update Stock", expanded=False):
            existing_categories = sorted(items_df['category'].dropna().unique()) if not items_df.empty else []
            category_options = ["Add New"] + existing_categories

            # Build item options with "<item_id> - <item_name>"
            if not items_df.empty:
                item_options = ["Add New"] + [f"{row['item_id']} - {row['item_name']}" for _, row in items_df.iterrows()]
            else:
                item_options = ["Add New"]

            selected_item = st.selectbox("Select Item", item_options)

            current_stock = None
            if selected_item != "Add New":
                selected_item_id = int(selected_item.split(" - ")[0])
                selected_item_name = selected_item.split(" - ")[1]

                item_rows = items_df[items_df['item_name'] == selected_item_name]
                if not item_rows.empty:
                    st.session_state.selected_category = item_rows.iloc[0]['category']
                    category_name = st.session_state.selected_category

                    current_stock = item_rows['quantity'].sum()
                    st.info(f"Stock Currently On Hand: {current_stock}")

                    st.write("Per-Fridge Breakdown:")
                    st.dataframe(item_rows[['fridge_no','quantity']])

                    styled_inventory = item_rows[['fridge_no','quantity']].style.format({
                        'quantity': '{:,.2f}'
                    })
                    st.dataframe(styled_inventory, width='stretch')

                else:
                    st.warning(f"No records found for item '{selected_item}'.")
                    current_stock = None
            else:
                selected_category = st.selectbox("Select Category", category_options)
                category_name = selected_category
                if selected_item == "Add New" and selected_category == "Add New":
                    category_name = st.text_input("Enter New Category Name")

            item_name = (
                st.text_input("Enter New Item Name", value=st.session_state.item_name)
                if selected_item == "Add New"
                else selected_item.split(" - ")[1]
            )
            item_id = selected_item.split(" - ")[0]
            #quantity = st.number_input("Quantity to Add", min_value=0.5, value=st.session_state.quantity)
            quantity = st.number_input("Quantity", min_value=0.5, value=0.5, step=0.1, format="%.2f")
            fridge_no = st.text_input("Fridge No", value=0)

            if st.button("Save"):
                if item_id and category_name:
                    qty_value = float(quantity)
                    add_or_update_item(item_id, item_name.strip().upper(), category_name.strip().upper(), qty_value, fridge_no, st.session_state.username)
                    st.success(f"Item '{item_name}' in category '{category_name}' updated successfully!")
                    st.rerun()
                else:
                    st.error("Please provide valid item and category names.")

        # --- Collapsible section: Delete Item ---
        with st.expander("🗑️ Delete Item", expanded=False):
            if items_df.empty:
                st.warning("No items to delete.")
            else:
                selected_label = "Select Item to Delete"
                items_df['label'] = items_df.apply(lambda row: f"{row['item_id']} - {row['category']} - {row['item_name']}", axis=1)
                selected_label = st.selectbox("Select Item to Delete", items_df['label'])
                item_id = int(selected_label.split(" - ")[0])
                if st.button("Delete"):
                    delete_item(item_id, st.session_state.username)
                    st.success(f"Item with ID {item_id} deleted successfully!")
                    st.rerun()



    elif menu == "Add/Update Stock":
        st.title("Add or Update Stock")
        items_df = view_items()
        existing_categories = sorted(items_df['category'].dropna().unique()) if not items_df.empty else []

        # Build item options with "<item_id> - <item_name>"
        if not items_df.empty:
            item_options = ["Add New"] + [
                f"{row['item_id']} - {row['item_name']}" for _, row in items_df.iterrows()
            ]
        else:
            item_options = ["Add New"]

        category_options = ["Add New"] + existing_categories

        # Session state initialization
        if 'item_name' not in st.session_state: st.session_state.item_name = ""
        if 'category_name' not in st.session_state: st.session_state.category_name = ""
        if 'quantity' not in st.session_state: st.session_state.quantity = 1
        if 'fridge_no' not in st.session_state: st.session_state.fridge_no = ""
        if 'selected_item' not in st.session_state: st.session_state.selected_item = "Add New"
        if 'selected_category' not in st.session_state: st.session_state.selected_category = "Add New"
        if 'show_next_action' not in st.session_state: st.session_state.show_next_action = False

        selected_item = st.selectbox(
            "Select Item",
            item_options,
            index=item_options.index(st.session_state.selected_item) if st.session_state.selected_item in item_options else 0
        )

        current_stock = None
        if selected_item != "Add New":
            # Extract item_id back from "<item_id> - <item_name>"
            selected_item_id = int(selected_item.split(" - ")[0])
            selected_item_name = selected_item.split(" - ")[1]

            # Get all rows for this item_id (could be multiple fridges)
            item_rows = items_df[items_df['item_name'] == selected_item_name]

            if not item_rows.empty:
                # Category is the same across rows
                st.session_state.selected_category = item_rows.iloc[0]['category']
                st.markdown(
                    f"<div style='background-color:#003366;color:white;padding:8px;border-radius:4px;'>Category: {st.session_state.selected_category}</div>",
                    unsafe_allow_html=True
                )
                category_name = st.session_state.selected_category

                num_records = len(item_rows)
                st.write(f"Number of records in item_rows: {num_records}")

                # ✅ Sum all quantities across fridge_no
                current_stock = item_rows['quantity'].sum()

                # Optional: show per-fridge breakdown
                st.write("Per-Fridge Breakdown:")
                st.dataframe(item_rows[['fridge_no', 'quantity']])
            else:
                st.warning(f"No records found for item '{selected_item}'.")
                current_stock = None

        if current_stock is not None:
            st.info(f"Stock Currently On Hand: {current_stock}")
        else:
            selected_category = st.selectbox(
                "Select Category",
                category_options,
                index=category_options.index(st.session_state.selected_category) if st.session_state.selected_category in category_options else 0
            )
            category_name = selected_category
            if selected_item == "Add New" and selected_category == "Add New":
                category_name = st.text_input("Enter New Category Name")
        
        item_name = (
            st.text_input("Enter New Item Name", value=st.session_state.item_name)
            if selected_item == "Add New"
            else selected_item.split(" - ")[1]  # extract item_name part
        )
        item_id = selected_item.split(" - ")[0]  # extract item_id part
        quantity = st.number_input("Quantity to Add", min_value=1, value=st.session_state.quantity)
        fridge_no = st.text_input("Fridge No", value=st.session_state.fridge_no)

        if st.button("Save"):
            if item_id and category_name:
                #st.write(f"calling function - {item_id} and {quantity}")
                add_or_update_item(item_id, item_name.strip().upper(), category_name.strip().upper(), quantity, fridge_no, st.session_state.username)
                st.success(f"Item '{item_name}' in category '{category_name}' updated successfully!")
                st.session_state.show_next_action = True
            else:
                st.error("Please provide valid item and category names.")

    # ---------------- File Upload (Items) ----------------
    elif menu == "File Upload (Items)":
        st.title("File Upload (Items)")
        uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file is not None:
            # Read file based on extension
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            if file_ext == ".csv":
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            # Validate columns
            required_cols = ["item_name", "category", "quantity", "fridge_no"]
            if all(col in df.columns for col in required_cols):
                conn = get_connection()
                cursor = conn.cursor()
                for _, row in df.iterrows():
                    add_or_update_item(None, row["item_name"].strip().upper(), row["category"].strip().upper(), row["quantity"], row["fridge_no"], st.session_state.username)
                conn.commit()
                conn.close()
                st.success("Items updated or inserted successfully!")
            else:
                st.error(f"Missing required columns: {required_cols}")

    # ---------------- UPLOAD PRICING ----------------
    elif menu == "File Upload (Pricing)":
        st.title("File Upload (Pricing)")
        uploaded_file = st.file_uploader("Upload Pricing CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file:
            upload_tiered_pricing(uploaded_file)
            
    # ---------------- View Tiered Pricing ------------------
    elif menu == "View Pricing Tiers":
        st.title("View Pricing Tiers")
        # show the tiered pricing
        data = view_pricing()
        if data.empty:
            st.warning("No pricing found.")
        else:
            paged_df, total_pages = paginate_dataframe(data, page_size=100)
            st.write(f"Showing {len(paged_df)} rows (Page size: 100)")


            st.dataframe(
                paged_df.style
                .format({"price_per_unit": "{:,.2f}"}),
                width="stretch"
                )
            csv_inventory = data.to_csv(index=False)
            st.download_button("Download Pricing Tiers CSV", data=csv_inventory, file_name="Pricing tiers.csv", mime="text/csv")               

    # ---------------- Update Pricing Manually ---------
    elif menu == "Update Pricing Manually":
        update_pricing_tiers_ui()
        
    # ---------------- Manage Pricing Tiers -----------
    elif menu == "Manage Pricing Tiers":
        manage_pricing_tiers()

    # ---------------- Special Customer Prices ----------
    elif menu == "Special Customer Prices":
        manage_special_customer_pricing()
    # ---------------- Special Pricing  -----------
    elif menu == "Special Pricing":
        conn = get_connection()
        cur = conn.cursor()

        # --- Select Customer ---
        cur.execute("SELECT id, name FROM customers")
        customers = cur.fetchall()
        customer_options = {name: cid for cid, name in customers}
        selected_customer = st.selectbox("Select Customer", list(customer_options.keys()))

        # --- Select Item ---
        cur.execute("SELECT id, label FROM pricing_tiers GROUP BY item_id")
        items = cur.fetchall()
        item_options = {label: iid for iid, label in items}
        selected_item = st.selectbox("Select Item", list(item_options.keys()))

        qty = st.number_input("Quantity", min_value=1, value=1)

        # --- Compute Prices immediately ---
        customer_id = customer_options[selected_customer]
        item_id = item_options[selected_item]

        base_price = get_base_price(item_id, qty)
        final_price = get_customer_adjusted_price(customer_id, item_id, qty)

        # --- Show summary above table ---
        st.write(f"**Final Price for {selected_customer}:** Base: {base_price}, special: {final_price:.2f}")

        # --- Fetch Special Pricing (if exists) ---
        cur.execute("""
            SELECT cpl.id, cpl.customer_id, cpl.item_id, cpl.custom_price
            FROM customer_price_list cpl
            WHERE cpl.customer_id = ? AND cpl.item_id = ?
        """, (customer_id, item_id))
        special_prices = cur.fetchall()

        # --- Build table with base + special price ---
        if special_prices:
            st.write("### Pricing Details")
            df = pd.DataFrame(special_prices, columns=["ID", "Customer ID", "Item ID", "Special Price"])
            df["Item Name"] = selected_item
            df["Base Price"] = f"{base_price:,.2f}"
            df["Special Price"] = df["Special Price"].apply(lambda x: f"{x:,.2f}")
            df = df[["Item Name", "Base Price", "Special Price"]]
            st.dataframe(df)
        else:
            # Show table with only base price if no special pricing exists
            st.write("### Pricing Details")
            df = pd.DataFrame([{"Item Name": selected_item, "Base Price": base_price, "Special Price": None}])
            df["Base Price"] = f"{base_price:,.2f}"
            df = df[["Item Name", "Base Price", "Special Price"]]
            st.dataframe(df)
 
    # ---------------- VIEW INVENTORY ----------------
    elif menu == "View Inventory":
        st.title("Inventory Data")
        data = view_items()
        if data.empty:
            st.warning("No items found.")
        else:
            # Toggle between views
            view_mode = st.radio(
                "Select View Mode",
                ["Per-Fridge View", "Aggregated View"],
                index=0
            )

            def highlight_low_stock(row):
                return ['background-color: #CC0000' if row['quantity'] < stock_threshold else '' for _ in row]

            if view_mode == "Per-Fridge View":
                # ✅ Add fridge filter
                fridge_options = sorted(data["fridge_no"].unique())
                selected_fridge = st.selectbox("Filter by Fridge No", ["All"] + fridge_options)

                if selected_fridge != "All":
                    data = data[data["fridge_no"] == selected_fridge]

                # ✅ Order by fridge_no
                data = data.sort_values(by="fridge_no")

                # Paginate after filtering & sorting
                paged_df, total_pages = paginate_dataframe(data, page_size=100)
                st.write(f"Showing {len(paged_df)} rows (Page size: 100)")

                st.dataframe(
                    paged_df.style
                    .apply(highlight_low_stock, axis=1)
                    .set_properties(subset=["item_id","quantity"], **{"text-align": "center"}),
                    width='stretch'
                )

                # Download per-fridge CSV
                csv_inventory = data.to_csv(index=False)
                st.download_button(
                    "Download Per-Fridge Inventory CSV",
                    data=csv_inventory,
                    file_name="inventory_per_fridge.csv",
                    mime="text/csv"
                )

            else:  # Aggregated View
                aggregated_df = (
                    data.groupby(["item_name", "category"], as_index=False)
                        .agg({"quantity": "sum"})
                        .rename(columns={"quantity": "total_stock"})
                )
                st.write(f"Showing {len(aggregated_df)} aggregated rows")
                st.dataframe(
                    aggregated_df.style
                    .format({"total_stock": "{:,.0f}"})
                    .set_properties(subset=["total_stock"], **{"text-align": "left"}),
                    width='stretch'
                )

                # Download aggregated CSV
                csv_aggregated = aggregated_df.to_csv(index=False)
                st.download_button(
                    "Download Aggregated Inventory CSV",
                    data=csv_aggregated,
                    file_name="inventory_aggregated.csv",
                    mime="text/csv"
                )

    # ---------------- VIEW AUDIT LOG ----------------
    elif menu == "View Audit Log":
        st.title("Inventory Audit Log")
        start_date = st.date_input("Start Date")
        end_date = st.date_input("End Date")

        if st.button("Filter"):
            audit_df = view_audit_log(start_date, end_date)
        else:
            audit_df = view_audit_log()

        if audit_df.empty:
            st.warning("No audit records found.")
        else:
            paged_audit, total_pages = paginate_dataframe(audit_df, page_size=20)
            st.write(f"Showing {len(paged_audit)} rows (Page size: 20)")
            st.dataframe(paged_audit)
            csv_audit = audit_df.to_csv(index=False)
            st.download_button("Download Audit Log CSV", data=csv_audit, file_name="audit_log.csv", mime="text/csv")

    # ---------------- DELETE ITEM ----------------
    elif menu == "Delete Item":
        st.title("Delete Item")
        data = view_items()
        if data.empty:
            st.warning("No items to delete.")
        else:
            data['label'] = data.apply(lambda row: f"{row['item_id']} - {row['category']} - {row['item_name']}", axis=1)
            selected_label = st.selectbox("Select Item to Delete", data['label'])
            item_id = int(selected_label.split(" - ")[0])
            if st.button("Delete"):
                delete_item(item_id, st.session_state.username)
                st.success(f"Item with ID {item_id} deleted successfully!")
                st.rerun()

    # ---------------- DELETE ALL INVENTORY ----------------
    elif menu == "Delete All Inventory":
        st.title("Delete All Inventory")
        if st.button("Confirm Delete All Inventory"):
            conn = get_connection()
            conn.execute('DELETE FROM items')
            conn.commit()
            conn.close()
            st.success("All inventory and audit logs deleted successfully!")

    # ---------------- DELETE ALL INVENTORY ----------------
    elif menu == "Delete Pricing Tiers":
        st.title("Delete All Pricing Tiers")
        if st.button("Confirm Delete All Pricing Tiers"):
            conn = get_connection()
            conn.execute('DELETE FROM pricing_tiers')
            conn.commit()
            conn.close()
            st.success("All Pricing Tiers deleted successfully!")

    # ---------------- DELETE ALL CUSTOMERS ----------------
    elif menu == "Delete All Customers":
        st.title("Delete All Customers")
        if st.button("Confirm Delete All Customers"):
            conn = get_connection()
            conn.execute('DELETE FROM customers')
            conn.commit()
            conn.close()
            st.success("All Customers deleted successfully!")

    # ---------------- ADD CUSTOMER ----------------
    elif menu == "Add Customer":
        st.title("Add New Customer")
        name = st.text_input("Customer Name")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        # validate that email is in proper format
        if email and "@" not in email:
            st.error("Please enter a valid email address.")
        address = st.text_area("Address")
        group_id = st.text_input("group_id")
        if st.button("Save Customer"):
            conn = get_connection()
            conn.execute('INSERT INTO customers (name, phone, email, address, group_id) VALUES (?, ?, ?, ?, ?)',
                         (name.upper(), phone, email.upper(), address.upper(), group_id.strip().upper()))
            conn.commit()
            conn.close()
            st.success(f"Customer '{name}' added successfully!")

    # ---------------- VIEW CUSTOMERS ----------------
    elif menu == "Manage Customers":
        st.title("Customer List")
        data = view_customers()
        if data.empty:
            st.warning("No customers found.")
        else:
            #paged_customers, total_pages = paginate_dataframe(data, page_size=20)
            #st.write(f"Showing {len(paged_customers)} rows (Page size: 20)")
            #st.dataframe(paged_customers)
        # ---- maintain customers -----

            customer_label = st.selectbox(
            "Select Customer",
            data.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])

            # Show existing tiers
            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
            customers = cursor.fetchall()
            conn.close()

            if customers:
                st.subheader("Existing Customers")
                customers_df = pd.DataFrame(customers, columns=customers[0].keys())
                st.dataframe(customers_df, width='stretch')
            else:
                st.info("No customers defined yet.")

            st.markdown("---")

            # ✅ Collapsible Add/Update section
            with st.expander("➕ Add / Update Customers", expanded=False):
                name = st.text_input("Name", value="")
                phone = st.text_input("Contact No", value="")
                email = st.text_input("Email Address", value="")
                address = st.text_input("Address", value="")

                if st.button("Save Customer"):
                    conn = get_connection()
                    cursor = conn.cursor()
                    if validate_if_customer_exist(name):   # if existing, means it's an update
                        cursor.execute(
                            "UPDATE customers set phone=?, email=?, address=? where name=?",
                            (phone.strip(), email.strip().upper(), address.strip().upper(), name.strip().upper())
                        ) 
                        st.write(f"{phone} {email} {address}")
                        conn.commit()
                        conn.close()
                        st.success(f"Updated existing profile for {name}.")
                        st.rerun()
                    else:
                        cursor.execute(
                            "INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)",
                            (name.strip().upper(), phone.strip(), email.strip().upper(), address.strip().upper())
                        )                
                        conn.commit()
                        conn.close()
                        st.success("Added new Customer successfully!")
                        st.rerun()


            # ✅ Collapsible Delete section
            if customers:
                with st.expander("🗑️ Delete a Customer", expanded=False):
                    st.subheader("Delete a Customer")
                    customer_to_delete = "Select Customer to Delete" 
                    customer_ids = ["Select Customer to Delete"] + [
                        f"{t['id']} - {t['name']}" for t in customers
                    ]
                    customer_to_delete = st.selectbox("Select Customer to Delete", customer_ids)
                    if st.button("Delete Customer"):
                        customer_id = int(customer_to_delete.split()[0])
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM customers WHERE id=?", (customer_id,))
                        conn.commit()
                        conn.close()
                        st.success("Customer deleted successfully!")
                        st.rerun()

    # ---------------- VIEW SALES FOR A CUSTOMER ----------------
    elif menu == "View Sale for a Customer":
        st.title("View Sales for a Customer")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            sales_df = view_sales_by_customers(customer_id)
            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                paged_sales, total_pages = paginate_dataframe(sales_df, page_size=20)
                st.write(f"Showing {len(paged_sales)} rows (Page size: 20)")

                # ✅ Format total_sale with 2 decimals              
                styled_sales = (
                    paged_sales.style
                    .format({
                        "total_sale": "{:,.2f}",
                        "selling_price": "{:,.2f}",
                        "cost": "{:,.2f}",
                        "profit": "{:,.2f}"
                    })
                )

                st.dataframe(styled_sales, width='stretch')
                csv_sales = sales_df.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")
    
    # ---------------- Generate PO for Customer based on Sales Date ----------------
    elif menu == "Generate Purchase Order":
        st.title("Generate Purchase Order (PO)")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])

            # select order date from the list of customer orders
            sales_df = view_sales_by_customers(customer_id)
            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                order_dates = sales_df['date'].unique()
                order_date = st.selectbox("Select Order Date", order_dates)

                # normalize order_date
                if isinstance(order_date, date):
                    order_date_sql = order_date.strftime("%Y-%m-%d")
                else:
                    order_date_sql = str(order_date)
                    
                pickup_date = st.date_input("Pickup Date")
                # normalize pickup_date (st.date_input returns a date)
                pickup_date_sql = pickup_date.strftime("%Y-%m-%d")

                #order_date = datetime.strptime(order_date_str, "%Y-%m-%d").date()

            if st.button("Generate PO"):
                pdf_file = generate_po_pdf(order_date_sql, customer_id, pickup_date_sql)
                with open(pdf_file, "rb") as f:
                    st.download_button("Download PO PDF", data=f, file_name=pdf_file, mime="application/pdf")

    # ---------------- RECORD SALE ----------------
    ## Added customer id dropdown
    elif menu == "Record Sale":
        st.title("Record Sale")
        items_df = view_items()
        customers_df = view_customers()

        if items_df.empty:
            st.warning("No items available for sale.")
        elif customers_df.empty:
            st.warning("No customers available. Please add a customer first.")
        else:
            # Build display labels: "<item_id> - <item_name>"
            items_df["display"] = items_df.apply(
                lambda row: f"{row['item_id']} - {row['item_name']}", axis=1
            )

            # Item selection
            item_display = st.selectbox(
                "Select Item",
                ["Select item"] + items_df["display"].tolist()
            )

            total_qty = 0
            selected_item_id, selected_item_name = None, None
            if item_display != "Select item":
                selected_item_id = int(item_display.split(" - ")[0])
                selected_item_name = item_display.split(" - ")[1]

            # Customer selection
            customer_label = st.selectbox(
                "Select Customer",
                ["Select customer"] + customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1).tolist()
            )
            if customer_label == "Select customer":
                st.warning("Please select a valid customer.")
            else:
                customer_id = int(customer_label.split(" - ")[0])
                customer_name = customer_label.split(" - ")[1]
                st.success(f"Selected customer: ID={customer_id}, Name={customer_name}")

            # Quantity input
            quantity = st.number_input("Quantity Sold", min_value=1)

            if customer_label != "Select customer" and item_display != "Select item":
                total_qty = get_total_qty(selected_item_name)
                st.info(f"Stock Currently On Hand: {total_qty}")
                if total_qty < quantity and quantity != 0:
                    st.error("Not enough stock")

                base_price = get_base_price(selected_item_id, quantity)
                final_price = get_customer_adjusted_price(customer_id, selected_item_id, quantity)

                # --- Show summary above table ---
                st.info(f"**Final Price for {customer_name}:** Base: {base_price:.2f}, Special Price: {final_price:.2f}")

                # Pricing choice
                price_choice = st.radio(
                    "Select pricing method",
                    ("Base Price", "Special Price", "Override Price")
                )

                chosen_unit_price = None

                if price_choice == "Base Price":
                    chosen_unit_price = base_price
                elif price_choice == "Special Price":
                    chosen_unit_price = final_price
                elif price_choice == "Override Price":
                    chosen_unit_price = st.number_input("Enter custom per unit price", min_value=0.0, format="%.2f")

                # Calculate total
                if chosen_unit_price is not None:
                    total_sale = quantity * chosen_unit_price
                    st.success(f"Chosen Price per Unit: PHP {chosen_unit_price:,.2f}")
                    st.success(f"Calculated Total Sale: PHP {total_sale:,.2f}")

                # Record Sale button
                if st.button("Record Sale"):
                    msg = record_sale(
                        selected_item_id,
                        quantity,
                        st.session_state.username,
                        customer_id,
                        chosen_unit_price  # Pass the chosen price
                    )
                    st.subheader("Sales Records")
                    sales_df = view_sales_by_customer(customer_id)
                    if not sales_df.empty:
                        paged_sales, total_pages = paginate_dataframe(sales_df, page_size=100)
                        st.write(f"Showing {len(paged_sales)} rows (Page size: 100)")

                        styled_sales = paged_sales.style.format({
                            "selling_price": "{:,.2f}",
                            "total_sale": "{:,.2f}",
                            "cost": "{:,.2f}",
                            "profit": "{:,.2f}"
                        })
                        st.dataframe(styled_sales, width='stretch')

                        csv_sales = sales_df.to_csv(index=False)
                        st.download_button("Download Sales CSV", data=csv_sales, file_name="sales.csv", mime="text/csv")
                    else:
                        st.info("No sales recorded yet.")
                    st.success(msg)

#                else:
#                    st.error("No pricing tier found for this item/quantity.")

    # ---------------- PROFIT/LOSS REPORT ----------------
    elif menu == "Profit/Loss Report":
        st.title("Profit/Loss Report")
        sales_df = view_sales()
        if sales_df.empty:
            st.warning("No sales data available.")
        else:
            total_sales = sales_df['total_sale'].sum()
            total_cost = sales_df['cost'].sum()
            total_profit = sales_df['profit'].sum()
            st.metric("Total Sales", f"${total_sales:,.2f}")
            st.metric("Total Cost", f"${total_cost:,.2f}")
            st.metric("Total Profit", f"${total_profit:,.2f}")
            paged_sales, total_pages = paginate_dataframe(sales_df, page_size=20)
            st.write(f"Showing {len(paged_sales)} rows (Page size: 20)")
            st.dataframe(paged_sales)
            csv_sales = sales_df.to_csv(index=False)
            st.download_button("Download Sales CSV", data=csv_sales, file_name="sales.csv", mime="text/csv")
## Aileen Added

    # ---------------- CUSTOMER SOA ----------------
    elif menu == "Customer Statement of Account":
        st.title("Customer Statement of Account")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            # Customer selection
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            customer_name = customer_label.split(" - ")[1]

            # --- Default start and end of current month ---
            today = date.today()
            start_of_month = today.replace(day=1)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end_of_month = today.replace(day=last_day)

            # Date filters with defaults
            start_date = st.date_input("Start Date", value=start_of_month)
            end_date = st.date_input("End Date", value=end_of_month)

            # Fetch filtered sales data
            def view_sales_by_customer_and_date(customer_id, start_date=None, end_date=None):
                conn = get_connection()
                if start_date and end_date:
                    query = """
                    SELECT date, item_id, item_name, quantity, selling_price, total_sale, overridden FROM sales
                    WHERE customer_id = ? AND date BETWEEN ? AND ?
                    """
                    df = pd.read_sql_query(query, conn, params=(customer_id, start_date, end_date))
                else:
                    query = "SELECT date, item_id, item_name, quantity, selling_price, total_sale, overridden FROM sales WHERE customer_id = ?"
                    df = pd.read_sql_query(query, conn, params=(customer_id,))
                conn.close()
                return df

            # Display filtered table
            sales_customer = view_sales_by_customer_and_date(customer_id, start_date, end_date)
            if sales_customer.empty:
                st.warning("No sales records found for this customer in the selected period.")
            else:
                st.subheader("Sales Records of Selected Customer")
                paged_sales_customer, total_pages = paginate_dataframe(sales_customer, page_size=20)
                st.write(f"Showing {len(paged_sales_customer)} rows (Page size: 20)")

                # ✅ Format selling_price and total_sale with commas and 2 decimals
                styled_sales = paged_sales_customer.style.format({
                    "selling_price": "{:,.2f}",
                    "total_sale": "{:,.2f}",
                    "cost": "{:,.2f}",
                    "profit": "{:,.2f}"
                })
                st.dataframe(styled_sales, width='stretch')

                # Download CSV
                csv_sales = sales_customer.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")

                # Generate SOA PDF
                if st.button("Generate SOA"):
                    pdf_file = generate_soa_pdf(customer_name, customer_id, start_date, end_date, sales_customer)
                    with open(pdf_file, "rb") as f:
                        st.download_button("Download SOA PDF", data=f, file_name=pdf_file, mime="application/pdf")

    # --- New Menu Options ---
    # --- Enhanced View Price History with Pagination and CSV Export ---
    elif menu == "View Price History2":
        st.title("Price History")
        conn = get_connection()
        df = pd.read_sql_query('SELECT ph.timestamp, i.item, ph.old_quantity, ph.new_price_quantity, ph.old_unit_cost, ph.old_selling_price, ph.new_unit_cost, ph.new_selling_price, ph.changed_by FROM price_history ph JOIN items i ON ph.item_id = i.id ORDER BY ph.timestamp DESC', conn)
        conn.close()
        if df.empty:
            st.warning("No price changes recorded")
        else:
            paged_df, total_pages = paginate_dataframe(df, page_size=20)
            st.write(f"Showing {len(paged_df)} rows (Page size: 20)")
            st.dataframe(paged_df.style.format({"old_unit_cost": "{:,.2f}", "old_selling_price": "{:,.2f}", "new_unit_cost": "{:,.2f}", "new_selling_price": "{:,.2f}"}))
            csv_data = df.to_csv(index=False)
            st.download_button("Download Price History CSV", data=csv_data, file_name="price_history.csv", mime="text/csv")

    # --- Enhanced Price Change Impact Report with Pagination and CSV Export ---
    elif menu == "Price Change Impact Report2":
        st.title("Price Change Impact Report")
        items_df = view_items()
        if items_df.empty:
            st.warning("No items available")
        else:
            item = st.selectbox("Select Item", items_df['item'])
            conn = get_connection()
            history_df = pd.read_sql_query('SELECT * FROM price_history WHERE item_id=(SELECT id FROM items WHERE item=?) ORDER BY timestamp', conn, params=(item,))
            if history_df.empty:
                st.warning("No price changes recorded for this item")
            else:
                st.subheader("Price Change Timeline")
                paged_history, total_pages = paginate_dataframe(history_df, page_size=20)
                st.write(f"Showing {len(paged_history)} rows (Page size: 20)")
                st.dataframe(paged_history)
                csv_history = history_df.to_csv(index=False)
                st.download_button("Download Impact Report CSV", data=csv_history, file_name="impact_report.csv", mime="text/csv")
                for idx, row in history_df.iterrows():
                    st.markdown(f"### Change on {row['timestamp']}: {row['old_selling_price']} → {row['new_selling_price']}")
                    before_sales = pd.read_sql_query('SELECT * FROM sales WHERE item=? AND date<?', conn, params=(item, row['timestamp']))
                    after_sales = pd.read_sql_query('SELECT * FROM sales WHERE item=? AND date>=?', conn, params=(item, row['timestamp']))
                    st.write("**Before Change:**")
                    st.dataframe(before_sales)
                    st.write("**After Change:**")
                    st.dataframe(after_sales)
            conn.close()