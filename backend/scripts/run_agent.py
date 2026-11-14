"""Run one agent on one case: `python -m scripts.run_agent <agent> <case.json> [--live]`.

Runs the REAL agent class. Without `--live` it uses FakeLLM/FakeSearch (offline); with `--live`
it uses the clients configured in `.env` (real LLM and web search).
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.contracts import Case
from app.core.agent import AgentContext
from app.core.factory import build_context
from app.core.llm import FakeLLM
from app.core.logging import get_logger
from app.core.search import FakeSearch
from app.core.settings import get_settings
from app.orchestrator.registry import AGENT_PAIRS


async def main(agent_name: str, case_path: Path, live: bool) -> int:
    agents = {real.name: real for real, _ in AGENT_PAIRS}
    if agent_name not in agents:
        sys.stderr.write(f"unknown agent {agent_name!r}; choose from {sorted(agents)}\n")
        return 2
    case = Case.model_validate_json(await asyncio.to_thread(case_path.read_text))
    settings = get_settings()
    ctx = build_context(settings)
    if not live:
        ctx = AgentContext(
            llm=FakeLLM(),
            search=FakeSearch(),
            http=ctx.http,
            settings=settings,
            log=get_logger("run_agent"),
        )
    try:
        report = await agents[agent_name]().run(case, ctx)
    finally:
        await ctx.http.aclose()
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent")
    parser.add_argument("case", type=Path)
    parser.add_argument("--live", action="store_true", help="use real LLM and web search")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.agent, args.case, args.live)))
