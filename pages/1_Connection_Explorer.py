"""Connection Explorer page — browse connections across all accounts."""

import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import ORGANIZATION_CODE
from helpers import (
    conn_id,
    conn_provider,
    fetch_accounts,
    fetch_connections,
    fetch_connection_detail,
    render_connection_detail,
)

st.set_page_config(page_title="Connection Explorer", page_icon="🔌", layout="wide")

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("Connection Explorer")

if st.sidebar.button("Refresh (clear cache)"):
    st.cache_data.clear()
    st.rerun()

# Fetch accounts dynamically
raw_accounts = fetch_accounts(ORGANIZATION_CODE)
account_errors = [a for a in raw_accounts if "_error" in a]
accounts = [a for a in raw_accounts if "_error" not in a]

if account_errors:
    st.sidebar.error(f"Error loading accounts: {account_errors[0]['_error']}")

if not accounts:
    st.error("No accounts found. Check your ORGANIZATION_CODE and network.")
    st.stop()

# Build display labels sorted by name
accounts_sorted = sorted(accounts, key=lambda a: a.get("name", ""))
account_labels = [
    f"{a['name']} ({a['code_live'][:8]}...)" for a in accounts_sorted
]

# Search filter
search = st.sidebar.text_input("Search accounts", placeholder="e.g. STRIPE, ADYEN...")
if search:
    filtered_indices = [
        i for i, a in enumerate(accounts_sorted)
        if search.upper() in a.get("name", "").upper()
    ]
    filtered_labels = [account_labels[i] for i in filtered_indices]
    filtered_accounts = [accounts_sorted[i] for i in filtered_indices]
else:
    filtered_labels = account_labels
    filtered_accounts = accounts_sorted

options = ["-- Select an account --", "** All Accounts **"] + filtered_labels
selected = st.sidebar.selectbox("Account", options)

st.sidebar.caption(f"{len(filtered_accounts)} accounts available ({len(accounts)} total)")

# Debug expander
with st.sidebar.expander("Debug: Raw account data"):
    st.json(accounts_sorted[:5])
    st.caption(f"Showing first 5 of {len(accounts_sorted)} accounts")


# ── Main area ────────────────────────────────────────────────────────────────
if selected == "-- Select an account --":
    st.info("Select an account from the sidebar to browse its connections.")
    st.stop()

if selected == "** All Accounts **":
    results: list[tuple[dict, dict]] = []

    def _fetch_for_account(account: dict) -> list[tuple[dict, dict]]:
        account_id = account["code_live"]
        conns = fetch_connections(account_id)
        return [(account, c) for c in conns if "_error" not in c]

    progress = st.progress(0, text="Fetching connections across all accounts...")
    total = len(filtered_accounts)
    done = 0

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_fetch_for_account, a): a for a in filtered_accounts}
        for future in as_completed(futures):
            done += 1
            progress.progress(done / total, text=f"Fetching... {done}/{total}")
            try:
                results.extend(future.result())
            except Exception:
                pass

    progress.empty()

    if not results:
        st.warning("No connections found across any account.")
        st.stop()

    st.metric("Total connections", len(results))

    rows = []
    for account, conn in results:
        rows.append({
            "Account": account.get("name", ""),
            "Provider": conn_provider(conn),
            "Name": conn.get("name", ""),
            "Connection ID": conn_id(conn),
            "Country": conn.get("country", ""),
            "Status": conn.get("status", ""),
        })

    df = pd.DataFrame(rows).sort_values(["Account", "Name"], ignore_index=True)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Connection Details")
    for account, conn in sorted(results, key=lambda x: (x[0].get("name", ""), x[1].get("name", ""))):
        cid = conn_id(conn)
        label = f"[{account.get('name', '')}] {conn.get('name', cid)} — {cid}"
        with st.expander(label):
            account_id = account["code_live"]
            detail = fetch_connection_detail(account_id, cid)
            if isinstance(detail, dict) and "_error" in detail:
                st.error(detail["_error"])
            elif isinstance(detail, dict):
                render_connection_detail(detail)
            else:
                st.json(detail)
    st.stop()

# ── Single account flow ─────────────────────────────────────────────────────
selected_index = options.index(selected) - 2  # offset for the two placeholder options
account = filtered_accounts[selected_index]
account_id = account["code_live"]
account_name = account.get("name", account_id)

with st.spinner(f"Fetching connections for **{account_name}**..."):
    connections = fetch_connections(account_id)

errors = [c for c in connections if "_error" in c]
connections = [c for c in connections if "_error" not in c]

if errors:
    st.error(f"API error: {errors[0]['_error']}")

if not connections:
    st.warning(f"No connections found for **{account_name}** (account `{account_id}`).")
    st.stop()

# ── Metrics row ──────────────────────────────────────────────────────────────
countries = {c.get("country", "N/A") for c in connections}
statuses = {c.get("status", "N/A") for c in connections}

col1, col2, col3 = st.columns(3)
col1.metric("Connections", len(connections))
col2.metric("Countries", len(countries))
col3.metric("Statuses", ", ".join(sorted(statuses)))

# ── Data table ───────────────────────────────────────────────────────────────
rows = []
for conn in connections:
    rows.append({
        "Name": conn.get("name", ""),
        "Provider": conn_provider(conn),
        "Country": conn.get("country", ""),
        "Connection ID": conn_id(conn),
        "Status": conn.get("status", ""),
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

# ── Detail cards ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("Connection Details")

for conn in connections:
    cid = conn_id(conn)
    label = f"{conn.get('name', cid)} — {cid}"
    with st.expander(label):
        detail = fetch_connection_detail(account_id, cid)
        if isinstance(detail, dict) and "_error" in detail:
            st.error(detail["_error"])
        elif isinstance(detail, dict):
            render_connection_detail(detail)
        else:
            st.json(detail)
