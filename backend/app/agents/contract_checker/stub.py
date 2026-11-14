"""Stub for contract_checker: replays fixtures/reports/contract_checker.json."""

from app.agents.contract_checker.agent import ContractCheckerAgent
from app.core.stub import FixtureStub


class ContractCheckerStub(FixtureStub):
    name = "contract_checker"
    requires = ContractCheckerAgent.requires
