"""Fetch full routing details from routing-ms API (no auth required).

Uses the internal staging API to query published routing for any account+PM.
The flow for each PM:
  1. GET /routing-ms/v1/by-payment-method/{pm} → returns versions[]
  2. Find version with status: "PUBLISHED" → get its code
  3. GET /routing-ms/v1/{published_code} → full routing details
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import INTERNAL_API_BASE
from replicator.models import (
    ConditionSetData,
    PublishedRouting,
    RouteConnection,
    RoutingCondition,
)

ROUTING_BASE = f"{INTERNAL_API_BASE}/routing-ms/v1"
_COMMON_HEADERS = {
    "Content-Type": "application/json",
    "x-user-code": "00000000-0000-0000-0000-000000000000",
}


def _headers(account_code: str) -> dict[str, str]:
    return {**_COMMON_HEADERS, "x-account-code": account_code}


# ---------------------------------------------------------------------------
# Low-level API calls
# ---------------------------------------------------------------------------

def _get_version_details(account_code: str, version_code: str) -> dict | None:
    """GET full routing details for a specific version."""
    try:
        resp = requests.get(
            f"{ROUTING_BASE}/{version_code}",
            headers=_headers(account_code),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# High-level: fetch published routing for a single PM
# ---------------------------------------------------------------------------

def fetch_routing_for_pm(account_code: str, payment_method: str) -> dict | None:
    """Fetch the full published routing for a PM in the given account.

    Returns the full routing dict (workflow + version + condition_sets) or None
    if the PM has no published routing.
    """
    # Step 1: GET by-payment-method to discover versions
    try:
        resp = requests.get(
            f"{ROUTING_BASE}/by-payment-method/{payment_method}",
            headers=_headers(account_code),
            timeout=15,
        )
        if resp.status_code in (400, 404):
            return None
        if resp.status_code != 200:
            return None
        body = resp.json()
    except Exception:
        return None

    # Step 2: Find the published version code
    versions = body.get("versions", [])
    published_code = None
    for v in versions:
        if isinstance(v, dict) and v.get("status") == "PUBLISHED":
            published_code = v.get("code")
            break

    if not published_code:
        # Some responses return the version directly at top level
        if body.get("version", {}).get("status") == "PUBLISHED":
            published_code = body["version"].get("code")

    if not published_code:
        return None

    # Step 3: Fetch full details for the published version
    return _get_version_details(account_code, published_code)


# ---------------------------------------------------------------------------
# Batch fetch for multiple PMs (concurrent)
# ---------------------------------------------------------------------------

def fetch_routing_batch(
    account_code: str,
    payment_methods: list[str],
    max_workers: int = 10,
) -> dict[str, dict]:
    """Fetch routing for multiple PMs concurrently.

    Returns ``{pm: raw_routing_dict}`` for PMs that have published routing.
    PMs without routing are omitted.
    """
    results: dict[str, dict] = {}

    def _fetch(pm: str) -> tuple[str, dict | None]:
        return pm, fetch_routing_for_pm(account_code, pm)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, pm): pm for pm in payment_methods}
        for future in as_completed(futures):
            try:
                pm, data = future.result()
                if data is not None:
                    results[pm] = data
            except Exception:
                continue

    return results


# ---------------------------------------------------------------------------
# Parse raw routing JSON into model objects
# ---------------------------------------------------------------------------

def parse_published_routing(pm: str, raw: dict) -> PublishedRouting:
    """Parse raw routing-ms response into a PublishedRouting model."""
    version = raw.get("version", {})
    parsed_sets: list[ConditionSetData] = []

    for cs in raw.get("condition_sets", []):
        conditions: list[RoutingCondition] = []
        for c in cs.get("conditions", []):
            conditions.append(RoutingCondition(
                condition_type=c.get("condition_type", ""),
                values=c.get("values", []),
                conditional=c.get("conditional", ""),
                metadata_key=c.get("metadata_key"),
            ))

        routes: list[RouteConnection] = []
        for r in cs.get("routes", []):
            data = r.get("data", {})
            routes.append(RouteConnection(
                integration_code=data.get("integration_code", ""),
                provider_id=data.get("provider_id", ""),
                provider_name=data.get("provider_name", ""),
                network_token_on=data.get("network_token_on", False),
            ))

        is_catch_all = any(
            c.condition_type == "EMPTY_CONDITION" for c in conditions
        )
        parsed_sets.append(ConditionSetData(
            sort_number=cs.get("sort_number", 0),
            editable=cs.get("editable", True),
            conditions=conditions,
            routes=routes,
            is_catch_all=is_catch_all,
        ))

    # Sort by sort_number to preserve original order
    parsed_sets.sort(key=lambda s: s.sort_number)

    return PublishedRouting(
        payment_method=pm,
        version_name=version.get("name", ""),
        condition_sets=parsed_sets,
    )


# ---------------------------------------------------------------------------
# Analyze routing relevance for selected connections
# ---------------------------------------------------------------------------

def pick_connection_for_pm(
    routing: PublishedRouting,
    our_codes: dict[str, str],
) -> str | None:
    """Pick the best connection for a PM's catch-all routing.

    Args:
        routing: Parsed published routing.
        our_codes: ``{integration_code: connection_name}`` for connections
                   being replicated.

    Returns the connection_name to use, or None if the PM doesn't reference
    any of our connections.

    Priority:
      1. Connection in the catch-all condition set (matching source behavior).
      2. First connection found in any condition set.
    """
    # Check catch-all first
    for cs in routing.condition_sets:
        if cs.is_catch_all:
            for route in cs.routes:
                if route.integration_code in our_codes:
                    return our_codes[route.integration_code]

    # Fallback: first match in any condition set
    for cs in routing.condition_sets:
        for route in cs.routes:
            if route.integration_code in our_codes:
                return our_codes[route.integration_code]

    return None
