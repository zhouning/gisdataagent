"""DerivationStrategy ABC + result dataclasses."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DerivationLink:
    source_kind: str        # 'data_element'
    source_id: str
    target_kind: str        # 'semantic_hint'
    target_table: str       # 'agent_semantic_hints'
    target_id: str          # cast to text (downstream PK may be int)
    notes: dict | None = None


@dataclass
class DerivationResult:
    strategy: str
    new_links: list[DerivationLink] = field(default_factory=list)
    staled_links: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


class DerivationStrategy(ABC):
    """Each strategy: read std_* artefacts, upsert downstream rows, manage
    std_derived_link active/stale."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, *, version_id: str, by_user: str) -> DerivationResult:
        ...
