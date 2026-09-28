"""Attach service criticality and priority weight to app events (SPEC.md 6.2).

Audit events aren't enriched here — they go straight to the access detector
(Milestone 4) unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import AppConfig
from app.models import AppEvent


class EnrichedAppEvent(BaseModel):
    event: AppEvent
    criticality: float
    priority_weight: int


class Enricher:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def enrich(self, event: AppEvent) -> EnrichedAppEvent:
        criticality = self._config.services[event.service].criticality
        priority_weight = self._config.priority_weight[event.priority]
        return EnrichedAppEvent(event=event, criticality=criticality, priority_weight=priority_weight)
