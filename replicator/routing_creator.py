"""Create and publish routing rules via the routing-ms REST API.

Replaces the old Playwright-based approach with direct API calls:
  1. Find target integration codes (POST /v1/connections/providers)
  2. Build condition sets from source routing data
  3. Create draft (POST /v1/)
  4. Update with condition sets (PUT /v1/{version_code})
  5. Publish (POST /v1/{version_code}/publish)
"""

from __future__ import annotations

import logging

import requests

from config import INTERNAL_API_BASE
from replicator.models import RoutingSpec, StepResult

log = logging.getLogger(__name__)

ROUTING_BASE = f"{INTERNAL_API_BASE}/routing-ms/v1"
_COMMON_HEADERS = {
    "Content-Type": "application/json",
    "x-user-code": "00000000-0000-0000-0000-000000000000",
}


def _headers(account_code: str, org_code: str = "") -> dict[str, str]:
    h = {
        **_COMMON_HEADERS,
        "x-account-code": account_code,
    }
    if org_code:
        h["x-organization-code"] = org_code
    return h


# ---------------------------------------------------------------------------
# Low-level API calls
# ---------------------------------------------------------------------------

def find_target_integration_code(
    account_code: str,
    provider_id: str,
    payment_method: str,
    country: str,
    org_code: str = "",
    retries: int = 3,
    retry_delay: float = 3.0,
) -> str | None:
    """Find the integration_code for a provider in the target account.

    POST /v1/connections/providers with payment_method + country filters,
    then match by provider_id. Retries to handle eventual consistency after
    connection creation.
    """
    import time

    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{ROUTING_BASE}/connections/providers",
                headers=_headers(account_code, org_code),
                json={"payment_method": payment_method, "country": country},
                timeout=15,
            )
            if resp.status_code in (400, 404):
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            if resp.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            data = resp.json()
        except Exception:
            if attempt < retries - 1:
                time.sleep(retry_delay)
                continue
            return None

        providers = data.get("providers", data if isinstance(data, list) else [])
        for p in providers:
            pid = p.get("provider_id") or p.get("providerId") or ""
            if pid.upper() == provider_id.upper():
                return (
                    p.get("account_integration_code")
                    or p.get("accountIntegrationCode")
                    or p.get("integration_code")
                    or p.get("integrationCode")
                )

        # Provider not found yet — retry if connections were just created
        if attempt < retries - 1:
            log.info(
                "Provider %s not found for %s (attempt %d/%d), retrying in %.0fs...",
                provider_id, payment_method, attempt + 1, retries, retry_delay,
            )
            time.sleep(retry_delay)

    return None


def create_routing_draft(
    account_code: str,
    payment_method: str,
    org_code: str = "",
) -> str | None:
    """Create a new routing draft. Returns the version code or None."""
    try:
        resp = requests.post(
            f"{ROUTING_BASE}/",
            headers=_headers(account_code, org_code),
            json={"payment_method": payment_method},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("create_routing_draft failed: %s %s", resp.status_code, resp.text[:300])
            return None
        body = resp.json()
        return body.get("version", {}).get("code")
    except Exception as e:
        log.warning("create_routing_draft exception: %s", e)
        return None


def update_routing_version(
    account_code: str,
    version_code: str,
    condition_sets: list[dict],
    org_code: str = "",
) -> bool:
    """Update a routing draft with condition sets. Returns True on success."""
    body = {
        "version": {"code": version_code, "status": "DRAFT"},
        "condition_sets": condition_sets,
    }
    try:
        resp = requests.put(
            f"{ROUTING_BASE}/{version_code}",
            headers=_headers(account_code, org_code),
            json=body,
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("update_routing_version failed: %s %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as e:
        log.warning("update_routing_version exception: %s", e)
        return False


def publish_routing_version(
    account_code: str,
    version_code: str,
    org_code: str = "",
) -> bool:
    """Publish a routing version. Returns True on success."""
    try:
        resp = requests.post(
            f"{ROUTING_BASE}/{version_code}/publish",
            headers=_headers(account_code, org_code),
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("publish_routing_version failed: %s %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as e:
        log.warning("publish_routing_version exception: %s", e)
        return False


# ---------------------------------------------------------------------------
# Condition set building
# ---------------------------------------------------------------------------

def build_target_condition_sets(
    source_condition_sets_raw: list[dict],
    integration_code_map: dict[str, str],
) -> list[dict]:
    """Build target condition sets by remapping integration codes.

    Args:
        source_condition_sets_raw: Raw condition_sets JSON from the source
            routing GET response.
        integration_code_map: ``{source_integration_code: target_integration_code}``

    Returns:
        List of condition set dicts ready for the PUT body.
    """
    result: list[dict] = []

    for cs in source_condition_sets_raw:
        source_routes = cs.get("routes", [])
        mapped_routes: list[dict] = []

        for route in source_routes:
            route_type = route.get("type", "")

            if route_type == "PROVIDER":
                src_code = route.get("data", {}).get("integration_code", "")
                target_code = integration_code_map.get(src_code)
                if target_code is None:
                    # Source integration not available in target — skip route
                    continue
                mapped_route = {
                    "type": "PROVIDER",
                    "data": {
                        **route.get("data", {}),
                        "integration_code": target_code,
                    },
                }
                # Copy outputs if present
                if "outputs" in route:
                    mapped_route["outputs"] = route["outputs"]
                mapped_routes.append(mapped_route)

            elif route_type == "ENDING":
                mapped_routes.append({
                    "type": "ENDING",
                    "data": route.get("data", {}),
                })

            else:
                # AUTHENTICATION, FRAUD, etc. — keep as-is
                mapped_routes.append({
                    "type": route_type,
                    "data": route.get("data", {}),
                    **({"outputs": route["outputs"]} if "outputs" in route else {}),
                })

        # Skip condition set if no PROVIDER routes remain
        has_provider = any(r.get("type") == "PROVIDER" for r in mapped_routes)
        if not has_provider:
            continue

        # Re-index routes sequentially and fix next_route_indexes
        _reindex_routes(mapped_routes)

        # Build condition set preserving required fields from source
        target_cs: dict = {
            "conditions": cs.get("conditions", []),
            "routes": mapped_routes,
            "category": cs.get("category", "PAYMENT"),
        }
        # Preserve optional fields the API may need
        if "start" in cs:
            target_cs["start"] = cs["start"]
        if "sort_number" in cs:
            target_cs["sort_number"] = cs["sort_number"]

        result.append(target_cs)

    # Ensure at least one catch-all condition set
    has_catch_all = any(
        any(
            c.get("condition_type") == "EMPTY_CONDITION"
            for c in cs.get("conditions", [])
        )
        for cs in result
    )
    if not has_catch_all and result:
        # Convert the last condition set to catch-all
        result[-1]["conditions"] = [{"condition_type": "EMPTY_CONDITION", "values": [], "conditional": "EQUAL"}]
        result[-1].setdefault("category", "PAYMENT")

    return result


def _reindex_routes(routes: list[dict]) -> None:
    """Re-index routes 0..N-1 and fix all next_route_indexes references."""
    # Build old-index → new-index mapping
    old_to_new: dict[int, int] = {}
    for new_idx, route in enumerate(routes):
        old_idx = route.pop("index", new_idx)
        old_to_new[old_idx] = new_idx
        route["index"] = new_idx

    # Fix next_route_indexes in outputs (routing-ms uses snake_case)
    for route in routes:
        for output in route.get("outputs", []):
            # Handle both snake_case (from real API) and camelCase (just in case)
            old_refs = output.get("next_route_indexes") or output.get("nextRouteIndexes") or []
            new_refs = [old_to_new[ref] for ref in old_refs if ref in old_to_new]
            # Write back in snake_case (API format)
            output["next_route_indexes"] = new_refs
            # Remove camelCase variant if present
            output.pop("nextRouteIndexes", None)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_routing_rule_api(
    target_org_code: str,
    account_code: str,
    spec: RoutingSpec,
    known_integration_map: dict[str, str] | None = None,
) -> StepResult:
    """Create and publish a routing rule for a payment method via API.

    Args:
        target_org_code: Target organization code.
        account_code: Target account code.
        spec: Routing specification with source_condition_sets_raw.
        known_integration_map: Pre-built map of source_integration_code ->
            target_integration_code (from connection creation step).
            If provided, skips the connections/providers API lookup.

    Returns:
        StepResult indicating success or failure.
    """
    step_name = f"Create routing: {spec.payment_method} -> {spec.connection_name}"

    if not spec.source_condition_sets_raw:
        return StepResult(
            success=False,
            step_name=step_name,
            message=f"No source condition sets for {spec.payment_method}. Cannot create routing.",
        )

    try:
        # Step 1: Build integration_code map
        # Collect unique (provider_id, integration_code) pairs from source
        source_integrations: dict[str, str] = {}  # integration_code -> provider_id
        for cs in spec.source_condition_sets_raw:
            for route in cs.get("routes", []):
                if route.get("type") == "PROVIDER":
                    data = route.get("data", {})
                    ic = data.get("integration_code", "")
                    pid = data.get("provider_id", "")
                    if ic and pid:
                        source_integrations[ic] = pid

        # Use pre-built map if available, otherwise fall back to API lookup
        integration_code_map: dict[str, str] = {}
        if known_integration_map:
            for src_code in source_integrations:
                if src_code in known_integration_map:
                    integration_code_map[src_code] = known_integration_map[src_code]
                else:
                    log.info(
                        "Source integration %s not in known map — skipping",
                        src_code,
                    )
        else:
            for src_code, provider_id in source_integrations.items():
                target_code = find_target_integration_code(
                    account_code, provider_id, spec.payment_method, "GLOBAL",
                    org_code=target_org_code,
                )
                if target_code:
                    integration_code_map[src_code] = target_code
                else:
                    log.info(
                        "Provider %s not found in target for %s — routes using it will be skipped",
                        provider_id, spec.payment_method,
                    )

        if not integration_code_map:
            return StepResult(
                success=False,
                step_name=step_name,
                message=(
                    f"No matching providers found in target account for {spec.payment_method}. "
                    f"Source providers: {list(source_integrations.values())}"
                ),
            )

        # Step 2: Build target condition sets
        target_condition_sets = build_target_condition_sets(
            spec.source_condition_sets_raw, integration_code_map,
        )

        if not target_condition_sets:
            return StepResult(
                success=False,
                step_name=step_name,
                message=f"No valid condition sets after mapping for {spec.payment_method}.",
            )

        # Step 3: Create draft
        draft_code = create_routing_draft(account_code, spec.payment_method, org_code=target_org_code)
        if not draft_code:
            return StepResult(
                success=False,
                step_name=step_name,
                message=f"Failed to create routing draft for {spec.payment_method}.",
            )

        # Step 4: Update with condition sets
        if not update_routing_version(account_code, draft_code, target_condition_sets, org_code=target_org_code):
            return StepResult(
                success=False,
                step_name=step_name,
                message=f"Failed to update routing version {draft_code} with condition sets.",
            )

        # Step 5: Publish
        if not publish_routing_version(account_code, draft_code, org_code=target_org_code):
            return StepResult(
                success=False,
                step_name=step_name,
                message=(
                    f"Routing draft {draft_code} created and configured but failed to publish. "
                    f"Manual publish may be needed."
                ),
            )

        n_sets = len(target_condition_sets)
        n_providers = len(integration_code_map)
        return StepResult(
            success=True,
            step_name=step_name,
            message=(
                f"Routing for {spec.payment_method} created and published via API. "
                f"{n_sets} condition set(s), {n_providers} provider(s) mapped."
            ),
        )

    except Exception as e:
        return StepResult(
            success=False,
            step_name=step_name,
            message=f"Failed to create routing rule: {e}",
        )
