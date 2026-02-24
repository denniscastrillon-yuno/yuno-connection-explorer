# CLAUDE.md

## Project Overview

**Yuno Connection Explorer** is a Streamlit dashboard that dynamically discovers and displays all payment provider connections configured in a Yuno organization. It uses Yuno's internal staging APIs to list accounts, their connections, and full connection details including credentials and parameters.

This tool is designed for QA engineers and integration developers who need to quickly inspect provider configurations without navigating the Yuno Dashboard.

## Architecture

```
Streamlit App (app.py)
  ├── config.py          # Environment variables (org code, API base)
  ├── yuno_client.py     # HTTP client for Yuno internal APIs
  └── .env               # Runtime configuration
```

### Data Flow

```
App startup
  │
  ▼
list_accounts(org_code)
  → GET /organization-user-ms/v1/accounts/by-organization
  → Header: x-organization-code
  → Returns: [{code_live, code_testing, name, organization_code, ...}]
  │
  ▼
User selects account in sidebar
  │
  ▼
list_connections(account_id)
  → GET /organization-ms/v1/connections/
  → Header: x-account-code
  → Returns: [{code, name, status, provider: {provider_id, name, icon}, payment_methods: [...]}]
  │
  ▼
User expands a connection
  │
  ▼
get_connection(account_id, connection_id)
  → GET /organization-ms/v1/connections/{code}
  → Header: x-account-code
  → Returns: {connection_name, provider_id, country, params: [{param_id, value, country, type}], ...}
```

## Essential Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run
streamlit run app.py

# Run headless (no browser auto-open)
streamlit run app.py --server.headless true
```

## File Responsibilities

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI: sidebar with dynamic account selector, search filter, data tables, expandable detail cards with credentials. Handles single-account and all-accounts (concurrent) flows. |
| `yuno_client.py` | HTTP client wrapping 3 Yuno internal API endpoints. Uses `_error` sentinel pattern for error propagation. |
| `config.py` | Loads `.env` via python-dotenv. Exports `INTERNAL_API_BASE` and `ORGANIZATION_CODE`. |
| `.env` | Runtime config. Only `ORGANIZATION_CODE` needed. Not committed to git. |

## API Endpoints Used

All endpoints hit `https://internal-staging.y.uno` (no auth tokens required):

| Method | Endpoint | Key Header | Purpose |
|--------|----------|------------|---------|
| GET | `/organization-user-ms/v1/accounts/by-organization` | `x-organization-code` | List all accounts in the org |
| GET | `/organization-ms/v1/connections/` | `x-account-code` | List connections for an account |
| GET | `/organization-ms/v1/connections/{code}` | `x-account-code` | Get connection detail with credentials |

## API Response Shapes

### Accounts (`list_accounts`)
```json
[{
  "code_live": "552aa0b7-...",
  "code_testing": "abc123-...",
  "name": "STRIPE",
  "created_at": "2023-09-12T...",
  "organization_code": "6fd95f92-..."
}]
```

### Connections list (`list_connections`)
```json
[{
  "code": "9dc116b1-...",
  "name": "STRIPE_CARD",
  "status": "COMPLETED",
  "archive": false,
  "provider": {
    "provider_id": "STRIPE",
    "name": "Stripe",
    "icon": "https://icons.prod.y.uno/stripe_logosimbolo.png"
  },
  "payment_methods": [{"payment_method_id": "CARD", "name": "Card"}]
}]
```
Key: connection ID is in `code` field (not `id`). Provider is a nested object.

### Connection detail (`get_connection`)
```json
{
  "connection_name": "STRIPE_CARD",
  "account_integration_code": "9dc116b1-...",
  "account_code": "552aa0b7-...",
  "provider_id": "STRIPE",
  "country": "GLOBAL",
  "params": [
    {"country": "GLOBAL", "type": "API", "param_id": "SECRET_KEY", "value": "sk_test_..."},
    {"country": "GLOBAL", "type": "API", "param_id": "PUBLIC_KEY", "value": "pk_test_..."}
  ],
  "payment_method": ["CARD", "Card"],
  "test_credentials": false,
  "costs": []
}
```
Key: credentials live inside `params` array as `{param_id, value}` pairs.

## Key Design Decisions

- **Dynamic account discovery**: No hardcoded provider-to-account mapping. Accounts are fetched from the API at startup and cached for 5 minutes.
- **`_error` sentinel pattern**: API errors are returned as `{"_error": "message"}` dicts mixed into result lists, allowing partial success (some accounts fail, others succeed).
- **`_conn_id()` / `_conn_provider()` helpers**: Defensive extraction that handles multiple possible field names across the list and detail endpoints.
- **ThreadPoolExecutor(20 workers)**: "All Accounts" mode fetches connections concurrently with a progress bar.
- **Streamlit caching**: `@st.cache_data(ttl=300)` on all API calls to avoid redundant requests.

## Development Notes

- The app connects to **staging** internal APIs only. No production endpoints are used.
- The `ORGANIZATION_CODE` default (`6fd95f92-...`) is the Yuno QA/Integrations org in staging.
- Network access to `internal-staging.y.uno` is required (VPN or internal network).
- Python 3.10+ required (uses `list[dict]` type hints).

## When Modifying This Project

- If the API response shape changes, update `_conn_id()`, `_conn_provider()`, and `_render_connection_detail()` in `app.py`.
- If new API endpoints are needed, add them to `yuno_client.py` following the existing pattern.
- Keep `config.py` minimal — only environment variables, no business logic.
- The `.env` file is gitignored. Use `.env.example` as template.
