"""Replicate Connections page — copy connections and routing from a source account."""

import streamlit as st
import pandas as pd

from config import ORGANIZATION_CODE
from helpers import (
    conn_id,
    conn_provider,
    fetch_accounts,
    fetch_connections,
    fetch_connection_detail,
)
from replicator.models import ConnectionParam, ConnectionSpec, PublishedRouting, RoutingSpec
from replicator.param_mapper import match_params
from replicator.orchestrator import Replicator
from replicator.routing_fetcher import (
    fetch_routing_batch,
    parse_published_routing,
    pick_connection_for_pm,
)

st.set_page_config(page_title="Replicate Connections", page_icon="\U0001f504", layout="wide")

# -- Sidebar: Source & Target Config -------------------------------------------
st.sidebar.title("Replicate Connections")
st.sidebar.markdown("---")
st.sidebar.subheader("Source Organization")
source_org_code = st.sidebar.text_input(
    "Source organization code",
    value=ORGANIZATION_CODE,
    key="replicate_source_org",
)
st.sidebar.markdown("---")
st.sidebar.subheader("Target Organization")

target_org_code = st.sidebar.text_input(
    "Target organization code",
    placeholder="e.g. a1b2c3d4-...",
    help="Organization code where connections will be replicated. Must be different from the source org.",
)

target_account_name = st.sidebar.text_input(
    "Target account name",
    placeholder="e.g. ADYEN_clone",
    max_chars=32,
    help="Account to create/select in the target org. Max 32 chars.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Options")

include_routing = st.sidebar.checkbox("Include routing rules", value=True)

if st.sidebar.button("Refresh (clear cache)"):
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

    # Extract uppercase-only payment method IDs
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
    """Fetch routing data for PMs from routing-ms (cached)."""
    return fetch_routing_batch(account_code, list(payment_methods))


def _build_smart_routing_specs(
    connection_specs: list[ConnectionSpec],
    account_id: str,
) -> tuple[list[RoutingSpec], dict[str, PublishedRouting]]:
    """Build routing specs based on actual published routing from routing-ms.

    Only creates routing for PMs that:
      1. Have PUBLISHED routing in the source account
      2. Reference at least one of the selected connections

    Returns:
        - List of RoutingSpec (one per PM that needs routing)
        - Dict of PM -> PublishedRouting (for UI display)
    """
    # Collect all unique PMs across selected connections
    all_pms: set[str] = set()
    # Map integration_code -> connection_name for matching
    conn_codes: dict[str, str] = {}
    for spec in connection_specs:
        all_pms.update(spec.payment_methods)
        if spec.integration_code:
            conn_codes[spec.integration_code] = spec.connection_name

    if not all_pms or not conn_codes:
        return [], {}

    # Fetch routing data from routing-ms (concurrent, cached)
    raw_routings = _fetch_routing_data(account_id, tuple(sorted(all_pms)))

    specs: list[RoutingSpec] = []
    routing_details: dict[str, PublishedRouting] = {}
    seen_pms: set[str] = set()

    for pm in sorted(all_pms):
        if pm in seen_pms:
            continue
        raw = raw_routings.get(pm)
        if raw is None:
            continue

        routing = parse_published_routing(pm, raw)

        # Pick the best connection for this PM
        conn_name = pick_connection_for_pm(routing, conn_codes)
        if conn_name is None:
            continue

        seen_pms.add(pm)
        specs.append(RoutingSpec(
            payment_method=pm,
            connection_name=conn_name,
            route_name=f"{conn_name}_{pm}",
            source_routing=routing,
            source_condition_sets_raw=raw.get("condition_sets", []),
        ))
        routing_details[pm] = routing

    return specs, routing_details


def _truncate_value(value: str, max_len: int = 12) -> str:
    """Truncate a credential value for display."""
    if len(value) <= max_len:
        return value
    return value[:max_len] + "..."


def resolve_routing_dependencies(
    connection_specs: list[ConnectionSpec],
    routing_specs: list[RoutingSpec],
    source_connections: list[dict],
    account_id: str,
) -> list[ConnectionSpec]:
    """Auto-detect and add missing connections required by routing condition sets.

    Scans all routing condition sets for integration codes not covered by the
    user-selected connections. For each missing code, finds the source connection,
    fetches its detail, and builds a ConnectionSpec with ``is_dependency=True``.

    Returns the list of newly added dependency ConnectionSpecs.
    """
    # Collect integration codes already selected
    selected_codes = {s.integration_code for s in connection_specs if s.integration_code}

    # Collect ALL integration codes referenced in routing condition sets
    needed_codes: set[str] = set()
    for rs in routing_specs:
        if not rs.source_condition_sets_raw:
            continue
        for cs in rs.source_condition_sets_raw:
            for route in cs.get("routes", []):
                if route.get("type") == "PROVIDER":
                    ic = route.get("data", {}).get("integration_code", "")
                    if ic:
                        needed_codes.add(ic)

    missing_codes = needed_codes - selected_codes
    if not missing_codes:
        return []

    # Build a lookup: integration_code (= code field) -> connection list item
    code_to_conn: dict[str, dict] = {}
    for conn in source_connections:
        cid = conn_id(conn)
        if cid in missing_codes:
            code_to_conn[cid] = conn

    # Fetch details and build specs for each missing connection
    deps: list[ConnectionSpec] = []
    for ic in sorted(missing_codes):
        if ic not in code_to_conn:
            continue
        detail = fetch_connection_detail(account_id, ic)
        if isinstance(detail, dict) and "_error" not in detail:
            spec = _build_connection_spec(detail)
            spec.is_dependency = True
            deps.append(spec)

    return deps


# -- Main: Step 1 -- Source Selection ------------------------------------------
st.header("Replicate Connections")
st.markdown("Copy connections and routing rules from a source account to your target organization via API.")

st.subheader("Step 1: Select Source Account")

raw_accounts = fetch_accounts(source_org_code)
accounts = [a for a in raw_accounts if "_error" not in a]

if not accounts:
    st.error("No accounts found. Check your ORGANIZATION_CODE and network.")
    st.stop()

accounts_sorted = sorted(accounts, key=lambda a: a.get("name", ""))
account_options = {f"{a['name']} ({a['code_live'][:8]}...)": a for a in accounts_sorted}

selected_label = st.selectbox("Source account", ["-- Select --"] + list(account_options.keys()))

if selected_label == "-- Select --":
    st.info("Select a source account to see its connections.")
    st.stop()

account = account_options[selected_label]
account_id = account["code_live"]

# Fetch connections for the selected account
with st.spinner(f"Fetching connections for {account.get('name')}..."):
    raw_connections = fetch_connections(account_id)

connections = [c for c in raw_connections if "_error" not in c]

if not connections:
    st.warning("No connections found for this account.")
    st.stop()

# Build table with checkboxes
select_all = st.checkbox(
    f"Select all ({len(connections)} connections)",
    value=False,
)

conn_rows = []
for conn in connections:
    cid = conn_id(conn)
    conn_rows.append({
        "Select": select_all,
        "Name": conn.get("name", ""),
        "Provider": conn_provider(conn),
        "Country": conn.get("country", ""),
        "Status": conn.get("status", ""),
        "Connection ID": cid,
    })

df = pd.DataFrame(conn_rows)
edited_df = st.data_editor(
    df,
    column_config={
        "Select": st.column_config.CheckboxColumn("Select", default=False),
    },
    disabled=["Name", "Provider", "Country", "Status", "Connection ID"],
    use_container_width=True,
    hide_index=True,
    key="connection_selector",
)

selected_indices = edited_df[edited_df["Select"]].index.tolist()
selected_conn_ids = [conn_rows[i]["Connection ID"] for i in selected_indices]

if not selected_conn_ids:
    st.info("Select one or more connections to replicate.")
    st.stop()

st.success(f"{len(selected_conn_ids)} connection(s) selected.")

# -- Main: Step 2 -- Review Plan -----------------------------------------------
st.subheader("Step 2: Review Plan")

# Fetch full details for selected connections
connection_specs: list[ConnectionSpec] = []
unmatched_mappings: dict[str, list] = {}  # conn_name -> list of unmatched FieldMappings

with st.spinner("Loading connection details..."):
    for cid in selected_conn_ids:
        detail = fetch_connection_detail(account_id, cid)
        if isinstance(detail, dict) and "_error" not in detail:
            spec = _build_connection_spec(detail)
            connection_specs.append(spec)

            # Pre-compute fuzzy matching (param_ids as both source and labels for preview)
            param_ids = [p.param_id for p in spec.params]
            mappings = match_params(param_ids, param_ids)
            unmatched = [m for m in mappings if m.confidence == "unmatched"]
            if unmatched:
                unmatched_mappings[spec.connection_name] = unmatched

if not connection_specs:
    st.error("Could not load details for any selected connection.")
    st.stop()

# Build routing specs (smart: query routing-ms for actual published routing)
routing_details: dict[str, PublishedRouting] = {}
dependency_specs: list[ConnectionSpec] = []
if include_routing:
    all_pms_count = sum(len(s.payment_methods) for s in connection_specs)
    with st.spinner(f"Querying routing status for {all_pms_count} payment methods..."):
        routing_specs, routing_details = _build_smart_routing_specs(
            connection_specs, account_id,
        )
    # Auto-detect missing connections required by routing condition sets
    if routing_specs:
        with st.spinner("Resolving routing dependencies..."):
            dependency_specs = resolve_routing_dependencies(
                connection_specs, routing_specs, connections, account_id,
            )
        if dependency_specs:
            connection_specs.extend(dependency_specs)
            # Re-build routing specs now that we have the full set of connections
            with st.spinner("Re-analyzing routing with dependency connections..."):
                routing_specs, routing_details = _build_smart_routing_specs(
                    connection_specs, account_id,
                )
else:
    routing_specs = []

# Summary
selected_count = sum(1 for s in connection_specs if not s.is_dependency)
dep_count = sum(1 for s in connection_specs if s.is_dependency)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Selected connections", selected_count)
col2.metric("Auto-added dependencies", dep_count)
col3.metric("Routing rules to create", len(routing_specs))
if include_routing:
    all_pms_count = len({pm for s in connection_specs for pm in s.payment_methods})
    col4.metric("PMs with published routing", f"{len(routing_specs)}/{all_pms_count}")

# Detail expanders — separate selected from dependencies
selected_specs = [s for s in connection_specs if not s.is_dependency]
dep_specs_display = [s for s in connection_specs if s.is_dependency]

for spec in selected_specs:
    with st.expander(f"{spec.connection_name} ({spec.provider_id} / {spec.country})"):
        st.markdown(f"**Provider:** {spec.provider_id}")
        st.markdown(f"**Country:** {spec.country}")
        st.markdown(f"**Payment Methods:** {', '.join(spec.payment_methods) if spec.payment_methods else 'None'}")
        st.markdown(f"**Parameters ({len(spec.params)}):**")
        for p in spec.params:
            st.code(f"[{p.country}] {p.param_id} = {_truncate_value(p.value)}", language="text")

if dep_specs_display:
    st.markdown("#### Auto-added dependencies")
    st.caption("These connections are referenced by routing condition sets and will be created automatically.")
    for spec in dep_specs_display:
        with st.expander(f"[DEP] {spec.connection_name} ({spec.provider_id} / {spec.country})"):
            st.markdown(f"**Provider:** {spec.provider_id}")
            st.markdown(f"**Country:** {spec.country}")
            st.markdown(f"**Payment Methods:** {', '.join(spec.payment_methods) if spec.payment_methods else 'None'}")
            st.markdown(f"**Parameters ({len(spec.params)}):**")
            for p in spec.params:
                st.code(f"[{p.country}] {p.param_id} = {_truncate_value(p.value)}", language="text")

# Show unmatched warnings
if unmatched_mappings:
    st.warning("Some parameters could not be auto-matched to dashboard form fields. They will be filled by position during creation.")
    for conn_name, unmatched in unmatched_mappings.items():
        st.caption(f"{conn_name}: {', '.join(m.param_id for m in unmatched)}")

if include_routing and routing_specs:
    # Build lookup sets for marker display
    selected_codes = {s.integration_code for s in connection_specs if s.integration_code and not s.is_dependency}
    dep_codes = {s.integration_code for s in connection_specs if s.integration_code and s.is_dependency}
    all_codes = selected_codes | dep_codes

    with st.expander(f"Routing rules to create ({len(routing_specs)} PMs)", expanded=True):
        for rs in routing_specs:
            routing = routing_details.get(rs.payment_method)
            if routing:
                n_sets = len(routing.condition_sets)
                st.markdown(
                    f"**{rs.payment_method}** -> {rs.connection_name} "
                    f"| Source: {n_sets} condition set(s) | Version: _{routing.version_name}_"
                )
                # Show condition sets details with markers
                for cs in routing.condition_sets:
                    route_parts: list[str] = []
                    for r in cs.routes:
                        code_short = r.integration_code[:8] + "..." if r.integration_code else "?"
                        if r.integration_code in selected_codes:
                            route_parts.append(f"**{r.provider_name}** ({code_short}) [SELECTED]")
                        elif r.integration_code in dep_codes:
                            route_parts.append(f"**{r.provider_name}** ({code_short}) [DEP]")
                        elif r.integration_code in all_codes:
                            route_parts.append(f"{r.provider_name} ({code_short})")
                        else:
                            route_parts.append(f"~~{r.provider_name}~~ ({code_short}) [MISSING]")
                    conn_names = ", ".join(route_parts)
                    st.caption(
                        f"  {cs.sort_number}. {cs.display_label} -> {conn_names}"
                    )
            else:
                st.markdown(f"- **{rs.payment_method}** -> {rs.connection_name}")

    # Show PMs that have NO routing (skipped)
    all_pms = {pm for s in connection_specs for pm in s.payment_methods}
    routed_pms = {rs.payment_method for rs in routing_specs}
    skipped_pms = sorted(all_pms - routed_pms)
    if skipped_pms:
        with st.expander(f"Skipped PMs ({len(skipped_pms)} - no published routing or not referencing selected connections)"):
            st.caption(", ".join(skipped_pms))

# -- Main: Step 3 -- Execute ---------------------------------------------------
st.subheader("Step 3: Execute Replication")

can_execute = bool(target_org_code and target_account_name and connection_specs)

if not target_org_code or not target_account_name:
    st.warning("Enter the target organization code and account name in the sidebar to enable replication.")

if st.button("Replicate", disabled=not can_execute, type="primary"):
    progress_bar = st.progress(0, text="Starting replication...")
    log_container = st.container()
    log_lines: list[str] = []

    def on_progress(message: str, fraction: float) -> None:
        progress_bar.progress(min(fraction, 1.0), text=message)
        log_lines.append(message)
        log_container.text("\n".join(log_lines))

    replicator = Replicator(
        connections=connection_specs,
        routings=routing_specs,
        target_org_code=target_org_code,
        target_account_name=target_account_name,
        on_progress=on_progress,
    )

    with st.spinner("Running API replication..."):
        result = replicator.execute()

    progress_bar.progress(1.0, text="Done!")

    # Results summary
    st.markdown("---")
    st.subheader("Results")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total steps", len(result.steps))
    col2.metric("Succeeded", result.success_count)
    col3.metric("Failed", result.failure_count)

    if result.all_succeeded:
        st.success("All steps completed successfully!")
    else:
        st.warning(f"{result.failure_count} step(s) failed. See details below.")

    # Step details
    for step in result.steps:
        icon = "\u2705" if step.success else "\u274c"
        with st.expander(f"{icon} {step.step_name}"):
            st.markdown(step.message)
