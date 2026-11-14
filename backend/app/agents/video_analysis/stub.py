"""Stub for video_analysis: replays fixtures/reports/video_analysis.json."""

from app.agents.video_analysis.agent import VideoAnalysisAgent
from app.core.stub import FixtureStub


class VideoAnalysisStub(FixtureStub):
    name = "video_analysis"
    requires = VideoAnalysisAgent.requires
