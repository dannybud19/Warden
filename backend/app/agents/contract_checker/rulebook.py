"""Load the small reviewed source collection; no live legal search during analysis."""

import json
from datetime import date
from pathlib import Path

from pydantic import Field

from app.agents.contract_checker.models import LegalSource, RuleId, StrictModel


class LegalRule(StrictModel):
    sources: list[str] = Field(default_factory=list)
    effective_from: date | None
    basis: str


class Rulebook(StrictModel):
    version: str
    verified_on: date
    sources: dict[str, LegalSource]
    rules: dict[RuleId, LegalRule]

    def references(self, rule: RuleId) -> list[LegalSource]:
        """Resolve only source URLs maintained in the reviewed collection."""
        return [self.sources[key] for key in self.rules[rule].sources]


def load_rulebook() -> Rulebook:
    """Read the package's immutable rule definitions."""
    path = Path(__file__).with_name("legal_rules.json")
    return Rulebook.model_validate(json.loads(path.read_text(encoding="utf-8")))
