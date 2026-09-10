"""Versioned event ontology (Build Spec Section 11).

Targets are named events, not the word "malicious". Task 0 is explicitly an
observable proxy and MUST NOT be renamed compromise. The SIH five-tactic
projection: Reconnaissance, Initial Access, Lateral Movement, Command and
Control, Exfiltration — evidence tags, not a linear kill chain.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The five named targets (Section 11). ``task_index`` fixes tensor order.
@dataclass(frozen=True)
class TaskDefinition:
    task_index: int
    id: str
    label: str
    label_tier: str
    description: str


TASK_DEFINITIONS: tuple[TaskDefinition, ...] = (
    TaskDefinition(
        task_index=0,
        id="malicious-endpoint-contact",
        label="Malicious endpoint contact",
        label_tier="weak_proxy",
        description=(
            "First observed malicious endpoint contact. An observable proxy, "
            "not compromise (Section 11)."
        ),
    ),
    TaskDefinition(
        task_index=1,
        id="initial-access",
        label="Confirmed initial access",
        label_tier="confirmed",
        description="First confirmed initial access on the entity.",
    ),
    TaskDefinition(
        task_index=2,
        id="lateral-movement",
        label="Confirmed lateral movement",
        label_tier="confirmed",
        description="First confirmed lateral movement involving the entity.",
    ),
    TaskDefinition(
        task_index=3,
        id="command-and-control",
        label="Confirmed C2",
        label_tier="confirmed",
        description="First confirmed command-and-control channel.",
    ),
    TaskDefinition(
        task_index=4,
        id="exfiltration",
        label="Verified exfiltration",
        label_tier="confirmed",
        description="First verified exfiltration event.",
    ),
)

TASK_IDS: tuple[str, ...] = tuple(t.id for t in TASK_DEFINITIONS)
TASK_LABEL_TIERS: tuple[str, ...] = tuple(t.label_tier for t in TASK_DEFINITIONS)


def task_label(task_index: int) -> str:
    return TASK_DEFINITIONS[task_index].label


#: SIH five-tactic projection (Section 11); order fixes the stage-tag axis.
SIH_TACTICS: tuple[str, ...] = (
    "reconnaissance",
    "initial-access",
    "lateral-movement",
    "command-and-control",
    "exfiltration",
)

#: Mapping from task index to its matching tactic axis position.
TASK_TO_TACTIC = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}
