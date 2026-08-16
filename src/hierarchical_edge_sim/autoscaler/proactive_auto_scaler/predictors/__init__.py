"""Predictor backends for proactive_auto_scaler."""

from .base import HorizonRpsPredictor, OneStepRpsPredictor
from .persistence import PersistencePredictor

__all__ = ["HorizonRpsPredictor", "OneStepRpsPredictor", "PersistencePredictor"]
