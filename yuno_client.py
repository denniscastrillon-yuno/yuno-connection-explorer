import requests
from config import INTERNAL_API_BASE


def _headers(account_id: str) -> dict[str, str]:
    return {
        "x-account-code": account_id,
        "Content-Type": "application/json",
    }


def list_accounts(org_code: str) -> list[dict]:
    """Fetch all accounts for an organization dynamically."""
    url = f"{INTERNAL_API_BASE}/organization-user-ms/v1/accounts/by-organization"
    headers = {
        "x-organization-code": org_code,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"_error": str(e)}]

    data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return [{"_error": f"Unexpected response type: {type(data)}"}]


def list_connections(account_id: str) -> list[dict]:
    """Fetch all connections for a given account."""
    url = f"{INTERNAL_API_BASE}/organization-ms/v1/connections/"
    try:
        resp = requests.get(url, headers=_headers(account_id), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"_error": str(e)}]

    data = resp.json()
    if isinstance(data, list):
        return data
    return [{"_error": f"Unexpected response type: {type(data)}"}]


def get_connection(account_id: str, connection_id: str) -> dict:
    """Fetch details for a single connection."""
    url = f"{INTERNAL_API_BASE}/organization-ms/v1/connections/{connection_id}"
    try:
        resp = requests.get(url, headers=_headers(account_id), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"_error": str(e)}
