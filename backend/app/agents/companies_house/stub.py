"""Stub for companies_house: replays fixtures/reports/companies_house.json."""

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.core.stub import FixtureStub


class CompaniesHouseStub(FixtureStub):
    name = "companies_house"
    requires = CompaniesHouseAgent.requires
