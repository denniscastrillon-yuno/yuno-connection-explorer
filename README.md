# Yuno Connection Explorer

A multipage Streamlit app for inspecting and replicating payment provider connections across Yuno organizations in staging.

Built for QA engineers and integration developers who need to quickly inspect provider configurations and replicate them to their own orgs for testing.

## Features

### Connection Explorer
- **Dynamic account discovery** — no hardcoded mappings; accounts are fetched from the API at startup
- **170+ provider accounts** discovered automatically from the organization
- **Search & filter** — find accounts instantly by typing in the sidebar
- **Single account view** — see all connections for a specific provider with metrics
- **All accounts view** — concurrent fetch across all accounts with progress bar (20 workers)
- **Connection details** — expandable cards showing credentials, API keys, payment methods, and raw JSON
- **5-minute cache** — fast navigation with a manual refresh button

### Replicate Connections
- **Source selection** — pick an account and select specific connections via checkboxes
- **Plan review** — see connection params (truncated) and routing rules before execution
- **Browser automation** — Playwright-powered creation of connections and routing rules in the Dashboard
- **Auth0 login** — automated login with MFA support (manual completion in headed mode)
- **Fuzzy param matching** — automatic mapping of API credentials to Dashboard form fields
- **Progress tracking** — real-time progress bar and step-by-step log
- **Failure tolerance** — individual connection failures don't stop the process
- **Debug screenshots** — automatic screenshots on failure for troubleshooting

## Quick Start

```bash
# Clone
git clone https://github.com/denniscastrillon-yuno/yuno-connection-explorer.git
cd yuno-connection-explorer

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium    # Download browser (~150MB, one time)

# Configure
cp .env.example .env
# Edit .env if you need a different organization code

# Run
streamlit run app.py
```

The app will open at `http://localhost:8501`.

> **Note:** Network access to `internal-staging.y.uno` is required (VPN or internal network).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ORGANIZATION_CODE` | `6fd95f92-f9b3-4f62-a496-80c6c08e00bb` | Yuno organization UUID (QA/Integrations staging org) |
| `INTERNAL_API` | `https://internal-staging.y.uno` | Base URL for internal APIs |
| `DASHBOARD_URL` | `https://dashboard.staging.y.uno` | Yuno Dashboard URL for browser automation |

## Project Structure

```
yuno-connection-explorer/
├── app.py                           # Landing page
├── helpers.py                       # Shared helpers (fetchers, rendering)
├── yuno_client.py                   # HTTP client for Yuno internal APIs
├── config.py                        # Environment variable loading
├── pages/
│   ├── 1_Connection_Explorer.py     # Browse connections across accounts
│   └── 2_Replicate_Connections.py   # Replicate connections & routing
├── replicator/
│   ├── models.py                    # Data models (ConnectionSpec, RoutingSpec, etc.)
│   ├── param_mapper.py              # Fuzzy matching of params to form fields
│   ├── dashboard_auth.py            # Auth0 login automation
│   ├── connection_creator.py        # Create connections via dashboard wizard
│   ├── routing_creator.py           # Create & publish routing rules
│   └── orchestrator.py              # Workflow coordinator
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment template
├── .gitignore
├── CLAUDE.md                        # AI assistant context
└── README.md
```

## API Endpoints

All requests go to `https://internal-staging.y.uno` with no auth tokens required:

| Endpoint | Header | Returns |
|----------|--------|---------|
| `GET /organization-user-ms/v1/accounts/by-organization` | `x-organization-code` | All accounts in the org |
| `GET /organization-ms/v1/connections/` | `x-account-code` | Connections for an account |
| `GET /organization-ms/v1/connections/{code}` | `x-account-code` | Connection detail with credentials |

## Requirements

- Python 3.10+
- Network access to Yuno internal staging
- Chromium browser (installed via `playwright install chromium`)
- Dependencies: `streamlit`, `requests`, `python-dotenv`, `pandas`, `playwright`

## License

Internal tool — Yuno Payments.
