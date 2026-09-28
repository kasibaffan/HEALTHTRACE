"""Milestone 3: baseline warm-up, global fallback, and SQLite persistence
round-trip (SPEC.md section 6.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import BaselineConfig
from app.detect.baseline import GLOBAL_HOUR, BaselineEngine
from app.store.db import Store

CONFIG = BaselineConfig(alpha=0.1, warmup_windows=12)


def test_not_ready_before_warmup():
    engine = BaselineEngine(CONFIG)
    for _ in range(11):
        engine.update("claims", 9, "error_rate", 0.02)
    assert engine.get("claims", 9, "error_rate") is None


def test_ready_after_warmup_windows():
    engine = BaselineEngine(CONFIG)
    for _ in range(12):
        engine.update("claims", 9, "error_rate", 0.02)
    stats = engine.get("claims", 9, "error_rate")
    assert stats is not None
    assert stats.count == 12
    assert stats.mean == pytest.approx(0.02, abs=1e-9)
    assert stats.is_global_fallback is False


def test_falls_back_to_global_when_hour_bucket_not_ready():
    engine = BaselineEngine(CONFIG)
    # Warm the global bucket via many different hours, none individually ready.
    for hour in range(12):
        engine.update("claims", hour, "error_rate", 0.02)
    # hour 9 itself only saw one update -> not ready on its own.
    assert engine.get("claims", 9, "error_rate").is_global_fallback is True

    stats = engine.get("claims", 9, "error_rate")
    assert stats is not None
    assert stats.mean == pytest.approx(0.02, abs=1e-9)


def test_hour_buckets_and_services_are_independent():
    engine = BaselineEngine(CONFIG)
    for _ in range(12):
        engine.update("claims", 9, "error_rate", 0.02)
        engine.update("claims", 14, "error_rate", 0.20)
        engine.update("prior_auth", 9, "error_rate", 0.01)

    assert engine.get("claims", 9, "error_rate").mean == pytest.approx(0.02, abs=1e-9)
    assert engine.get("claims", 14, "error_rate").mean == pytest.approx(0.20, abs=1e-9)
    assert engine.get("prior_auth", 9, "error_rate").mean == pytest.approx(0.01, abs=1e-9)


def test_ewma_tracks_a_shift_gradually():
    engine = BaselineEngine(CONFIG)
    for _ in range(12):
        engine.update("claims", 9, "error_rate", 0.02)
    mean_before = engine.get("claims", 9, "error_rate").mean

    engine.update("claims", 9, "error_rate", 0.02)  # one more normal sample
    mean_after = engine.get("claims", 9, "error_rate").mean
    assert mean_after == pytest.approx(mean_before, abs=1e-9)

    engine.update("claims", 9, "error_rate", 0.5)  # one big jump
    mean_after_jump = engine.get("claims", 9, "error_rate").mean
    assert mean_before < mean_after_jump < 0.5  # moved, but not all the way


async def test_save_and_load_roundtrip(tmp_path: Path):
    engine = BaselineEngine(CONFIG)
    for _ in range(15):
        engine.update("claims", 9, "error_rate", 0.02)
        engine.update("pharmacy", 3, "p95_latency_ms", 180.0)

    store = Store(tmp_path / "medguard.db")
    await store.connect()
    try:
        await engine.save(store)

        reloaded = BaselineEngine(CONFIG)
        await reloaded.load(store)

        original = engine.get("claims", 9, "error_rate")
        restored = reloaded.get("claims", 9, "error_rate")
        assert restored is not None
        assert restored.mean == pytest.approx(original.mean)
        assert restored.count == original.count

        original_lat = engine.get("pharmacy", 3, "p95_latency_ms")
        restored_lat = reloaded.get("pharmacy", 3, "p95_latency_ms")
        assert restored_lat.mean == pytest.approx(original_lat.mean)

        # GLOBAL_HOUR fallback rows persist too: hour 4 was never updated
        # directly, so both engines fall back to the (persisted) global bucket.
        original_fallback = engine.get("claims", 4, "error_rate")
        restored_fallback = reloaded.get("claims", 4, "error_rate")
        assert original_fallback is not None and original_fallback.is_global_fallback is True
        assert restored_fallback is not None and restored_fallback.is_global_fallback is True
        assert restored_fallback.mean == pytest.approx(original_fallback.mean)
    finally:
        await store.close()
