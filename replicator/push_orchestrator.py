"""Push orchestrator: execute a PushPlan to sync source -> target account."""

from __future__ import annotations

import logging
from typing import Callable

from helpers import fetch_connections, conn_id
from replicator.models import (
    ReplicationResult,
    RoutingSpec,
    StepResult,
)
from replicator.diff_engine import PushPlan
from replicator.connection_creator import create_connection_api
from replicator.routing_creator import (
    build_target_condition_sets,
    create_routing_draft,
    find_target_integration_code,
    publish_routing_version,
    update_routing_version,
)

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]


class PushOrchestrator:
    """Execute a push plan: create missing connections and update routing.

    Unlike the Replicator (Feature 2), this does NOT create accounts — both
    source and target already exist. It operates on pre-computed diffs.
    """

    def __init__(
        self,
        plan: PushPlan,
        source_account_code: str,
        target_account_code: str,
        target_org_code: str,
        on_progress: ProgressCallback | None = None,
    ):
        self.plan = plan
        self.source_account_code = source_account_code
        self.target_account_code = target_account_code
        self.target_org_code = target_org_code
        self.on_progress = on_progress or (lambda msg, pct: None)

    def execute(self) -> ReplicationResult:
        result = ReplicationResult()

        conn_creates = self.plan.connections_to_create
        routing_changes = self.plan.routings_to_create_or_update
        total_steps = len(conn_creates) + len(routing_changes) + 1  # +1 for mapping step
        current_step = 0

        # Phase 1: Create missing connections
        for i, diff in enumerate(conn_creates):
            self.on_progress(
                f"Creating connection {i + 1}/{len(conn_creates)}: {diff.connection_name}",
                current_step / total_steps,
            )
            step = create_connection_api(
                self.target_org_code, self.target_account_code, diff.source_spec,
            )
            result.steps.append(step)
            current_step += 1

        # Phase 2: Build integration code map (source -> target)
        self.on_progress("Building integration code map...", current_step / total_steps)
        integration_code_map = self._build_integration_map()
        result.steps.append(StepResult(
            success=bool(integration_code_map),
            step_name="Build integration code map",
            message=f"Mapped {len(integration_code_map)} integration code(s).",
        ))
        current_step += 1

        if not integration_code_map and routing_changes:
            self.on_progress("No integration codes mapped. Skipping routing.", 1.0)
            for diff in routing_changes:
                result.steps.append(StepResult(
                    success=False,
                    step_name=f"Routing: {diff.payment_method}",
                    message="Skipped — no integration code map available.",
                ))
            return result

        # Phase 3: Create/Update routing
        for i, diff in enumerate(routing_changes):
            self.on_progress(
                f"{'Creating' if diff.status == 'CREATE' else 'Updating'} routing "
                f"{i + 1}/{len(routing_changes)}: {diff.payment_method}",
                current_step / total_steps,
            )
            step = self._push_routing(diff.payment_method, diff.source_condition_sets_raw, integration_code_map)
            result.steps.append(step)
            current_step += 1

        self.on_progress("Push complete.", 1.0)
        return result

    def _build_integration_map(self) -> dict[str, str]:
        """Map ALL source integration codes to their target equivalents.

        For existing connections: match by name between source and target lists.
        For newly created connections: create_connection_api updates spec.integration_code.
        """
        # Fetch current connections for both accounts
        source_conns = fetch_connections(self.source_account_code)
        target_conns = fetch_connections(self.target_account_code)

        # Build name -> integration_code lookups
        source_by_name: dict[str, str] = {}  # upper_name -> integration_code
        for c in source_conns:
            name = (c.get("name") or "").upper()
            code = conn_id(c)
            if name and code:
                source_by_name[name] = code

        target_by_name: dict[str, str] = {}  # upper_name -> integration_code
        for c in target_conns:
            name = (c.get("name") or "").upper()
            code = conn_id(c)
            if name and code:
                target_by_name[name] = code

        # Map source_code -> target_code via shared name
        code_map: dict[str, str] = {}
        for name, source_code in source_by_name.items():
            target_code = target_by_name.get(name)
            if target_code:
                code_map[source_code] = target_code

        log.info("Integration code map: %d entries", len(code_map))
        return code_map

    def _push_routing(
        self,
        payment_method: str,
        source_condition_sets_raw: list[dict] | None,
        integration_code_map: dict[str, str],
    ) -> StepResult:
        """Create/update routing for a single payment method."""
        step_name = f"Routing: {payment_method}"

        if not source_condition_sets_raw:
            return StepResult(
                success=False, step_name=step_name,
                message="No source condition sets available.",
            )

        try:
            # Build target condition sets with remapped integration codes
            target_condition_sets = build_target_condition_sets(
                source_condition_sets_raw, integration_code_map,
            )
            if not target_condition_sets:
                return StepResult(
                    success=False, step_name=step_name,
                    message="No valid condition sets after mapping.",
                )

            # Create draft (works even if published routing already exists)
            draft_code = create_routing_draft(
                self.target_account_code, payment_method,
                org_code=self.target_org_code,
            )
            if not draft_code:
                return StepResult(
                    success=False, step_name=step_name,
                    message="Failed to create routing draft.",
                )

            # Update with condition sets
            update_routing_version(
                self.target_account_code, draft_code, target_condition_sets,
                org_code=self.target_org_code,
            )

            # Publish (replaces any existing published version)
            if not publish_routing_version(
                self.target_account_code, draft_code,
                org_code=self.target_org_code,
            ):
                return StepResult(
                    success=False, step_name=step_name,
                    message=f"Draft {draft_code} created but failed to publish.",
                )

            n_sets = len(target_condition_sets)
            return StepResult(
                success=True, step_name=step_name,
                message=f"Published with {n_sets} condition set(s).",
            )

        except Exception as e:
            return StepResult(
                success=False, step_name=step_name,
                message=f"Error: {e}",
            )
