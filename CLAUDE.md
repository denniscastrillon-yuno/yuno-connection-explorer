# CLAUDE.md

## Project Overview

**Yuno Connection Explorer** is a multipage Streamlit app with two tools:

1. **Connection Explorer** — dynamically discovers and displays all payment provider connections in a Yuno organization via internal staging APIs.
2. **Replicate Connections** — copies connections and routing rules from a source account to a target organization, entirely via direct API calls (no browser automation).

Designed for QA engineers and integration developers who need to inspect provider configurations and replicate them across organizations.

## Architecture

```
Streamlit Multipage App
├── app.py                           # Landing page with links to both tools
├── helpers.py                       # Shared helpers (fetchers, rendering, extraction)
├── config.py                        # Environment variables (org code, API base)
├── yuno_client.py                   # HTTP client for Yuno internal APIs
├── pages/
│   ├── 1_Connection_Explorer.py     # Browse connections (original app functionality)
│   └── 2_Replicate_Connections.py   # Replicate connections & routing via API
├── replicator/
│   ├── __init__.py
│   ├── models.py                    # Dataclasses: ConnectionSpec, RoutingSpec, routing models
│   ├── param_mapper.py              # Fuzzy matching of API params (for preview only)
│   ├── account_manager.py           # Account creation/lookup via organization-user-ms API
│   ├── connection_creator.py        # Connection creation via organization-ms API
│   ├── routing_creator.py           # Routing rules via routing-ms API
│   ├── routing_fetcher.py           # HTTP client for routing-ms API (read-only)
│   └── orchestrator.py              # Workflow coordinator with progress callbacks
└── .env                             # Runtime configuration (gitignored)
```

### Data Flow — Connection Explorer

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

### Data Flow — Replicate Connections

```
User selects source account + connections (via API)
  │
  ▼
Build ConnectionSpec from API data
  │
  ▼
Smart routing analysis (routing_fetcher.py):
  For each PM the connections support:
    GET /routing-ms/v1/by-payment-method/{pm} → find published version
    GET /routing-ms/v1/{published_code} → full routing details + raw condition_sets
  Filter: only PMs with published routing referencing selected connections
  │
  ▼
Show plan: connections + filtered routing rules with source details
  │
  ▼
Account setup via API:
  1. GET /organization-user-ms/v1/accounts/by-organization → find existing or:
  2. GET /organization-user-ms/v1/organizations/{org}/users → get user_code
  3. POST /organization-user-ms/v1/accounts → create account → get code_live
  │
  ▼
Connection creation via API:
  For each connection:
    1. GET /organization-ms/v1/connections/ → idempotency check (by name)
    2. POST /organization-ms/v1/organizations/{org}/integrations → create connection
  │
  ▼
Routing via API:
  For each routing rule:
    1. POST /v1/connections/providers → find target integration codes
    2. Build condition sets by remapping source → target integration codes
    3. POST /v1/ → create draft
    4. PUT /v1/{code} → update with condition sets
    5. POST /v1/{code}/publish → publish
  │
  ▼
Results with per-step success/failure
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
| `app.py` | Landing page with links to Connection Explorer and Replicate Connections. |
| `helpers.py` | Shared helpers: `conn_id()`, `conn_provider()`, `render_connection_detail()`, cached fetchers (`fetch_accounts`, `fetch_connections`, `fetch_connection_detail`). |
| `yuno_client.py` | HTTP client wrapping 3 Yuno internal API endpoints. Uses `_error` sentinel pattern. |
| `config.py` | Loads `.env` via python-dotenv. Exports `INTERNAL_API_BASE`, `ORGANIZATION_CODE`, `DASHBOARD_URL`. |
| `pages/1_Connection_Explorer.py` | Browse connections: sidebar selector, data tables, expandable detail cards with credentials. Single-account and all-accounts (concurrent) flows. |
| `pages/2_Replicate_Connections.py` | Replicate connections UI: source selection with checkboxes, plan review, execution with progress bar and results. |
| `replicator/models.py` | Dataclasses: `ConnectionParam`, `ConnectionSpec`, `RoutingSpec`, `StepResult`, `ReplicationResult`, routing models (`RoutingCondition`, `RouteConnection`, `ConditionSetData`, `PublishedRouting`). |
| `replicator/param_mapper.py` | Fuzzy matching: normalizes `param_id` and field labels, matches by exact/substring/positional/unmatched layers. |
| `replicator/account_manager.py` | Account creation/lookup via organization-user-ms API. `ensure_account(name)` returns `(name, code_live)`. |
| `replicator/connection_creator.py` | Connection creation via organization-ms integrations API. `create_connection_api(code, spec)` returns `StepResult`. |
| `replicator/routing_creator.py` | Creates and publishes routing rules via direct routing-ms API calls. Maps source condition sets to target integration codes. |
| `replicator/routing_fetcher.py` | HTTP client for routing-ms API. Fetches published routing details per PM. Uses GET /by-payment-method/{pm} endpoint. |
| `replicator/orchestrator.py` | `Replicator` class: coordinates account setup → connections → routing. All via API, no browser. |
| `.env` | Runtime config. Not committed to git. |

## API Endpoints Used

All endpoints hit `https://internal-staging.y.uno` (no auth tokens required):

| Method | Endpoint | Key Header | Purpose |
|--------|----------|------------|---------|
| GET | `/organization-user-ms/v1/accounts/by-organization` | `x-organization-code` | List all accounts in the org |
| GET | `/organization-user-ms/v1/organizations/{org}/users` | `x-organization-code` | Get user codes for account creation |
| POST | `/organization-user-ms/v1/accounts` | `x-organization-code`, `x-user-code` | Create a new account |
| GET | `/organization-ms/v1/connections/` | `x-account-code` | List connections for an account |
| GET | `/organization-ms/v1/connections/{code}` | `x-account-code` | Get connection detail with credentials |
| POST | `/organization-ms/v1/organizations/{org}/integrations` | `x-account-code`, `x-organization-code` | Create connection with params |
| GET | `/routing-ms/v1/by-payment-method/{pm}` | `x-account-code`, `x-user-code` | Get versions for a PM (find published) |
| GET | `/routing-ms/v1/{version_code}` | `x-account-code`, `x-user-code` | Get full routing details for a version |
| POST | `/routing-ms/v1/` | `x-account-code`, `x-user-code` | Create draft routing version |
| PUT | `/routing-ms/v1/{version_code}` | `x-account-code`, `x-user-code` | Update version with condition sets |
| POST | `/routing-ms/v1/{version_code}/publish` | `x-account-code`, `x-user-code` | Publish a routing version |
| POST | `/routing-ms/v1/connections/providers` | `x-account-code`, `x-user-code` | Find provider integration codes (body: paymentMethod, country) |

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
- **`_error` sentinel pattern**: API errors are returned as `{"_error": "message"}` dicts mixed into result lists, allowing partial success.
- **Pure API replication**: All replication (account creation, connections, routing) uses direct HTTP calls to internal staging APIs. No browser automation, no Playwright, no Auth0 login needed.
- **Idempotent operations**: Account and connection creation check for existing resources by name before creating new ones.
- **Modular replicator**: Account/connection/routing in separate modules for testability and iterative development.
- **Individual failure tolerance**: Connection/routing failures don't stop the process; only account setup failure is fatal.
- **ThreadPoolExecutor(20 workers)**: "All Accounts" mode fetches connections concurrently.
- **Streamlit caching**: `@st.cache_data(ttl=300)` on all API calls.
- **Smart routing filtering**: Routing specs are built by querying routing-ms API at plan time (not at execution time). Only PMs with PUBLISHED routing that reference at least one of the selected connections get routing created. Raw condition_sets JSON is stored on each RoutingSpec for later API-based creation.
- **routing-ms API flow (read)**: GET /by-payment-method/{pm} -> find published version -> GET /{code} for full details. The `x-user-code: 00000000-...` header is a dummy value that works for all queries.
- **routing-ms API flow (write)**: POST /v1/ creates draft -> PUT /v1/{code} updates with remapped condition_sets -> POST /v1/{code}/publish. Source integration codes are mapped to target codes via POST /v1/connections/providers.

## Development Notes

- The app connects to **staging** internal APIs only. No production endpoints are used.
- The `ORGANIZATION_CODE` default (`6fd95f92-...`) is the Yuno QA/Integrations org in staging.
- Network access to `internal-staging.y.uno` is required (VPN or internal network).
- Python 3.10+ required (uses `list[dict]` type hints and `str | None`).

## When Modifying This Project

- If the API response shape changes, update `conn_id()`, `conn_provider()`, and `render_connection_detail()` in `helpers.py`.
- If new API endpoints are needed, add them to `yuno_client.py` following the existing pattern.
- Keep `config.py` minimal — only environment variables, no business logic.
- The `.env` file is gitignored. Use `.env.example` as template.
- `routing_creator.py` is API-based. If routing-ms endpoints change, update the API calls there.
- `param_mapper.py` handles fuzzy matching of API param names to form field labels. If new matching strategies are needed, add them as additional layers.
