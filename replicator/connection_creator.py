"""Create connections via Yuno internal APIs (no Playwright)."""

from __future__ import annotations

import logging

import requests

from config import INTERNAL_API_BASE
from replicator.models import ConnectionSpec, StepResult

log = logging.getLogger(__name__)

_ORG_BASE = f"{INTERNAL_API_BASE}/organization-ms/v1"


def _list_connections(account_code: str) -> list[dict]:
    """GET /organization-ms/v1/connections/ -> existing connections."""
    url = f"{_ORG_BASE}/connections/"
    headers = {
        "x-account-code": account_code,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("Failed to list connections: %s", e)
        return []


def _connection_exists(account_code: str, connection_name: str) -> bool:
    """Check if connection already exists (by name)."""
    connections = _list_connections(account_code)
    upper_name = connection_name.upper()
    for conn in connections:
        if (conn.get("name", "")).upper() == upper_name:
            return True
    return False


def create_connection_api(
    target_org_code: str,
    account_code: str,
    spec: ConnectionSpec,
) -> StepResult:
    """Create a connection via POST /organization-ms/v1/organizations/{org}/integrations.

    Args:
        target_org_code: Target organization code.
        account_code: Target account code_live.
        spec: Connection specification with provider, name, params.

    Returns:
        StepResult with integration_code on success.
    """
    step_name = f"Create connection: {spec.connection_name}"

    try:
        # Idempotency check
        if _connection_exists(account_code, spec.connection_name):
            return StepResult(
                success=True,
                step_name=step_name,
                message=f"Connection '{spec.connection_name}' already exists, skipping.",
            )

        # Build params list — skip params with empty values (API rejects them)
        params = [
            {
                "country": p.country,
                "type": p.param_type,
                "param_id": p.param_id,
                "value": p.value,
            }
            for p in spec.params
            if p.value  # skip empty/None values
        ]

        url = f"{_ORG_BASE}/organizations/{target_org_code}/integrations"
        headers = {
            "x-account-code": account_code,
            "x-organization-code": target_org_code,
            "Content-Type": "application/json",
        }
        body = {
            "provider_id": spec.provider_id,
            "name": spec.connection_name,
            "country": spec.country,
            "accounts": [account_code],
            "params": params,
        }

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Extract integration_code from response
        connections_created = data.get("connections_created", [])
        if connections_created:
            integration_code = connections_created[0].get("integration_code", "")
            if integration_code:
                spec.integration_code = integration_code

        return StepResult(
            success=True,
            step_name=step_name,
            message=(
                f"Connection '{spec.connection_name}' created via API. "
                f"Provider: {spec.provider_id}, Params: {len(params)}"
            ),
        )

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body_text = ""
        try:
            body_text = e.response.text[:300] if e.response is not None else ""
        except Exception:
            pass
        return StepResult(
            success=False,
            step_name=step_name,
            message=f"API error {status}: {body_text}",
        )
    except Exception as e:
        return StepResult(
            success=False,
            step_name=step_name,
            message=f"Failed to create connection: {e}",
        )
