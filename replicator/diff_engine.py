"""Diff engine: compute differences between two accounts (connections + routing)."""

from __future__ import annotations

from dataclasses import dataclass, field

from replicator.models import ConnectionSpec, PublishedRouting


# ---------------------------------------------------------------------------
# Diff models
# ---------------------------------------------------------------------------

@dataclass
class ConnectionDiff:
    connection_name: str
    provider_id: str
    status: str  # "CREATE" | "SKIP" | "WARN_EXTRA"
    source_spec: ConnectionSpec | None = None
    message: str = ""


@dataclass
class RoutingDiff:
    payment_method: str
    status: str  # "CREATE" | "UPDATE" | "SKIP" | "WARN_EXTRA"
    source_routing: PublishedRouting | None = None
    target_routing: PublishedRouting | None = None
    source_condition_sets_raw: list[dict] | None = None
    changes_summary: str = ""


@dataclass
class PushPlan:
    source_account_name: str
    target_account_name: str
    connection_diffs: list[ConnectionDiff] = field(default_factory=list)
    routing_diffs: list[RoutingDiff] = field(default_factory=list)

    @property
    def connections_to_create(self) -> list[ConnectionDiff]:
        return [d for d in self.connection_diffs if d.status == "CREATE"]

    @property
    def routings_to_create_or_update(self) -> list[RoutingDiff]:
        return [d for d in self.routing_diffs if d.status in ("CREATE", "UPDATE")]

    @property
    def has_changes(self) -> bool:
        return bool(self.connections_to_create or self.routings_to_create_or_update)


# ---------------------------------------------------------------------------
# Connection diff
# ---------------------------------------------------------------------------

def compute_connection_diff(
    source_specs: list[ConnectionSpec],
    target_connections: list[dict],
) -> list[ConnectionDiff]:
    """Compare source connection specs against target connections list.

    - Source has, target doesn't -> CREATE
    - Both have (by name, case-insensitive) -> SKIP
    - Target has, source doesn't -> WARN_EXTRA
    """
    source_names = {s.connection_name.upper(): s for s in source_specs}
    target_names = {
        (c.get("name") or "").upper(): c for c in target_connections
    }

    diffs: list[ConnectionDiff] = []

    # Check source connections against target
    for upper_name, spec in sorted(source_names.items()):
        if upper_name in target_names:
            diffs.append(ConnectionDiff(
                connection_name=spec.connection_name,
                provider_id=spec.provider_id,
                status="SKIP",
                source_spec=spec,
                message="Already exists in target.",
            ))
        else:
            diffs.append(ConnectionDiff(
                connection_name=spec.connection_name,
                provider_id=spec.provider_id,
                status="CREATE",
                source_spec=spec,
                message="Missing in target, will be created.",
            ))

    # Check for extra connections in target
    for upper_name, conn in sorted(target_names.items()):
        if upper_name not in source_names:
            provider = conn.get("provider", {})
            pid = provider.get("provider_id", "") if isinstance(provider, dict) else str(provider)
            diffs.append(ConnectionDiff(
                connection_name=conn.get("name", upper_name),
                provider_id=pid,
                status="WARN_EXTRA",
                message="Exists in target but not in source (will not be deleted).",
            ))

    return diffs


# ---------------------------------------------------------------------------
# Routing equivalence
# ---------------------------------------------------------------------------

def _routing_is_equivalent(source: PublishedRouting, target: PublishedRouting) -> bool:
    """Check if two routings have equivalent structure.

    Cannot compare integration_codes directly (they differ between accounts).
    Compares structure: number of condition sets, conditions, and providers (by provider_id).
    """
    if len(source.condition_sets) != len(target.condition_sets):
        return False

    # Compare by sort_number order
    src_sets = sorted(source.condition_sets, key=lambda cs: cs.sort_number)
    tgt_sets = sorted(target.condition_sets, key=lambda cs: cs.sort_number)

    for src_cs, tgt_cs in zip(src_sets, tgt_sets):
        # Compare conditions
        if len(src_cs.conditions) != len(tgt_cs.conditions):
            return False
        for src_c, tgt_c in zip(src_cs.conditions, tgt_cs.conditions):
            if src_c.condition_type != tgt_c.condition_type:
                return False
            if sorted(src_c.values) != sorted(tgt_c.values):
                return False
            if src_c.conditional != tgt_c.conditional:
                return False
            if src_c.metadata_key != tgt_c.metadata_key:
                return False

        # Compare routes by provider_id (not integration_code)
        src_providers = sorted(r.provider_id for r in src_cs.routes)
        tgt_providers = sorted(r.provider_id for r in tgt_cs.routes)
        if src_providers != tgt_providers:
            return False

    return True


def _describe_routing_changes(source: PublishedRouting, target: PublishedRouting) -> str:
    """Generate human-readable description of routing differences."""
    parts: list[str] = []

    if len(source.condition_sets) != len(target.condition_sets):
        parts.append(
            f"Condition sets: source has {len(source.condition_sets)}, "
            f"target has {len(target.condition_sets)}"
        )

    src_sets = sorted(source.condition_sets, key=lambda cs: cs.sort_number)
    tgt_sets = sorted(target.condition_sets, key=lambda cs: cs.sort_number)

    for i, (src_cs, tgt_cs) in enumerate(zip(src_sets, tgt_sets)):
        src_providers = sorted(r.provider_id for r in src_cs.routes)
        tgt_providers = sorted(r.provider_id for r in tgt_cs.routes)
        if src_providers != tgt_providers:
            parts.append(
                f"Set #{i + 1}: source routes to [{', '.join(src_providers)}], "
                f"target routes to [{', '.join(tgt_providers)}]"
            )

        if len(src_cs.conditions) != len(tgt_cs.conditions):
            parts.append(
                f"Set #{i + 1}: source has {len(src_cs.conditions)} condition(s), "
                f"target has {len(tgt_cs.conditions)}"
            )

    # Handle extra sets in source or target
    if len(src_sets) > len(tgt_sets):
        for i in range(len(tgt_sets), len(src_sets)):
            providers = [r.provider_id for r in src_sets[i].routes]
            parts.append(f"Set #{i + 1}: only in source, routes to [{', '.join(providers)}]")
    elif len(tgt_sets) > len(src_sets):
        for i in range(len(src_sets), len(tgt_sets)):
            providers = [r.provider_id for r in tgt_sets[i].routes]
            parts.append(f"Set #{i + 1}: only in target, routes to [{', '.join(providers)}]")

    return "; ".join(parts) if parts else "Structural differences detected"


# ---------------------------------------------------------------------------
# Routing diff
# ---------------------------------------------------------------------------

def compute_routing_diff(
    source_routings: dict[str, PublishedRouting],
    target_routings: dict[str, PublishedRouting],
    source_raw: dict[str, dict],
) -> list[RoutingDiff]:
    """Compare source routing against target routing by payment method.

    Args:
        source_routings: {pm: PublishedRouting} parsed from source account.
        target_routings: {pm: PublishedRouting} parsed from target account.
        source_raw: {pm: raw_routing_dict} from routing-ms for source (needed
            to carry condition_sets_raw for the push phase).

    Returns:
        List of RoutingDiff with status CREATE/UPDATE/SKIP/WARN_EXTRA.
    """
    all_pms = sorted(set(source_routings) | set(target_routings))
    diffs: list[RoutingDiff] = []

    for pm in all_pms:
        src = source_routings.get(pm)
        tgt = target_routings.get(pm)
        raw = source_raw.get(pm)

        if src and not tgt:
            diffs.append(RoutingDiff(
                payment_method=pm,
                status="CREATE",
                source_routing=src,
                source_condition_sets_raw=raw.get("condition_sets", []) if raw else None,
                changes_summary=f"New routing: {len(src.condition_sets)} condition set(s)",
            ))
        elif src and tgt:
            if _routing_is_equivalent(src, tgt):
                diffs.append(RoutingDiff(
                    payment_method=pm,
                    status="SKIP",
                    source_routing=src,
                    target_routing=tgt,
                    changes_summary="Already equivalent.",
                ))
            else:
                diffs.append(RoutingDiff(
                    payment_method=pm,
                    status="UPDATE",
                    source_routing=src,
                    target_routing=tgt,
                    source_condition_sets_raw=raw.get("condition_sets", []) if raw else None,
                    changes_summary=_describe_routing_changes(src, tgt),
                ))
        elif not src and tgt:
            diffs.append(RoutingDiff(
                payment_method=pm,
                status="WARN_EXTRA",
                target_routing=tgt,
                changes_summary="Exists in target but not in source (will not be deleted).",
            ))

    return diffs
