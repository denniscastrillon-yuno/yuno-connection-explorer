"""Orchestrator: coordinates the full replication workflow via API."""

from __future__ import annotations

from typing import Callable

from replicator.models import (
    ConnectionSpec,
    ReplicationResult,
    RoutingSpec,
    StepResult,
)
from replicator.account_manager import ensure_account
from replicator.connection_creator import create_connection_api
from replicator.routing_creator import create_routing_rule_api


ProgressCallback = Callable[[str, float], None]  # (message, progress_0_to_1)


class Replicator:
    """Coordinates connection and routing replication via pure API calls.

    No Playwright, no browser, no login required.

    Args:
        connections: List of connection specs to create.
        routings: List of routing specs to create (already filtered).
        target_org_code: Organization code where replication happens.
        target_account_name: Name for the target account.
        on_progress: Callback for progress updates (message, fraction).
    """

    def __init__(
        self,
        connections: list[ConnectionSpec],
        routings: list[RoutingSpec],
        target_org_code: str,
        target_account_name: str = "Replication Target",
        on_progress: ProgressCallback | None = None,
    ):
        self.connections = connections
        self.routings = routings
        self.target_org_code = target_org_code
        self.target_account_name = target_account_name
        self.on_progress = on_progress or (lambda msg, pct: None)

    def execute(self) -> ReplicationResult:
        """Execute the full replication workflow.

        Returns:
            ReplicationResult with per-step outcomes.
        """
        result = ReplicationResult()

        total_steps = 1 + len(self.connections) + len(self.routings)
        current_step = 0

        # Step 1: Ensure target account exists (API)
        self.on_progress(
            f"Setting up target account: {self.target_account_name}...",
            current_step / total_steps,
        )
        account_result, account_code = self._do_account_setup()
        result.steps.append(account_result)
        current_step += 1

        if not account_result.success:
            self.on_progress("Account setup failed. Aborting.", 1.0)
            return result

        self.on_progress("Account ready.", current_step / total_steps)

        # Save source integration codes BEFORE creating connections
        # (create_connection_api overwrites spec.integration_code with the target code)
        source_integration_codes: dict[str, str] = {}  # source_code -> provider_id
        for spec in self.connections:
            if spec.integration_code:
                source_integration_codes[spec.integration_code] = spec.provider_id

        # Step 2: Create connections (API)
        for i, conn_spec in enumerate(self.connections):
            self.on_progress(
                f"Creating connection {i + 1}/{len(self.connections)}: {conn_spec.connection_name} (API)",
                current_step / total_steps,
            )
            step_result = create_connection_api(
                self.target_org_code, account_code, conn_spec,
            )
            result.steps.append(step_result)
            current_step += 1

        # Build source_integration_code -> target_integration_code map
        # After creation, spec.integration_code holds the TARGET code
        provider_to_target: dict[str, str] = {}
        for spec in self.connections:
            if spec.integration_code:
                provider_to_target[spec.provider_id] = spec.integration_code

        integration_code_map: dict[str, str] = {}
        for source_code, provider_id in source_integration_codes.items():
            target_code = provider_to_target.get(provider_id)
            if target_code:
                integration_code_map[source_code] = target_code

        # Step 3: Create routing rules (API)
        for i, routing_spec in enumerate(self.routings):
            routing_spec.account_name = self.target_account_name
            self.on_progress(
                f"Creating routing {i + 1}/{len(self.routings)}: {routing_spec.payment_method} (API)",
                current_step / total_steps,
            )
            step_result = create_routing_rule_api(
                self.target_org_code, account_code, routing_spec,
                known_integration_map=integration_code_map,
            )
            result.steps.append(step_result)
            current_step += 1

        self.on_progress("Replication complete.", 1.0)
        return result

    def _do_account_setup(self) -> tuple[StepResult, str]:
        """Create or find the target account via API.

        Returns (StepResult, account_code).
        """
        try:
            actual_name, account_code = ensure_account(
                self.target_org_code, self.target_account_name,
            )
            return StepResult(
                success=True,
                step_name="Account setup",
                message=f"Account '{actual_name}' is ready. Code: {account_code[:8]}...",
            ), account_code
        except Exception as e:
            return StepResult(
                success=False,
                step_name="Account setup",
                message=f"Failed to set up account: {e}",
            ), ""
