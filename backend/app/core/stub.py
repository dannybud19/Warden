"""Base class for every agent's stub: replays a fixture report."""

from app.contracts import AgentReport, Case
from app.core.agent import AgentContext, BaseAgent, hash_slice


class FixtureStub(BaseAgent):
    """Returns fixtures/reports/<name>.json, with this run's input hash."""

    async def run(self, case: Case, ctx: AgentContext) -> AgentReport:
        path = ctx.settings.fixtures_dir / "reports" / f"{self.name}.json"
        report = AgentReport.model_validate_json(path.read_text())
        return report.model_copy(
            update={
                "agent": self.name,
                "version": f"{self.version}-stub",
                "input_hash": hash_slice(self.input_slice(case)),
            }
        )
