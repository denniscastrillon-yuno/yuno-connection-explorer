# Yuno Connection Explorer

A Streamlit dashboard that dynamically discovers and displays all payment provider connections configured in a Yuno organization via internal staging APIs.

Built for QA engineers and integration developers who need to quickly inspect provider configurations, credentials, and parameters without navigating the Yuno Dashboard.

## Features

- **Dynamic account discovery** — no hardcoded mappings; accounts are fetched from the API at startup
- **170+ provider accounts** discovered automatically from the organization
- **Search & filter** — find accounts instantly by typing in the sidebar
- **Single account view** — see all connections for a specific provider with metrics
- **All accounts view** — concurrent fetch across all accounts with progress bar (20 workers)
- **Connection details** — expandable cards showing credentials, API keys, payment methods, and raw JSON
- **5-minute cache** — fast navigation with a manual refresh button

## Quick Start

```bash
# Clone
git clone https://github.com/denniscastrillon-yuno/yuno-connection-explorer.git
cd yuno-connection-explorer

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

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

## Project Structure

```
yuno-connection-explorer/
├── app.py             # Streamlit UI (sidebar, tables, detail cards)
├── yuno_client.py     # HTTP client for Yuno internal APIs
├── config.py          # Environment variable loading
├── requirements.txt   # Python dependencies
├── .env.example       # Environment template
├── .gitignore
├── CLAUDE.md          # AI assistant context for Claude Code
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
- Dependencies: `streamlit`, `requests`, `python-dotenv`, `pandas`

## License

Internal tool — Yuno Payments.
