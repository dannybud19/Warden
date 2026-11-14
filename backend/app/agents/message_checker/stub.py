"""Stub for message_checker: replays fixtures/reports/message_checker.json."""

from app.agents.message_checker.agent import MessageCheckerAgent
from app.core.stub import FixtureStub


class MessageCheckerStub(FixtureStub):
    name = "message_checker"
    requires = MessageCheckerAgent.requires
