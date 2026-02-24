"""Data models for the connection replication workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConnectionParam:
    param_id: str       # e.g. "SECRET_KEY"
    value: str          # e.g. "sk_test_..."
    country: str        # e.g. "GLOBAL"
    param_type: str     # e.g. "API"


@dataclass
class ConnectionSpec:
    connection_name: str
    provider_id: str
    country: str
    params: list[ConnectionParam]
    payment_methods: list[str]  # uppercase IDs only, e.g. ["CARD"]
    integration_code: str = ""  # account_integration_code from API


@dataclass
class RoutingSpec:
    payment_method: str     # e.g. "CARD"
    connection_name: str    # connection to route to (primary, for display)
    route_name: str         # display name for the route
    account_name: str | None = None  # target account for filter selection
    # Full source routing data for API-based creation
    source_routing: PublishedRouting | None = None
    source_condition_sets_raw: list[dict] | None = None  # raw JSON from API


# ---------------------------------------------------------------------------
# Routing data models (from routing-ms API)
# ---------------------------------------------------------------------------

@dataclass
class RoutingCondition:
    """A single condition within a condition set."""
    condition_type: str     # PARENT_PAYMENT_METHOD_TYPE, COUNTRY, METADATA, EMPTY_CONDITION
    values: list[str]       # e.g. ["GOOGLE_PAY"], ["BR"], ["true"]
    conditional: str        # EQUAL, NOT_EQUAL, ONE_OF, etc.
    metadata_key: str | None = None  # e.g. "3ds", "network_token", "flow"

    @property
    def display_label(self) -> str:
        """Human-readable label for this condition."""
        if self.condition_type == "EMPTY_CONDITION":
            return "All other payments"
        if self.condition_type == "METADATA" and self.metadata_key:
            return f"metadata.{self.metadata_key} {self.conditional.lower()} {', '.join(self.values)}"
        if self.condition_type == "COUNTRY":
            return f"Country {self.conditional.lower()} {', '.join(self.values)}"
        if self.condition_type == "PARENT_PAYMENT_METHOD_TYPE":
            return f"Parent PM {self.conditional.lower()} {', '.join(self.values)}"
        return f"{self.condition_type} {self.conditional.lower()} {', '.join(self.values)}"


@dataclass
class RouteConnection:
    """A connection (provider) assigned to a condition set route."""
    integration_code: str
    provider_id: str        # e.g. "ADYEN"
    provider_name: str      # e.g. "Adyen"
    network_token_on: bool = False


@dataclass
class ConditionSetData:
    """A condition set in the routing workflow (one node in the canvas)."""
    sort_number: int
    editable: bool
    conditions: list[RoutingCondition]
    routes: list[RouteConnection]
    is_catch_all: bool = False  # True when condition_type is EMPTY_CONDITION

    @property
    def display_label(self) -> str:
        if self.is_catch_all:
            return "All other payments"
        return " AND ".join(c.display_label for c in self.conditions)


@dataclass
class PublishedRouting:
    """Full published routing for a payment method."""
    payment_method: str
    version_name: str
    condition_sets: list[ConditionSetData] = field(default_factory=list)

    @property
    def connection_codes(self) -> set[str]:
        """All integration_codes referenced in this routing."""
        return {
            r.integration_code
            for cs in self.condition_sets
            for r in cs.routes
        }

    def uses_connection(self, integration_code: str) -> bool:
        return integration_code in self.connection_codes


@dataclass
class StepResult:
    success: bool
    step_name: str
    message: str
    screenshot_path: str | None = None


@dataclass
class ReplicationResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for s in self.steps if s.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for s in self.steps if not s.success)

    @property
    def all_succeeded(self) -> bool:
        return all(s.success for s in self.steps)
