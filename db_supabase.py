from supabase import create_client, Client
import pandas as pd
import streamlit as st
import os
from datetime import datetime

# Initialize Supabase client
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["service_role_key"]  # server-side only
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------- ITEMS ----------------
def view_items():
    res = supabase.table("items").select("*").execute()
    return pd.DataFrame(res.data)

def add_or_update_item(item_id, item_name, category, quantity, fridge_no, user):
    # Normalize fridge_no to int if possible
    try:
        fridge_no = int(fridge_no)
    except:
        pass

    action = None

    if item_id and item_id != "Add New":
        # Case 1: Existing item selected
        existing = supabase.table("items").select("*").eq("item_id", item_id).execute()
        if existing.data:
            current_record = existing.data[0]
            current_qty = current_record["quantity"]
            current_fridge = current_record["fridge_no"]

            if str(current_fridge) == str(fridge_no):
                # Same fridge → add to existing quantity
                new_qty = current_qty + quantity
                supabase.table("items").update({
                    "quantity": new_qty
                }).eq("item_id", item_id).execute()
                action = "Update"
            else:
                # Different fridge → create new item row
                supabase.table("items").insert({
                    "item_name": item_name,
                    "category": category,
                    "quantity": quantity,
                    "fridge_no": fridge_no
                }).execute()
                action = "Add (New Fridge)"
        else:
            # No record found → insert new
            supabase.table("items").insert({
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "fridge_no": fridge_no
            }).execute()
            action = "Add"
    else:
        # Case 2: New item/category entered
        # ✅ Check if same item/category/fridge already exists
        existing = (
            supabase.table("items")
            .select("*")
            .eq("item_name", item_name)
            .eq("category", category)
            .eq("fridge_no", fridge_no)
            .execute()
        )

        if existing.data:
            # Update quantity instead of inserting duplicate
            current_record = existing.data[0]
            new_qty = current_record["quantity"] + quantity
            supabase.table("items").update({
                "quantity": new_qty
            }).eq("item_id", current_record["item_id"]).execute()
            action = "Update Existing (Duplicate Prevented)"
        else:
            # Insert new record
            supabase.table("items").insert({
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "fridge_no": fridge_no
            }).execute()
            action = "Add"

    # Audit log entry
    supabase.table("audit_log").insert({
        "item_name": item_name,
        "category": category,
        "action": action,
        "quantity": quantity,
        "unit_cost": 0.0,
        "selling_price": 0.0,
        "username": user,
        "timestamp": datetime.now().isoformat()
    }).execute()

def delete_item(item_id, user):
    item = supabase.table("items").select("*").eq("item_id", item_id).execute()
    if item.data:
        supabase.table("audit_log").insert({
            "item_name": item.data[0]["item_name"],
            "category": item.data[0]["category"],
            "action": "Delete",
            "quantity": item.data[0]["quantity"],
            "unit_cost": 0.0,
            "selling_price": 0.0,
            "username": user,
            "timestamp": datetime.now().isoformat()
        }).execute()
    supabase.table("items").delete().eq("item_id", item_id).execute()

def delete_all_inventory():
    supabase.table("items").delete().gte("item_id", 0).execute()
    supabase.table("audit_log").insert({
        "item_name": "ALL ITEMS",
        "category": "ALL CATEGORIES",
        "action": "Delete All Inventory",
        "quantity": 0,
        "unit_cost": 0.00,
        "selling_price": 0.00,
        "username": "System"
    }).execute()   

def get_total_qty(item_name):
    res = supabase.table("items").select("quantity").eq("item_name", item_name).execute()
    if not res.data:
        return 0
    return sum([row["quantity"] for row in res.data])

# ---------------- CUSTOMERS ----------------
def view_customers():
    res = supabase.table("customers").select("*").execute()
    return pd.DataFrame(res.data)

def get_customer(customer_id: int) -> dict:
    """Fetch customer details by ID."""
    result = supabase.table("customers").select("*").eq("id", customer_id).execute()
    if result.data:
        return result.data[0]
    return {}

def validate_if_customer_exist(name):
    res = supabase.table("customers").select("id").eq("name", name.upper()).execute()
    return bool(res.data)

def save_customer(customer_id, name, phone, email, address, group_id=None):
    """Insert or update a customer record."""
    data = {
        "name": name.strip().upper(),
        "phone": phone.strip(),
        "email": email.strip().upper(),
        "address": address.strip().upper(),
        "group_id": int(group_id) if group_id else None
    }

    if customer_id:  # Update existing
        supabase.table("customers").update(data).eq("id", customer_id).execute()
        return "updated"
    else:  # Insert new
        supabase.table("customers").insert(data).execute()
        return "inserted"

def update_customer(name, phone, email, address):
    supabase.table("customers").update({
        "phone": phone,
        "email": email.upper(),
        "address": address.upper()
    }).eq("name", name.upper()).execute()

def delete_customer(customer_id):
    supabase.table("customers").delete().eq("id", customer_id).execute()

def delete_all_customers():
    # Explicitly delete all rows by using a condition that matches everything
    supabase.table("customers").delete().gte("id", 0).execute()

    # Log the action
    supabase.table("audit_log").insert({
        "item_name": "ALL CUSTOMERS",
        "category": "N/A",
        "action": "Delete All Customers",
        "quantity": 0,
        "unit_cost": 0.00,
        "selling_price": 0.00,
        "username": "System"
    }).execute()

# ---------------- PRICING ----------------
def view_pricing():
    res = supabase.table("pricing_tiers").select("*").execute()
    return pd.DataFrame(res.data)

def get_items_for_pricing() -> pd.DataFrame:
    """Fetch items grouped by item_id for pricing tiers."""
    res = supabase.table("pricing_tiers").select("item_id, label").execute()
    return pd.DataFrame(res.data)

#def get_price_list():
#    res = supabase.rpc("get_price_list").execute()  # optional: create SQL function in Supabase
#    return pd.DataFrame(res.data)

def get_price_list() -> pd.DataFrame:
    """
    Fetch the special customer price list with customer and item names.
    Equivalent to the SQL join:
    SELECT cpl.id, c.name AS customer_name, i.item_name AS item_name,
           cpl.custom_price, cpl.customer_id, cpl.item_id
    FROM customer_price_list cpl
    JOIN customers c ON cpl.customer_id = c.id
    JOIN items i ON cpl.item_id = i.item_id;
    """
    res = (
        supabase.table("customer_price_list")
        .select("id, custom_price, customer_id, item_id, customers(name), items(item_name)")
        .execute()
    )
    df = pd.DataFrame(res.data)

    # Flatten nested dicts for easier use in UI
    if not df.empty:
        df["customer_name"] = df["customers"].apply(lambda x: x["name"] if isinstance(x, dict) else None)
        df["item_name"] = df["items"].apply(lambda x: x["item_name"] if isinstance(x, dict) else None)
        df = df.drop(columns=["customers", "items"])

    return df

def add_price(customer_id, item_id, custom_price):
    supabase.table("customer_price_list").insert({
        "customer_id": customer_id,
        "item_id": item_id,
        "custom_price": custom_price
    }).execute()

#def update_price(record_id, custom_price):
#    supabase.table("customer_price_list").update({
#        "custom_price": custom_price
#    }).eq("id", record_id).execute()

def update_price(customer_id: int, item_id: int, custom_price: float):
    """Update an existing special price record."""
    supabase.table("customer_price_list").update({
        "custom_price": custom_price
    }).eq("customer_id", customer_id).eq("item_id", item_id).execute()

def delete_price(record_id):
    supabase.table("customer_price_list").delete().eq("id", record_id).execute()

def validate_special_price_exist(customer_id: int, item_id: int) -> bool:
    """Check if a special price record already exists for a customer-item pair."""
    res = (
        supabase.table("customer_price_list")
        .select("id")
        .eq("customer_id", customer_id)
        .eq("item_id", item_id)
        .execute()
    )
    return bool(res.data)

def get_base_price(item_id: int, quantity: int) -> float:
    res = (
        supabase.table("pricing_tiers")
        .select("price_per_unit")
        .eq("item_id", item_id)
        .lte("min_qty", quantity)
        .or_(f"max_qty.is.null,max_qty.eq.0,max_qty.gte.{quantity}")
        .order("min_qty", desc=True)
        .limit(1)
        .execute()
    )
    if res.data and res.data[0].get("price_per_unit") is not None:
        return float(res.data[0]["price_per_unit"])
    return 0.00

def get_special_price(customer_id: int, item_id: int) -> pd.DataFrame:
    """
    Fetch special pricing for a given customer and item.
    Equivalent to:
    SELECT id, customer_id, item_id, custom_price
    FROM customer_price_list
    WHERE customer_id = ? AND item_id = ?
    """
    res = (
        supabase.table("customer_price_list")
        .select("id, customer_id, item_id, custom_price")
        .eq("customer_id", customer_id)
        .eq("item_id", item_id)
        .execute()
    )
    return pd.DataFrame(res.data)

def get_customer_adjusted_price(customer_id: int, item_id: int, quantity: int) -> float:
    """Fetch special customer price if defined, otherwise fall back to base price."""
    res = (
        supabase.table("customer_price_list")
        .select("custom_price")
        .eq("customer_id", customer_id)
        .eq("item_id", item_id)
        .execute()
    )
    if res.data:
        return res.data[0]["custom_price"]
    return get_base_price(item_id, quantity)


def upload_tiered_pricing_to_db(df: pd.DataFrame):
    """
    Process a DataFrame of tiered pricing and update/insert into Supabase.
    Returns a list of skipped item_ids.
    """
    skipped_rows = []

    for _, row in df.iterrows():
        item_id = int(row['item_id'])
        min_qty = int(row['min_qty'])
        max_qty = None if pd.isna(row['max_qty']) else int(row['max_qty'])
        price_per_unit = float(row['price_per_unit'])
        label = str(row['label']).strip().upper()

        # ✅ Check if item exists in items table
        item_check = supabase.table("items").select("item_id").eq("item_id", item_id).execute()
        if not item_check.data:
            skipped_rows.append(item_id)
            continue

        # Check if pricing tier exists
        if max_qty is None:
            existing = (
                supabase.table("pricing_tiers")
                .select("id")
                .eq("item_id", item_id)
                .eq("min_qty", min_qty)
                .is_("max_qty", None)
                .eq("label", label)
                .execute()
            )
        else:
            existing = (
                supabase.table("pricing_tiers")
                .select("id")
                .eq("item_id", item_id)
                .eq("min_qty", min_qty)
                .eq("max_qty", max_qty)
                .eq("label", label)
                .execute()
            )

        if existing.data:
            tier_id = existing.data[0]["id"]
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit
            }).eq("id", tier_id).execute()
        else:
            supabase.table("pricing_tiers").insert({
                "item_id": item_id,
                "min_qty": min_qty,
                "max_qty": max_qty,
                "price_per_unit": price_per_unit,
                "label": label
            }).execute()

    return skipped_rows

# ---------------- SALES ----------------
def view_sales():
    res = supabase.table("sales").select("*").execute()
    return pd.DataFrame(res.data)

def view_sales_by_customer(customer_id: int) -> pd.DataFrame:
    """Fetch sales records for a given customer."""
    res = supabase.table("sales").select("*").eq("customer_id", customer_id).order("date", desc=True).execute()
    return pd.DataFrame(res.data)

def record_sale(item_id: int, quantity: int, user: str, customer_id: int, chosen_unit_price: float):
    """Deduct stock, record sale, and log audit entry."""
    # Get item details
    res = supabase.table("items").select("*").eq("item_id", item_id).execute()
    if not res.data:
        return "Item not found."

    item_name = res.data[0]["item_name"]
    category = res.data[0]["category"]

    # Get all fridge records for this item_name
    res = supabase.table("items").select("*").eq("item_name", item_name).execute()
    rows = res.data
    total_quantity = sum(r["quantity"] for r in rows)
    if total_quantity < quantity:
        return "Not enough stock."

    # Deduct stock across fridges
    qty_to_deduct = quantity
    deduction_log = []
    for r in rows:
        if qty_to_deduct <= 0:
            break
        available = r["quantity"]
        deduct = min(available, qty_to_deduct)
        new_qty = available - deduct
        supabase.table("items").update({"quantity": new_qty}).eq("item_id", r["item_id"]).execute()
        qty_to_deduct -= deduct
        deduction_log.append(f"Fridge {r['fridge_no']}: deducted {deduct}, new qty={new_qty}")

    # Insert into sales
    total_sale = quantity * chosen_unit_price
    supabase.table("sales").insert({
        "item_id": item_id,
        "item_name": item_name,
        "quantity": quantity,
        "selling_price": chosen_unit_price,
        "total_sale": total_sale,
        "cost": 0.0,
        "profit": 0.0,
        "date": datetime.now().date().isoformat(),
        "customer_id": customer_id,
        "overridden": 1 if chosen_unit_price else 0
    }).execute()

    # Insert into audit log
    supabase.table("audit_log").insert({
        "item_name": item_name,
        "category": category,
        "action": "Sale",
        "quantity": quantity,
        "unit_cost": 0.0,
        "selling_price": chosen_unit_price,
        "username": user,
        "timestamp": datetime.now().isoformat()
    }).execute()

    return f"Sale recorded. Deduction details:\n" + "\n".join(deduction_log)

def get_sales_by_customer(customer_id: int, start_date: str, end_date: str):
    """
    Fetch sales records for a given customer between start_date and end_date.
    Returns a DataFrame.
    """
    query = (
        supabase.table("sales")
        .select("*")
        .eq("customer_id", customer_id)
        .gte("date", str(start_date))
        .lte("date", str(end_date))
        .execute()
    )
    return pd.DataFrame(query.data)

def get_po_sequence(order_date_sql: str) -> int:
    """Fetch or increment PO sequence for a given date."""
    result = supabase.table("po_sequence").select("seq").eq("date", order_date_sql).execute()
    if result.data:
        seq = result.data[0]["seq"] + 1
        supabase.table("po_sequence").update({"seq": seq}).eq("date", order_date_sql).execute()
    else:
        seq = 1
        supabase.table("po_sequence").insert({"date": order_date_sql, "seq": seq}).execute()
    return seq

# ---------------- AUDIT LOG ----------------
def view_audit_log(start_date=None, end_date=None):
    if start_date and end_date:
        res = supabase.table("audit_log").select("*").gte("timestamp", start_date).lte("timestamp", end_date).order("timestamp", desc=True).execute()
    else:
        res = supabase.table("audit_log").select("*").order("timestamp", desc=True).execute()
    return pd.DataFrame(res.data)

# ---------------- PRICE HISTORY ----------------
def create_price_history_entry(item_id, old_qty, new_qty, old_uc, old_sp, new_uc, new_sp, user):
    supabase.table("price_history").insert({
        "item_id": item_id,
        "old_quantity": old_qty,
        "new_price_quantity": new_qty,
        "old_unit_cost": old_uc,
        "old_selling_price": old_sp,
        "new_unit_cost": new_uc,
        "new_selling_price": new_sp,
        "changed_by": user,
        "timestamp": datetime.now().isoformat()
    }).execute()



#----------------- PRICING TIERS ----------------
def get_pricing_tiers(item_id: int):
    """Fetch pricing tiers for a given item_id, ordered by min_qty."""
    res = supabase.table("pricing_tiers").select("*").eq("item_id", item_id).order("min_qty").execute()
    return pd.DataFrame(res.data)

def save_pricing_tier(item_id: int, min_qty: int, max_qty: int, price_per_unit: float, label: str):
    """Insert or update a pricing tier."""
    if max_qty == 0:
        existing = (
            supabase.table("pricing_tiers")
            .select("*")
            .eq("item_id", item_id)
            .eq("min_qty", min_qty)
            .is_("max_qty", None)
            .execute()
        )
    else:
        existing = (
            supabase.table("pricing_tiers")
            .select("*")
            .eq("item_id", item_id)
            .eq("min_qty", min_qty)
            .eq("max_qty", max_qty)
            .execute()
        )

    if existing.data:
        if max_qty == 0:
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit,
                "label": label.strip().upper()
            }).eq("item_id", item_id).eq("min_qty", min_qty).is_("max_qty", None).execute()
        else:
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit,
                "label": label.strip().upper()
            }).eq("item_id", item_id).eq("min_qty", min_qty).eq("max_qty", max_qty).execute()
        return "updated"
    else:
        supabase.table("pricing_tiers").insert({
            "item_id": item_id,
            "min_qty": min_qty,
            "max_qty": None if max_qty == 0 else max_qty,
            "price_per_unit": price_per_unit,
            "label": label.strip().upper()
        }).execute()
        return "inserted"

def delete_pricing_tier(tier_id: int):
    """Delete a pricing tier by ID."""
    supabase.table("pricing_tiers").delete().eq("id", tier_id).execute()
    return True