"""The ONE list of agents, with the stub/real switch per agent."""

from app.agents.companies_house.agent import CompaniesHouseAgent
from app.agents.companies_house.stub import CompaniesHouseStub
from app.agents.contract_checker.agent import ContractCheckerAgent
from app.agents.contract_checker.stub import ContractCheckerStub
from app.agents.emotion_classifier.agent import EmotionClassifierAgent
from app.agents.emotion_classifier.stub import EmotionClassifierStub
from app.agents.message_checker.agent import MessageCheckerAgent
from app.agents.message_checker.stub import MessageCheckerStub
from app.agents.video_analysis.agent import VideoAnalysisAgent
from app.agents.video_analysis.stub import VideoAnalysisStub
from app.core.agent import BaseAgent
from app.core.settings import Settings

AGENT_PAIRS: list[tuple[type[BaseAgent], type[BaseAgent]]] = [
    (CompaniesHouseAgent, CompaniesHouseStub),
    (MessageCheckerAgent, MessageCheckerStub),
    (ContractCheckerAgent, ContractCheckerStub),
    (EmotionClassifierAgent, EmotionClassifierStub),
    (VideoAnalysisAgent, VideoAnalysisStub),
]


def build_agents(settings: Settings) -> list[BaseAgent]:
    """One instance per agent: the real class when `AGENT_MODE_<NAME>=real`, else its stub."""
    return [
        real() if settings.agent_mode(real.name) == "real" else stub() for real, stub in AGENT_PAIRS
    ]
