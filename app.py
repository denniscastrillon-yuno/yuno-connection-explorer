"""Yuno Connection Explorer — landing page for the multipage Streamlit app."""

import streamlit as st

st.set_page_config(page_title="Yuno Connection Explorer", page_icon="🔌", layout="wide")

st.title("Yuno Connection Explorer")
st.markdown(
    "A toolkit for inspecting and replicating payment provider connections "
    "across Yuno organizations in staging."
)

st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Connection Explorer")
    st.markdown(
        "Browse all accounts and connections in the QA Integrations org. "
        "View credentials, parameters, payment methods, and raw JSON for any connection."
    )
    st.page_link("pages/1_Connection_Explorer.py", label="Open Explorer", icon="🔌")

with col2:
    st.subheader("Replicate Connections")
    st.markdown(
        "Copy connections and routing rules from a source account to a new target account "
        "via direct API calls."
    )
    st.page_link("pages/2_Replicate_Connections.py", label="Open Replicator", icon="🔄")

with col3:
    st.subheader("Push Changes")
    st.markdown(
        "Sync connections and routing from your dev account to an existing target account. "
        "Reviews a diff before pushing."
    )
    st.page_link("pages/3_Push_Changes.py", label="Open Push", icon="🚀")

st.markdown("---")
st.caption("Internal tool — Yuno Payments. Requires VPN / internal network access.")
