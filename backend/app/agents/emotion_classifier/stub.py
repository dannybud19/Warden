"""Stub for emotion_classifier: replays fixtures/reports/emotion_classifier.json."""

from app.agents.emotion_classifier.agent import EmotionClassifierAgent
from app.core.stub import FixtureStub


class EmotionClassifierStub(FixtureStub):
    name = "emotion_classifier"
    requires = EmotionClassifierAgent.requires
