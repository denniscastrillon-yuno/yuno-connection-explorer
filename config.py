import os
from dotenv import load_dotenv

load_dotenv()

INTERNAL_API_BASE = os.getenv("INTERNAL_API", "https://internal-staging.y.uno")
ORGANIZATION_CODE = os.getenv(
    "ORGANIZATION_CODE", "6fd95f92-f9b3-4f62-a496-80c6c08e00bb"
)
