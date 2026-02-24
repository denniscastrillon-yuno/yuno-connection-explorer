"""Account management via Yuno internal APIs (no Playwright)."""

from __future__ import annotations

import logging

import requests

from config import INTERNAL_API_BASE

log = logging.getLogger(__name__)

_ORG_USER_BASE = f"{INTERNAL_API_BASE}/organization-user-ms/v1"


def _org_headers(org_code: str) -> dict[str, str]:
    return {
        "x-organization-code": org_code,
        "Content-Type": "application/json",
    }


def _get_user_code(org_code: str) -> str:
    """GET /organization-user-ms/v1/organizations/{org}/users -> first active user code."""
    url = f"{_ORG_USER_BASE}/organizations/{org_code}/users"
    resp = requests.get(url, headers=_org_headers(org_code), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # Response shape: {"active": [...], "pending": [...]} or plain list
    if isinstance(data, dict):
        users = data.get("active", data.get("data", []))
    else:
        users = data
    if not users:
        raise RuntimeError("No users found in the target organization.")
    # User code field is "code" (not "user_code")
    return users[0].get("code") or users[0].get("user_code", "")


def _list_accounts(org_code: str) -> list[dict]:
    """GET /organization-user-ms/v1/accounts/by-organization -> all accounts."""
    url = f"{_ORG_USER_BASE}/accounts/by-organization"
    resp = requests.get(url, headers=_org_headers(org_code), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []


def _find_account(org_code: str, account_name: str) -> str | None:
    """Search accounts list for matching name -> return code_live or None."""
    accounts = _list_accounts(org_code)
    upper_name = account_name.upper()
    for acc in accounts:
        if (acc.get("name", "")).upper() == upper_name:
            return acc.get("code_live")
    return None


def _create_account(org_code: str, account_name: str, user_code: str) -> str:
    """POST /organization-user-ms/v1/accounts -> return code_live."""
    url = f"{_ORG_USER_BASE}/accounts"
    headers = {
        **_org_headers(org_code),
        "x-user-code": user_code,
    }
    body = {"name": account_name}
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    code = data.get("code_live")
    if not code:
        raise RuntimeError(f"Account created but no code_live in response: {data}")
    return code


def ensure_account(target_org_code: str, account_name: str) -> tuple[str, str]:
    """Find or create account in the TARGET organization.

    Args:
        target_org_code: Organization code where the account should exist.
        account_name: Desired account name (max 32 chars).

    Returns:
        Tuple of (actual_account_name, code_live).

    Raises:
        RuntimeError: If account creation fails and lookup also fails.
    """
    account_name = account_name[:32]

    # Try to find existing account first
    existing_code = _find_account(target_org_code, account_name)
    if existing_code:
        log.info("Account '%s' already exists: %s", account_name, existing_code[:8])
        return account_name, existing_code

    # Create new account
    try:
        user_code = _get_user_code(target_org_code)
        code_live = _create_account(target_org_code, account_name, user_code)
        log.info("Account '%s' created: %s", account_name, code_live[:8])
        return account_name, code_live
    except requests.HTTPError as e:
        # 400 likely means name already exists (race condition) — look it up
        if e.response is not None and e.response.status_code == 400:
            log.info("Account creation returned 400, looking up existing account...")
            existing_code = _find_account(target_org_code, account_name)
            if existing_code:
                return account_name, existing_code
        raise RuntimeError(f"Failed to create account '{account_name}': {e}") from e
