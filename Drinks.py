import streamlit as st
from streamlit_option_menu import option_menu
import pandas as pd
import plotly.express as px
import os
import calendar
from datetime import datetime, date

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Import Supabase DB functions
from db_supabase import (
    view_items, add_or_update_item, delete_item, delete_all_inventory, get_total_qty,
    view_customers, validate_if_customer_exist, save_customer, update_customer, delete_customer, delete_all_customers,get_customer,
    view_pricing, get_price_list, add_price, update_price, delete_price, validate_special_price_exist, upload_tiered_pricing_to_db, 
    get_pricing_tiers, save_pricing_tier, delete_pricing_tier, get_items_for_pricing, get_special_price,
    get_base_price, get_customer_adjusted_price, get_po_sequence,
    view_sales, view_sales_by_customer, record_sale, get_sales_by_customer,
    view_audit_log, create_price_history_entry
)

# ---------------- SESSION STATE INIT ----------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'menu' not in st.session_state:
    st.session_state.menu = "Landing"
if 'username' not in st.session_state:
    st.session_state.username = ""

if "item_name" not in st.session_state:
    st.session_state.item_name = ""
if "category" not in st.session_state:
    st.session_state.category = ""
if "quantity" not in st.session_state:
    st.session_state.quantity = 1
if "fridge_no" not in st.session_state:
    st.session_state.fridge_no = ""

# ---------------- FUNCTIONS ----------------
def upload_tiered_pricing(uploaded_file):
    if uploaded_file is None:
        st.error("No file uploaded.")
        return

    # Determine file type and read accordingly
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    if file_ext == '.csv':
        df = pd.read_csv(uploaded_file)
    elif file_ext in ['.xlsx', '.xls']:
        df = pd.read_excel(uploaded_file, engine='openpyxl' if file_ext == '.xlsx' else 'xlrd')
    else:
        raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")

    skipped_rows = upload_tiered_pricing_to_db(df)

    if skipped_rows:
        st.warning(f"Skipped rows with invalid item_id(s): {skipped_rows}")
    else:
        st.success("Pricing Tiers updated or inserted successfully!")

# ----------------- Manage Pricing Tiers -----------------
def manage_pricing_tiers():
    st.title("Manage Pricing Tiers")

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
    tiers = get_pricing_tiers(item_id)
    if not tiers.empty:
        st.subheader("Existing Pricing Tiers")
        tiers["max_qty"] = tiers["max_qty"].fillna("∞")
        tiers["price_per_unit"] = tiers["price_per_unit"].map(lambda x: f"{x:.2f}")
        st.dataframe(tiers, width='stretch')
    else:
        st.info("No pricing tiers defined for this item yet.")

    st.markdown("---")

    # Add/Update section
    with st.expander("➕ Add / Update Pricing Tier", expanded=False):
        min_qty = st.number_input("Minimum Quantity", min_value=1)
        max_qty = st.number_input("Maximum Quantity (0 = unlimited)", min_value=0)
        price_per_unit = st.number_input("Price per Unit", min_value=0.0, format="%.2f")
        label = st.text_input("Tier Label (optional)", value=item_name)

        if st.button("Save Tier"):
            result = save_pricing_tier(item_id, min_qty, max_qty, price_per_unit, label)
            if result == "updated":
                st.success(f"Updated existing pricing tier for {item_name}.")
            else:
                st.success("Added new Pricing tier successfully!")
            st.rerun()

    # Delete section
    if not tiers.empty:
        with st.expander("🗑️ Delete a Tier", expanded=False):
            st.subheader("Delete a Tier")
            tier_ids = ["Select Tier to Delete"] + [
                f"{t['id']} (min {t['min_qty']}, max {t['max_qty'] if t['max_qty'] is not None else '∞'})"
                for _, t in tiers.iterrows()
            ]
            tier_to_delete = st.selectbox("Select Tier to Delete", tier_ids)
            if st.button("Delete Tier") and tier_to_delete != "Select Tier to Delete":
                tier_id = int(tier_to_delete.split()[0])
                delete_pricing_tier(tier_id)
                st.success("Tier deleted successfully!")
                st.rerun()

# ------ Manage Special Customer Pricing ------ 
def manage_special_customer_pricing():
    st.subheader("Manage Special Customer Price List")
    price_list_df = get_price_list()
    if price_list_df.empty:
        st.warning("No special customer pricing found.")
    else:
        st.dataframe(price_list_df)

    st.markdown("---")

    # Add/Update section
    with st.expander("➕ Add / Update Special Customer Pricing", expanded=False):
        customers_df = view_customers()
        items_df = view_items()

        customer_options = ["Select customer"] + [f"{row['id']} - {row['name']}" for _, row in customers_df.iterrows()]
        item_options = ["Select item"] + [f"{row['item_id']} - {row['item_name']}" for _, row in items_df.iterrows()]

        selected_customer = st.selectbox("Customer", customer_options, index=0)
        selected_item = st.selectbox("Item", item_options, index=0)
        custom_price = st.number_input("Custom Price", min_value=0.0, format="%.2f")

        if st.button("Save Special Price"):
            customer_id = None
            item_id = None
            if selected_customer != "Select customer":
                customer_id = int(selected_customer.split(" - ")[0])
            if selected_item != "Select item":
                item_id = int(selected_item.split(" - ")[0])

            if validate_special_price_exist(customer_id, item_id):
                update_price(customer_id, item_id, custom_price)
                st.success(f"Updated existing special pricing for customer {customer_id}.")
                st.rerun()
            else:
                add_price(customer_id, item_id, custom_price)
                st.success(f"Added new special pricing for customer {customer_id}.")
                st.rerun()

    # Delete section
    with st.expander("🗑️ Delete Special Customer Pricing", expanded=False):
        st.subheader("Delete a Special Customer Price")
        price_list_df = get_price_list()
        if not price_list_df.empty:
            record_options_del = ["Select record"] + [
                f"{row['id']} - {row['customer_name']} - {row['item_name']}"
                for _, row in price_list_df.iterrows()
            ]
            selected_record_del = st.selectbox("Select record to delete", record_options_del, index=0)
            if selected_record_del != "Select record":
                record_id = int(selected_record_del.split(" - ")[0])
                if st.button("Delete Price"):
                    delete_price(record_id)
                    st.success("Price deleted.")
                    st.rerun()

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

# ---------------- LOGOUT FUNCTION ----------------
def logout():
    st.session_state.logged_in = False
    st.session_state.menu = "Landing"
    st.session_state.username = ""

# ---------------- LOGIN PAGE ----------------
if not st.session_state.logged_in:
    if os.path.exists("icon.jpeg"):
        st.image("icon.jpeg", width=250)
    st.title("Welcome to Diane's Wholesale Inventory")
    #st.write("Your choice for premium quality meat")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "admin" and password == "1234":
            st.session_state.logged_in = True
            st.session_state.menu = "Home"
            st.session_state.username = username
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
        main_menu = option_menu(
            "Main Menu",
            ["Home", "Inventory", "Pricing", "Customer", "Reports"],
            icons=["house", "box", "list", "people", "bar-chart"],
            menu_icon="cast",
            default_index=0
        )
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
                "View Special Pricing",
                "Manage Special Customer Prices"
            ], icons=["list", "upload", "pencil", "people", "clipboard"])
        elif main_menu == "Customer":
            menu = option_menu("Customer", [
                "Manage Customers",
                "View Sale for a Customer",
                "Record Sale",
                "Customer Statement of Account",
                "Delete All Customers"
            ], icons=["person-plus", "people", "clipboard", "file-text", "trash"])
        elif main_menu == "Reports":
            menu = option_menu("Reports", [
                "Profit/Loss Report",
                "View Audit Log",
                "Generate Purchase Order",
                "Price Change Impact Report"
            ], icons=["graph-up", "book", "file-earmark-text", "bar-chart"])

    st.session_state.menu = menu
    st.write(f"Selected: {main_menu} → {menu}")

    # ---------------- HOME ----------------
    if menu == "Home":
        st.title("Dashboard")
        items_df = view_items()
        sales_df = view_sales()
        if not items_df.empty:
            st.subheader("Inventory Summary")
            st.metric("Total Items", len(items_df))
            fig = px.bar(items_df, x='category', y='quantity', color='category', title="Stock by Category")
            st.plotly_chart(fig)
        if not sales_df.empty:
            st.subheader("Sales Summary")
            fig2 = px.line(sales_df, x='date', y='profit', title="Profit Trend Over Time")
            st.plotly_chart(fig2)

    # ---------------- INVENTORY ----------------
    elif menu == "View Inventory":
        st.title("Inventory Data")
        data = view_items()
        if data.empty:
            st.warning("No items found.")
        else:
            view_mode = st.radio("Select View Mode", ["Per-Fridge View", "Aggregated View"], index=0)
            if view_mode == "Per-Fridge View":
                fridge_options = sorted(data["fridge_no"].unique())
                selected_fridge = st.selectbox("Filter by Fridge No", ["All"] + fridge_options)
                if selected_fridge != "All":
                    data = data[data["fridge_no"] == selected_fridge]
                data = data.sort_values(by="fridge_no")
                paged_df, _ = paginate_dataframe(data, page_size=100)
                st.dataframe(paged_df)
            else:
                aggregated_df = data.groupby(["item_name", "category"], as_index=False).agg({"quantity": "sum"}).rename(columns={"quantity": "total_stock"})
                st.dataframe(aggregated_df)

    elif menu == "Manage Stock":
        st.title("Manage Stock")

        items_df = view_items()
        if items_df.empty:
            st.warning("No items found.")
        else:
            # Show current inventory list
            st.subheader("Current Inventory")
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
                    styled_inventory = item_rows[['fridge_no', 'quantity']].style.format({
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
            quantity = st.number_input("Quantity", min_value=0.5, value=0.5, step=0.1, format="%.2f")
            fridge_no = st.text_input("Fridge No", value="0")

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
                items_df['label'] = items_df.apply(lambda row: f"{row['item_id']} - {row['category']} - {row['item_name']}", axis=1)
                selected_label = st.selectbox("Select Item to Delete", items_df['label'])
                item_id = int(selected_label.split(" - ")[0])
                if st.button("Delete"):
                    delete_item(item_id, st.session_state.username)
                    st.success(f"Item with ID {item_id} deleted successfully!")
                    st.rerun()

    elif menu == "File Upload (Items)":
        st.title("File Upload (Items)")
        uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file is not None:
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            if file_ext == ".csv":
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            required_cols = ["item_name", "category", "quantity", "fridge_no"]
            if all(col in df.columns for col in required_cols):
                for _, row in df.iterrows():
                    add_or_update_item(None, row["item_name"].strip().upper(), row["category"].strip().upper(), row["quantity"], row["fridge_no"], st.session_state.username)
                st.success("Items updated or inserted successfully!")
            else:
                st.error(f"Missing required columns: {required_cols}")

    elif menu == "Delete All Inventory":
        st.title("Delete All Inventory")
        st.warning("This action will delete ALL inventory items permanently.")
        confirm = st.text_input("Type 'DELETE' to confirm")
        if st.button("Delete All Inventory"):
            if confirm == "DELETE":
                delete_all_inventory()
                st.success("All inventory items have been deleted.")
            else:
                st.error("Confirmation text does not match. Inventory not deleted.")

    # ---------------- PRICING ----------------
    elif menu == "View Pricing Tiers":
        st.title("View Pricing Tiers")
        data = view_pricing()
        if data.empty:
            st.warning("No pricing found.")
        else:
            data, total_pages = paginate_dataframe(data, page_size=100)
            st.write(f"Showing {len(data)} rows (Page size: 100)")
            st.dataframe(data)

    elif menu == "File Upload (Pricing)":
        st.title("File Upload (Pricing)")
        uploaded_file = st.file_uploader("Upload Pricing CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file:
            upload_tiered_pricing(uploaded_file)

    elif menu == "Manage Pricing Tiers":
        manage_pricing_tiers()
        

    elif menu == "Manage Special Customer Prices":
        manage_special_customer_pricing()   
        
    # ---------------- CUSTOMER ----------------
    elif menu == "Manage Customers":
        st.title("Manage Customers")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            st.subheader("Current Customers")
            st.dataframe(customers_df[['id','name','phone','email','address']], width='stretch')

        with st.expander("➕ Add / Update Customers", expanded=False):
            if not customers_df.empty:
                customer_options = ["Add New"] + [f"{row['id']} - {row['name']}" for _, row in customers_df.iterrows()]
            else:
                customer_options = ["Add New"]

            selected_customer = st.selectbox("Select Customer", customer_options)
            if selected_customer != "Add New":
                selected_customer_id = int(selected_customer.split(" - ")[0])
                selected_customer_name = selected_customer.split(" - ")[1]
                customer_rows = customers_df[customers_df['name'] == selected_customer_name]

                if not customer_rows.empty:
                    st.info("Existing customer details:")
                    st.dataframe(customer_rows[['id','name','phone','email','address']])
                else:
                    st.warning(f"No records found for customer '{selected_customer_name}'.")

                customer_id = selected_customer_id
                name = st.text_input("Name", value=selected_customer_name)
                phone = st.text_input("Contact No", value=customer_rows.iloc[0]['phone'] if not customer_rows.empty else "")
                email = st.text_input("Email Address", value=customer_rows.iloc[0]['email'] if not customer_rows.empty else "")
                address = st.text_input("Address", value=customer_rows.iloc[0]['address'] if not customer_rows.empty else "")
                group_id = st.text_input("Group ID", value=customer_rows.iloc[0]['group_id'] if not customer_rows.empty else "")
            else:
                customer_id = None
                name = st.text_input("Name", value="")
                phone = st.text_input("Contact No", value="")
                email = st.text_input("Email Address", value="")
                address = st.text_input("Address", value="")
                group_id = st.text_input("Group ID", value="")

            if st.button("Save Customer"):
                result = save_customer(customer_id, name, phone, email, address, group_id)
                if result == "updated":
                    st.success(f"Customer '{name}' updated successfully!")
                else:
                    st.success(f"Customer '{name}' added successfully!")
                st.rerun()

        with st.expander("🗑️ Delete a Customer", expanded=False):
            if customers_df.empty:
                st.warning("No customers to delete.")
            else:
                customers_df['label'] = customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
                selected_label = st.selectbox("Select Customer to Delete", customers_df['label'])
                customer_id = int(selected_label.split(" - ")[0])
                if st.button("Delete Customer"):
                    delete_customer(customer_id)
                    st.success(f"Customer with ID {customer_id} deleted successfully!")
                    st.rerun()
        
    
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
            sales_df = view_sales_by_customer(customer_id)

            # Ensure 'date' is the first column
            if not sales_df.empty and "date" in sales_df.columns:
                cols = ["date"] + [c for c in sales_df.columns if c != "date"]
                sales_df = sales_df[cols]

            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                paged_sales, total_pages = paginate_dataframe(sales_df, page_size=20)
                st.write(f"Showing {len(paged_sales)} rows (Page size: 20)")
                styled_sales = paged_sales.style.format({
                    "total_sale": "{:,.2f}",
                    "selling_price": "{:,.2f}",
                    "cost": "{:,.2f}",
                    "profit": "{:,.2f}"
                })
                st.dataframe(styled_sales, width='stretch')
                csv_sales = sales_df.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")

    # ---- Record SAle----
    elif menu == "Record Sale":
        st.title("Record Sale")
        items_df = view_items()
        customers_df = view_customers()

        if items_df.empty:
            st.warning("No items available for sale.")
        elif customers_df.empty:
            st.warning("No customers available. Please add a customer first.")
        else:
            items_df["display"] = items_df.apply(lambda row: f"{row['item_id']} - {row['item_name']}", axis=1)
            item_display = st.selectbox("Select Item", ["Select item"] + items_df["display"].tolist())

            selected_item_id, selected_item_name = None, None
            if item_display != "Select item":
                selected_item_id = int(item_display.split(" - ")[0])
                selected_item_name = item_display.split(" - ")[1]

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

            quantity = st.number_input("Quantity Sold", min_value=1)

            if customer_label != "Select customer" and item_display != "Select item":
                total_qty = get_total_qty(selected_item_name)
                st.info(f"Stock Currently On Hand: {total_qty}")
                if total_qty < quantity and quantity != 0:
                    st.error("Not enough stock")

                base_price = get_base_price(selected_item_id, quantity)
                final_price = get_customer_adjusted_price(customer_id, selected_item_id, quantity)

                st.info(f"**Final Price for {customer_name}:** Base: {base_price:.2f}, Special Price: {final_price:.2f}")

                price_choice = st.radio("Select pricing method", ("Base Price", "Special Price", "Override Price"))
                chosen_unit_price = None

                if price_choice == "Base Price":
                    chosen_unit_price = base_price
                elif price_choice == "Special Price":
                    chosen_unit_price = final_price
                elif price_choice == "Override Price":
                    chosen_unit_price = st.number_input("Enter custom per unit price", min_value=0.0, format="%.2f")

                if chosen_unit_price is not None:
                    total_sale = quantity * chosen_unit_price
                    st.success(f"Chosen Price per Unit: PHP {chosen_unit_price:,.2f}")
                    st.success(f"Calculated Total Sale: PHP {total_sale:,.2f}")

                if st.button("Record Sale"):
                    msg = record_sale(selected_item_id, quantity, st.session_state.username, customer_id, chosen_unit_price)
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
                            
    elif menu == "Customer Statement of Account":
        st.title("Customer Statement of Account")
        from fpdf.enums import XPos, YPos
        customers_df = view_customers()

        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            customer_name = customer_label.split(" - ")[1]

            today = date.today()
            start_of_month = today.replace(day=1)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end_of_month = today.replace(day=last_day)

            start_date = st.date_input("Start Date", value=start_of_month)
            end_date = st.date_input("End Date", value=end_of_month)

            # ✅ Use helper function from db_supabase.py
            sales_customer = get_sales_by_customer(customer_id, start_date, end_date)

            # Ensure 'date' is the first column
            if not sales_customer.empty and "date" in sales_customer.columns:
                cols = ["date"] + [c for c in sales_customer.columns if c != "date"]
                sales_customer = sales_customer[cols]

            if sales_customer.empty:
                st.warning("No sales records found for this customer in the selected period.")
            else:
                st.subheader("Sales Records of Selected Customer")
                paged_sales_customer, total_pages = paginate_dataframe(sales_customer, page_size=20)
                st.write(f"Showing {len(paged_sales_customer)} rows (Page size: 20)")
                styled_sales = paged_sales_customer.style.format({
                    "selling_price": "{:,.2f}",
                    "total_sale": "{:,.2f}",
                    "cost": "{:,.2f}",
                    "profit": "{:,.2f}"
                })
                st.dataframe(styled_sales, width='stretch')

                csv_sales = sales_customer.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")

                if st.button("Generate SOA"):
                    from fpdf import FPDF

                    filename = f"SOA_{customer_id}_{start_date}_{end_date}.pdf"
                    pdf = FPDF()
                    pdf.add_page()

                    # --- Logo ---
                    pdf.image("Icon.jpeg", x=10, y=8, w=30)

                    # --- Company Name & Address ---
                    pdf.set_font("Helvetica", 'B', 14)
                    pdf.cell(0, 10, "Diane's Wholesale Beverages", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

                    pdf.set_font("Helvetica", size=10)
                    pdf.multi_cell(0, 5, "45 Data St. Brgy Don Manuel QC\nPhone: +63 917 8081409\nEmail: ong_diane@yahoo.com", align="C")
                    pdf.ln(10)

                    pdf.set_font("Helvetica", size=12)
                    pdf.cell(200, 10, text=f"Statement of Account", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.cell(200, 10, text=f"Customer: {customer_name} (ID: {customer_id})", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.cell(200, 10, text=f"Period: {start_date} to {end_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.ln(10)

                    # Table header
                    pdf.set_font("Helvetica", 'B', 10)
                    pdf.cell(20, 10, "Date", 1, align="C")
                    pdf.cell(60, 10, "Item", 1, align="L")
                    pdf.cell(20, 10, "Qty", 1, align="C")
                    pdf.cell(40, 10, "Total Sale", 1, align="R")
                    pdf.cell(40, 10, "Profit", 1, align="R")
                    pdf.ln()

                    # Table rows
                    pdf.set_font("Helvetica", size=10)
                    for _, row in sales_customer.iterrows():
                        pdf.cell(20, 10, str(row.get("date", "")), 1, align="C")
                        pdf.cell(60, 10, str(row.get("item_name", "")), 1, align="L")
                        pdf.cell(20, 10, str(row.get("quantity", "")), 1, align="C")
                        pdf.cell(40, 10, f"{row.get('total_sale', 0):,.2f}", 1, align="R")
                        pdf.cell(40, 10, f"{row.get('profit', 0):,.2f}", 1, align="R")
                        pdf.ln()

                    # ✅ Save PDF properly
                    pdf.output(filename)

                    # ✅ Get bytes without deprecated dest
                    pdf_bytes = bytes(pdf.output())
                    st.download_button("Download SOA PDF", data=pdf_bytes, file_name=filename, mime="application/pdf")
                
    elif menu == "Delete All Customers":
        st.title("Delete All Customers")
        st.warning("This action will delete ALL customers permanently.")
        confirm = st.text_input("Type 'DELETE' to confirm")
        if st.button("Delete All Customers"):
            if confirm == "DELETE":
                delete_all_customers()
                st.success("All customers have been deleted.")
            else:
                st.error("Confirmation text does not match. Customers not deleted.")


    elif menu == "View Special Pricing":
        st.title("View Customer Special Pricing")

        # --- Select Customer ---
        customers_df = view_customers()

        customers_df["display"] = customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
        customer_display = st.selectbox("Select Customer", ["Select customer"] + customers_df["display"].tolist())

        selected_customer_id, selected_customer_name = None, None
        if customer_display != "Select customer":
            selected_customer_id = int(customer_display.split(" - ")[0])
            selected_customer_name = customer_display.split(" - ")[1]

        # --- Select Item ---
        items_df = get_items_for_pricing()

        items_df["display"] = items_df.apply(lambda row: f"{row['item_id']} - {row['label']}", axis=1)
        item_display = st.selectbox("Select Item", ["Select item"] + items_df["display"].tolist())

        selected_item_id, selected_item_name = None, None
        if item_display != "Select item":
            selected_item_id = int(item_display.split(" - ")[0])
            selected_item_name = item_display.split(" - ")[1]

        qty = st.number_input("Quantity", min_value=1, value=1)

        # --- Compute Prices immediately ---
        customer_id = selected_customer_id
        item_id = selected_item_id

        if selected_customer_id is not None and selected_item_id is not None:
            base_price = get_base_price(item_id, qty)
            final_price = get_customer_adjusted_price(customer_id, item_id, qty)

            st.write(f"**Final Price for {selected_customer_id}:** Base: {base_price}, special: {final_price:.2f}")

            # --- Fetch Special Pricing (if exists) ---
            special_prices_df = get_special_price(customer_id, item_id)

            # --- Build table with base + special price ---
            if not special_prices_df.empty:
                st.write("### Pricing Details")
                df = special_prices_df.copy()
                df["Item Name"] = selected_item_name
                df["Base Price"] = f"{base_price:,.2f}"
                df["Special Price"] = df["custom_price"].apply(lambda x: f"{x:,.2f}")
                df = df[["Item Name", "Base Price", "Special Price"]]
                st.dataframe(df)
            else:
                st.write("### Pricing Details")
                df = pd.DataFrame([{"Item Name": selected_item_name, "Base Price": base_price, "Special Price": None}])
                df["Base Price"] = f"{base_price:,.2f}"
                df = df[["Item Name", "Base Price", "Special Price"]]
                st.dataframe(df)


    # ---------------- REPORTS ----------------
    elif menu == "View Audit Log":
        st.title("Audit Log")
        data = view_audit_log()
        if data.empty:
            st.warning("No audit log entries found.")
        else:
            paged_df, total_pages = paginate_dataframe(data, page_size=100)
            st.write(f"Showing {len(paged_df)} rows (Page size: 100)")
            st.dataframe(paged_df)
            csv_audit = data.to_csv(index=False)    
            st.download_button("Download Audit Log CSV", data=csv_audit, file_name="audit_log.csv", mime="text/csv")

    elif menu == "Profit/Loss Report":
        st.title("Profit/Loss Report")
        sales_df = view_sales()
        if sales_df.empty:
            st.warning("No sales data found.")
        else:
            profit_loss_df = sales_df.groupby('date', as_index=False).agg({'profit': 'sum'})
            st.dataframe(profit_loss_df)
            fig = px.line(profit_loss_df, x='date', y='profit', title="Profit/Loss Over Time")
            st.plotly_chart(fig)
            csv_profit_loss = profit_loss_df.to_csv(index=False)    
            st.download_button("Download Profit/Loss CSV", data=csv_profit_loss, file_name="profit_loss_report.csv", mime="text/csv")

    elif menu == "Generate Purchase Order":
        st.title("Generate Purchase Order (PO)")
        from fpdf.enums import XPos, YPos
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            sales_df = view_sales_by_customer(customer_id)
            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                order_dates = sales_df['date'].unique()
                order_date = st.selectbox("Select Order Date", order_dates)
                if isinstance(order_date, date):
                    order_date_sql = order_date.strftime("%Y-%m-%d")
                else:
                    order_date_sql = str(order_date)

                pickup_date = st.date_input("Pickup Date")
                pickup_date_sql = pickup_date.strftime("%Y-%m-%d")

                if st.button("Generate PO"):
                    from fpdf import FPDF

                    # --- Generate PO Number ---
                    seq = get_po_sequence(order_date_sql)
                    po_number = f"PO-{order_date_sql.replace('-', '')}-{seq:03d}"

                    # --- Vendor Info ---
                    vendor = {
                        "name": "Diane's Wholesale Beverages",
                        "address": "45 Data St. Brgy Don Manuel QC",
                        "phone": "+63 917 808 1409",
                        "email": "ong_diane@yahoo.com"
                    }

                    # --- Buyer Info ---
                    customer = get_customer(customer_id)
                    buyer = {
                        "name": customer.get("name", ""),
                        "address": customer.get("address", ""),
                        "phone": customer.get("phone", ""),
                        "email": customer.get("email", "")
                    }
                    safe_name = buyer["name"].replace(" ", "_").replace("/", "_")
                    filename = f"PO_{order_date_sql.replace('-', '')}_{safe_name}.pdf"

                    # --- Build PDF ---
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.image("Icon.jpeg", x=10, y=8, w=30)

                    pdf.set_font("Helvetica", 'B', 14)
                    pdf.cell(0, 10, vendor["name"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.set_font("Helvetica", size=10)
                    pdf.multi_cell(0, 5, f"{vendor['address']}\nPhone: {vendor['phone']}\nEmail: {vendor['email']}", align="C")
                    pdf.ln(10)

                    pdf.set_font("Helvetica", 'B', 12)
                    pdf.cell(0, 10, "Purchase Order", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
                    pdf.set_font("Helvetica", size=10)
                    pdf.cell(0, 10, f"PO Number: {po_number}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(0, 10, f"Order Date: {order_date_sql}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    #pdf.cell(0, 10, f"Pickup Date: {pickup_date_sql}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.ln(10)

                    # Table header
                    pdf.set_font("Helvetica", 'B', 10)
                    pdf.cell(20, 10, "No.", 1, align="C")
                    pdf.cell(80, 10, "Description", 1, align="L")
                    pdf.cell(30, 10, "Qty", 1, align="C")
                    pdf.cell(30, 10, "Unit Price", 1, align="R")
                    pdf.cell(30, 10, "Total", 1, align="R")
                    pdf.ln()

                    # Table rows
                    pdf.set_font("Helvetica", size=10)
                    subtotal = 0
                    for idx, row in sales_df[sales_df['date'] == order_date].iterrows():
                        total = row["quantity"] * row["selling_price"]
                        subtotal += total
                        pdf.cell(20, 10, str(idx+1), 1, align="C")
                        pdf.cell(80, 10, str(row.get("item_name", "")), 1, align="L")
                        pdf.cell(30, 10, str(row.get("quantity", "")), 1, align="C")
                        pdf.cell(30, 10, f"{row.get('selling_price', 0):,.2f}", 1, align="R")
                        pdf.cell(30, 10, f"{total:,.2f}", 1, align="R")
                        pdf.ln()

                    pdf.ln(5)
                    pdf.cell(0, 10, f"Subtotal: PHP {subtotal:,.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    pdf.cell(0, 10, "GST: PHP 0.00 (No GST)", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    pdf.cell(0, 10, f"Total Amount: PHP {subtotal:,.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    pdf.ln(10)

                    pdf.cell(0, 10, f"Pickup Date: {pickup_date_sql}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.ln(20)
                    pdf.cell(0, 10, "Authorized By: ____________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                    #pdf_bytes = bytes(pdf.output(dest="S"))

                    #pdf_bytes = pdf.output(dest="bytes")
                    #pdf_bytes = bytes(pdf_bytes)   # Convert bytearray → bytes
                    #st.download_button(
                    #    "Download PO PDF",
                    #    data=pdf_bytes,
                    #    file_name=filename,
                    #    mime="application/pdf"
                    #)

                    pdf_bytes = bytes(pdf.output())  # no dest argument
                    st.download_button(
                        "Download PO PDF",
                        data=pdf_bytes,
                        file_name=filename,
                        mime="application/pdf"
                    )