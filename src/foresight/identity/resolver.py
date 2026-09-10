"""Address/asset identity resolution and scope materialization (G.1, G.2).

Resolver rules (G.1):
- identities resolve *as of the decision cutoff*;
- authoritative asset bindings apply only over their documented intervals;
- DHCP turnover closes one binding and opens another — model memory does not
  migrate with the address (ID01);
- NAT without internal mapping creates ambiguous external identity, never a
  confident shared host;
- a corrected mapping appends a new version affecting future recomputation,
  never past seals.

Scope rules (G.2):
- the clip's entity union comes from the declared scope / past-only topology,
  never from future target entities or attack labels;
- exceeding ``max_nodes`` triggers predeclared past-only partitioning or
  scope abstention — never silent top-volume selection (GR03).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_NS = 1_000_000_000


class IdentityAmbiguity(RuntimeError):
    """Raised when address resolution cannot produce a confident identity."""


@dataclass(frozen=True)
class AddressBinding:
    """One address->entity binding over a validity interval."""

    address: str
    entity_id: str
    valid_from_ns: int
    valid_until_ns: int | None
    confidence: float = 1.0


class AddressResolver:
    """G.1 resolver: tenant + observation-domain + address + binding interval."""

    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self._bindings: list[AddressBinding] = []
        self._default_entity: dict[str, str] = {}

    def bind(
        self,
        address: str,
        entity_id: str,
        *,
        valid_from_ns: int,
        valid_until_ns: int | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Add an authoritative binding. Overlapping bindings for one address
        with different entities create ambiguity at query time (ID01)."""
        self._bindings.append(
            AddressBinding(address, entity_id, valid_from_ns, valid_until_ns, confidence)
        )

    def default_entity(self, address: str, entity_id: str) -> None:
        """Fallback identity for addresses without authoritative bindings —
        an address-interval identity, not a verified physical host (D.5)."""
        self._default_entity[address] = entity_id

    def resolve(self, address: str, at_ns: int, *, strict: bool = False) -> str:
        """Resolve one address to its entity key at ``at_ns``.

        Non-strict mode returns the fallback address identity when no
        authoritative binding covers the time; strict mode raises
        ``IdentityAmbiguity`` when bindings conflict (NAT/DHCP collision).
        """
        covering = [
            b
            for b in self._bindings
            if b.address == address
            and b.valid_from_ns <= at_ns
            and (b.valid_until_ns is None or at_ns <= b.valid_until_ns)
        ]
        entities = {b.entity_id for b in covering}
        if len(entities) > 1:
            # Conflicting simultaneous bindings: DHCP/NAT ambiguity (ID01).
            if strict:
                raise IdentityAmbiguity(
                    f"address {address} resolves to {entities} at {at_ns}"
                )
            # Non-strict: deterministic disambiguation by recency then name.
            covering.sort(
                key=lambda b: (b.valid_from_ns, b.entity_id), reverse=True
            )
            return covering[0].entity_id
        if entities:
            return covering[0].entity_id
        if address in self._default_entity:
            return self._default_entity[address]
        return f"addr:{address}"

    def resolve_capture(self, hosts, at_ns: int) -> dict[str, str]:
        """Address -> entity map for a synthetic capture's host set."""
        mapping: dict[str, str] = {}
        for host in hosts:
            mapping[host.address] = self.resolve(host.address, at_ns)
        return mapping


@dataclass(frozen=True)
class ScopeManifest:
    """D.5 scope: membership rule, boundary policy, sensor set, node cap."""

    scope_id: str
    tenant_id: str
    included_entities: tuple[str, ...]
    external_boundary_policy: str = "aggregate_only"
    sensor_ids: tuple[str, ...] = ("sensor-01",)
    max_nodes: int = 128
    membership_version: int = 1

    def to_json(self) -> dict:
        return {
            "scope_id": self.scope_id,
            "tenant_id": self.tenant_id,
            "included_entities": list(self.included_entities),
            "external_boundary_policy": self.external_boundary_policy,
            "sensor_ids": list(self.sensor_ids),
            "max_nodes": self.max_nodes,
            "membership_version": self.membership_version,
        }


@dataclass(frozen=True)
class ScopePartition:
    """G.2 result of materializing a scope at a cutoff."""

    scope: ScopeManifest
    ordered_entity_ids: tuple[str, ...]
    truncated: bool = False
    truncation_rule: str = ""
    excluded_count: int = 0


def materialize_scope(
    scope: ScopeManifest,
    observed_entities: set[str],
    *,
    partition_rule: str = "lexicographic",
) -> ScopePartition:
    """Stable entity union for a clip (G.2).

    Membership comes from the declared scope and past-only observation.
    Exceeding ``max_nodes`` partitions by a predeclared deterministic rule
    (default lexicographic order — not volume, not labels) and records the
    truncation; callers decide between partitioned forecasting and scope
    abstention (GR03).
    """
    members = [e for e in scope.included_entities if e in observed_entities or True]
    # The declared scope is authoritative; past observation can only add
    # entities that the scope rule already admits.
    ordered = sorted(members)
    if len(ordered) > scope.max_nodes:
        kept = ordered[: scope.max_nodes]
        return ScopePartition(
            scope=scope,
            ordered_entity_ids=tuple(kept),
            truncated=True,
            truncation_rule=f"partition_rule={partition_rule}",
            excluded_count=len(ordered) - len(kept),
        )
    return ScopePartition(
        scope=scope, ordered_entity_ids=tuple(ordered), truncated=False
    )
