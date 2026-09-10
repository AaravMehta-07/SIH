"""Identity resolution and scope management (Build Spec Appendix G).

Identity keys enable tracking but are never numeric model features (G.1).
DHCP lease turnover closes one address binding and opens another; NAT without
internal mapping creates ambiguous external identity (ID01).
"""

from .resolver import (
    AddressResolver,
    IdentityAmbiguity,
    ScopeManifest,
    ScopePartition,
    materialize_scope,
)
from .scope import cohort_assignment

__all__ = [
    "AddressResolver",
    "IdentityAmbiguity",
    "ScopeManifest",
    "ScopePartition",
    "materialize_scope",
    "cohort_assignment",
]
