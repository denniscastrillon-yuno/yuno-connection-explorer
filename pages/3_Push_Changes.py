"""Push Changes page — sync connections and routing from a dev account to a target."""

import streamlit as st

from config import ORGANIZATION_CODE
from helpers import (
    conn_id,
    conn_provider,
    fetch_accounts,
    fetch_connections,
    fetch_connection_detail,
)
from replicator.models import ConnectionParam, ConnectionSpec, PublishedRouting
from replicator.routing_fetcher import fetch_routing_batch, parse_published_routing
from replicator.diff_engine import (
    PushPlan,
    compute_connection_diff,
    compute_routing_diff,
)
from replicator.push_orchestrator import PushOrchestrator

st.set_page_config(page_title="Push Changes", page_icon="\U0001f680", layout="wide")

# -- Sidebar -------------------------------------------------------------------
st.sidebar.title("Push Changes")
st.sidebar.markdown("---")

st.sidebar.subheader("Source Organization")
source_org_code = st.sidebar.text_input(
    "Source org code",
    value=ORGANIZATION_CODE,
    key="push_source_org",
)

st.sidebar.subheader("Target Organization")
target_org_code = st.sidebar.text_input(
    "Target org code",
    value=ORGANIZATION_CODE,
    key="push_target_org",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Options")
include_routing = st.sidebar.checkbox("Include routing", value=True, key="push_routing")

if st.sidebar.button("Refresh (clear cache)", key="push_refresh"):
    st.cache_data.clear()
    st.rerun()


# -- Helpers -------------------------------------------------------------------

def _build_connection_spec(detail: dict) -> ConnectionSpec:
    """Build a ConnectionSpec from a connection detail API response."""
    params = []
    for p in detail.get("params", []):
        params.append(ConnectionParam(
            param_id=p.get("param_id", ""),
            value=p.get("value", ""),
            country=p.get("country", "GLOBAL"),
            param_type=p.get("type", "API"),
        ))

    raw_methods = detail.get("payment_method", [])
    payment_methods = [m for m in raw_methods if isinstance(m, str) and m == m.upper()]

    return ConnectionSpec(
        connection_name=detail.get("connection_name", detail.get("name", "")),
        provider_id=detail.get("provider_id", ""),
        country=detail.get("country", "GLOBAL"),
        params=params,
        payment_methods=payment_methods,
        integration_code=detail.get("account_integration_code", ""),
    )


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_routing_data(
    account_code: str, payment_methods: tuple[str, ...],
) -> dict[str, dict]:
    return fetch_routing_batch(account_code, list(payment_methods))


# -- Main: Step 1 — Select Source and Target -----------------------------------
st.header("Push Changes")
st.markdown("Sync connections and routing from a source (dev) account to a target account.")

st.subheader("Step 1: Select Source & Target")

# Fetch accounts for both orgs
source_accounts_raw = fetch_accounts(source_org_code)
source_accounts = [a for a in source_accounts_raw if "_error" not in a]

target_accounts_raw = fetch_accounts(target_org_code)
target_accounts = [a for a in target_accounts_raw if "_error" not in a]

if not source_accounts:
    st.error("No accounts found for source organization. Check org code and network.")
    st.stop()
if not target_accounts:
    st.error("No accounts found for target organization. Check org code and network.")
    st.stop()

source_sorted = sorted(source_accounts, key=lambda a: a.get("name", ""))
target_sorted = sorted(target_accounts, key=lambda a: a.get("name", ""))

source_options = {f"{a['name']} ({a['code_live'][:8]}...)": a for a in source_sorted}
target_options = {f"{a['name']} ({a['code_live'][:8]}...)": a for a in target_sorted}

col_src, col_tgt = st.columns(2)
with col_src:
    source_label = st.selectbox(
        "Source Account (dev)",
        ["-- Select --"] + list(source_options.keys()),
        key="push_source_account",
    )
with col_tgt:
    target_label = st.selectbox(
        "Target Account",
        ["-- Select --"] + list(target_options.keys()),
        key="push_target_account",
    )

if source_label == "-- Select --" or target_label == "-- Select --":
    st.info("Select both a source and target account to compute the diff.")
    st.stop()

source_account = source_options[source_label]
target_account = target_options[target_label]
source_code = source_account["code_live"]
target_code = target_account["code_live"]

# Validate: same account
if source_org_code == target_org_code and source_code == target_code:
    st.error("Source and target accounts must be different.")
    st.stop()


# -- Main: Step 2 — Review Diff -----------------------------------------------
st.subheader("Step 2: Review Diff")

# Fetch connections for both accounts
with st.spinner("Fetching connections for source and target..."):
    source_conns_raw = fetch_connections(source_code)
    target_conns_raw = fetch_connections(target_code)

source_conns = [c for c in source_conns_raw if "_error" not in c]
target_conns = [c for c in target_conns_raw if "_error" not in c]

# Build ConnectionSpec for each source connection
with st.spinner("Loading source connection details..."):
    source_specs: list[ConnectionSpec] = []
    for conn in source_conns:
        cid = conn_id(conn)
        detail = fetch_connection_detail(source_code, cid)
        if isinstance(detail, dict) and "_error" not in detail:
            source_specs.append(_build_connection_spec(detail))

# Compute connection diff
conn_diffs = compute_connection_diff(source_specs, target_conns)

# Compute routing diff
source_routings: dict[str, PublishedRouting] = {}
target_routings: dict[str, PublishedRouting] = {}
source_raw_routings: dict[str, dict] = {}
routing_diffs = []

if include_routing:
    # Collect all PMs from source connections
    all_pms: set[str] = set()
    for spec in source_specs:
        all_pms.update(spec.payment_methods)
    # Also check PMs from target connections
    for conn in target_conns:
        for pm in conn.get("payment_methods", []):
            pm_id = pm.get("payment_method_id", "") if isinstance(pm, dict) else str(pm)
            if pm_id and pm_id == pm_id.upper():
                all_pms.add(pm_id)

    if all_pms:
        with st.spinner(f"Fetching routing for {len(all_pms)} payment method(s)..."):
            pms_tuple = tuple(sorted(all_pms))
            source_raw_routings = _fetch_routing_data(source_code, pms_tuple)
            target_raw_routings = _fetch_routing_data(target_code, pms_tuple)

        for pm in sorted(all_pms):
            src_raw = source_raw_routings.get(pm)
            tgt_raw = target_raw_routings.get(pm)
            if src_raw:
                source_routings[pm] = parse_published_routing(pm, src_raw)
            if tgt_raw:
                target_routings[pm] = parse_published_routing(pm, tgt_raw)

        routing_diffs = compute_routing_diff(source_routings, target_routings, source_raw_routings)

# Build the plan
plan = PushPlan(
    source_account_name=source_account.get("name", ""),
    target_account_name=target_account.get("name", ""),
    connection_diffs=conn_diffs,
    routing_diffs=routing_diffs,
)

# Metrics
creates = [d for d in conn_diffs if d.status == "CREATE"]
skips_conn = [d for d in conn_diffs if d.status == "SKIP"]
warns_conn = [d for d in conn_diffs if d.status == "WARN_EXTRA"]

routing_creates = [d for d in routing_diffs if d.status == "CREATE"]
routing_updates = [d for d in routing_diffs if d.status == "UPDATE"]
routing_skips = [d for d in routing_diffs if d.status == "SKIP"]
warns_routing = [d for d in routing_diffs if d.status == "WARN_EXTRA"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Connections to create", len(creates))
m2.metric("Routing to create/update", len(routing_creates) + len(routing_updates))
m3.metric("Already in sync", len(skips_conn) + len(routing_skips))
m4.metric("Warnings", len(warns_conn) + len(warns_routing))

if not plan.has_changes:
    st.success("Already in sync! No changes needed.")

# Connection diffs detail
if creates:
    with st.expander(f"Connections to create ({len(creates)})", expanded=True):
        for d in creates:
            st.markdown(f"**{d.connection_name}** ({d.provider_id})")
            if d.source_spec:
                st.caption(
                    f"Country: {d.source_spec.country} | "
                    f"PMs: {', '.join(d.source_spec.payment_methods) or 'None'} | "
                    f"Params: {len(d.source_spec.params)}"
                )

if skips_conn:
    with st.expander(f"Connections already in target ({len(skips_conn)})"):
        for d in skips_conn:
            st.caption(f"{d.connection_name} ({d.provider_id}) — {d.message}")

if warns_conn:
    with st.expander(f"Extra connections in target ({len(warns_conn)})"):
        for d in warns_conn:
            st.caption(f"\u26a0\ufe0f {d.connection_name} ({d.provider_id}) — {d.message}")

# Routing diffs detail
if routing_creates:
    with st.expander(f"Routing to create ({len(routing_creates)})", expanded=True):
        for d in routing_creates:
            st.markdown(f"**{d.payment_method}** — {d.changes_summary}")
            if d.source_routing:
                for cs in d.source_routing.condition_sets:
                    providers = ", ".join(r.provider_id for r in cs.routes)
                    st.caption(f"  {cs.sort_number}. {cs.display_label} -> [{providers}]")

if routing_updates:
    with st.expander(f"Routing to update ({len(routing_updates)})", expanded=True):
        for d in routing_updates:
            st.markdown(f"**{d.payment_method}** — {d.changes_summary}")
            col_s, col_t = st.columns(2)
            with col_s:
                st.caption("**Source:**")
                if d.source_routing:
                    for cs in d.source_routing.condition_sets:
                        providers = ", ".join(r.provider_id for r in cs.routes)
                        st.caption(f"  {cs.sort_number}. {cs.display_label} -> [{providers}]")
            with col_t:
                st.caption("**Target (current):**")
                if d.target_routing:
                    for cs in d.target_routing.condition_sets:
                        providers = ", ".join(r.provider_id for r in cs.routes)
                        st.caption(f"  {cs.sort_number}. {cs.display_label} -> [{providers}]")

if routing_skips:
    with st.expander(f"Routing already in sync ({len(routing_skips)})"):
        for d in routing_skips:
            st.caption(f"{d.payment_method} — {d.changes_summary}")

if warns_routing:
    with st.expander(f"Extra routing in target ({len(warns_routing)})"):
        for d in warns_routing:
            st.caption(f"\u26a0\ufe0f {d.payment_method} — {d.changes_summary}")


# -- Main: Step 3 — Execute Push -----------------------------------------------
st.subheader("Step 3: Execute Push")

can_push = plan.has_changes

if not can_push:
    st.info("Nothing to push. Source and target are in sync.")

if st.button("Push Changes", disabled=not can_push, type="primary"):
    progress_bar = st.progress(0, text="Starting push...")
    log_container = st.container()
    log_lines: list[str] = []

    def on_progress(message: str, fraction: float) -> None:
        progress_bar.progress(min(fraction, 1.0), text=message)
        log_lines.append(message)
        log_container.text("\n".join(log_lines))

    orchestrator = PushOrchestrator(
        plan=plan,
        source_account_code=source_code,
        target_account_code=target_code,
        target_org_code=target_org_code,
        on_progress=on_progress,
    )

    with st.spinner("Pushing changes..."):
        result = orchestrator.execute()

    progress_bar.progress(1.0, text="Done!")

    # Results summary
    st.markdown("---")
    st.subheader("Results")

    r1, r2, r3 = st.columns(3)
    r1.metric("Total steps", len(result.steps))
    r2.metric("Succeeded", result.success_count)
    r3.metric("Failed", result.failure_count)

    if result.all_succeeded:
        st.success("All steps completed successfully!")
    else:
        st.warning(f"{result.failure_count} step(s) failed. See details below.")

    for step in result.steps:
        icon = "\u2705" if step.success else "\u274c"
        with st.expander(f"{icon} {step.step_name}"):
            st.markdown(step.message)
