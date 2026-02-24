"""Shared helpers for the Yuno Connection Explorer multipage app."""

import streamlit as st

from config import ORGANIZATION_CODE
from yuno_client import list_accounts, list_connections, get_connection


# ── Extraction helpers ───────────────────────────────────────────────────────

def conn_id(conn: dict) -> str:
    """Extract connection ID from a list_connections item."""
    return conn.get("code", conn.get("id", conn.get("connection_id", "")))


def conn_provider(conn: dict) -> str:
    """Extract provider name from a list_connections item."""
    p = conn.get("provider")
    if isinstance(p, dict):
        return p.get("provider_id", p.get("name", ""))
    return p or conn.get("name", "")


# ── Cached fetchers ──────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_accounts(org_code: str) -> list[dict]:
    return list_accounts(org_code)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_connections(account_id: str) -> list[dict]:
    return list_connections(account_id)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_connection_detail(account_id: str, connection_id: str) -> dict:
    return get_connection(account_id, connection_id)


# ── Rendering helpers ────────────────────────────────────────────────────────

def render_connection_detail(detail: dict) -> None:
    """Render a connection detail dict into structured Streamlit widgets."""
    name = detail.get("connection_name", detail.get("name", "N/A"))
    provider = detail.get("provider_id", detail.get("provider", "N/A"))
    country = detail.get("country", "N/A")

    basic_cols = st.columns(3)
    basic_cols[0].markdown(f"**Name:** {name}")
    basic_cols[1].markdown(f"**Provider:** {provider}")
    basic_cols[2].markdown(f"**Country:** {country}")

    info_cols = st.columns(3)
    info_cols[0].markdown(f"**Account:** {detail.get('account_code', 'N/A')}")
    info_cols[1].markdown(f"**Integration Code:** {detail.get('account_integration_code', 'N/A')}")
    info_cols[2].markdown(f"**Test Credentials:** {detail.get('test_credentials', 'N/A')}")

    # Payment methods
    methods = detail.get("payment_method", [])
    if methods:
        st.markdown(f"**Payment Methods ({len(methods)}):**")
        st.code(", ".join(methods) if isinstance(methods, list) else str(methods))

    # Params (credentials/config)
    params = detail.get("params", [])
    if params:
        st.markdown("**Params (Credentials & Config):**")
        if isinstance(params, list):
            for p in params:
                param_id = p.get("param_id", "")
                value = p.get("value", "")
                country_p = p.get("country", "")
                st.code(f"[{country_p}] {param_id} = {value}", language="text")
        else:
            st.code(str(params), language="json")

    # Legacy fields
    creds = detail.get("credentials") or detail.get("credential") or {}
    if creds:
        st.markdown("**Credentials:**")
        st.code(str(creds), language="json")

    parameters = detail.get("parameters") or {}
    if parameters:
        st.markdown("**Parameters:**")
        st.code(str(parameters), language="json")

    # Full raw JSON
    st.markdown("**Raw JSON:**")
    st.json(detail)
