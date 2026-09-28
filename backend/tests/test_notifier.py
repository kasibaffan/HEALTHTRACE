"""Milestone 5: AWS notifier modes, retry/backoff, and non-blocking queueing
(SPEC.md section 6.9)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.models import Alert, Incident
from app.notify.aws import AwsNotifier

T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def make_alert(severity="HIGH") -> Alert:
    return Alert(ts=T0, kind="error_rate", service="prior_auth", severity=severity, score=0.6, explanation="x")


def make_incident(severity="CRITICAL") -> Incident:
    return Incident(
        id=1, fingerprint="error_rate:prior_auth", kind="error_rate", service="prior_auth",
        state="OPEN", peak_severity=severity, alert_count=1, opened_at=T0,
    )


async def test_off_mode_does_nothing():
    notifier = AwsNotifier("off")
    await notifier.start()
    notifier.notify_alert(make_alert())
    notifier.notify_incident(make_incident(), "explanation")
    assert notifier.queue_depth == 0
    await notifier.stop()


async def test_mock_mode_writes_cloudwatch_and_sns(tmp_path: Path, capsys):
    mock_log = tmp_path / "aws_mock.log"
    notifier = AwsNotifier("mock", sns_topic_arn="arn:aws:sns:x", mock_log_path=mock_log)
    await notifier.start()

    notifier.notify_alert(make_alert(severity="LOW"))
    notifier.notify_incident(make_incident(severity="CRITICAL"), "prior_auth error rate 38%")
    await notifier.stop()

    lines = mock_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["aws_service"] == "cloudwatch_logs"
    assert records[1]["aws_service"] == "sns"
    assert records[1]["subject"] == "[MedGuard CRITICAL] prior_auth: error rate spike"
    assert "Incident ID: 1" in records[1]["body"]

    captured = capsys.readouterr()
    assert "[aws:mock]" in captured.out


async def test_only_high_and_critical_incidents_reach_sns(tmp_path: Path):
    mock_log = tmp_path / "aws_mock.log"
    notifier = AwsNotifier("mock", mock_log_path=mock_log)
    await notifier.start()

    notifier.notify_alert(make_alert(severity="LOW"))  # every alert goes to CloudWatch...
    notifier.notify_incident(make_incident(severity="LOW"), "x")  # ...but LOW/MEDIUM incidents never reach SNS
    notifier.notify_incident(make_incident(severity="MEDIUM"), "x")
    await notifier.stop()

    records = [json.loads(line) for line in mock_log.read_text(encoding="utf-8").strip().splitlines()]
    assert len(records) == 1
    assert records[0]["aws_service"] == "cloudwatch_logs"


async def test_notify_alert_never_blocks_even_when_the_worker_is_slow(monkeypatch):
    notifier = AwsNotifier("mock", mock_log_path=None)

    async def slow_send(alert):
        await asyncio.sleep(0.3)

    monkeypatch.setattr(notifier, "_send_cloudwatch", slow_send)
    await notifier.start()

    start = time.monotonic()
    for _ in range(5):
        notifier.notify_alert(make_alert())
    elapsed = time.monotonic() - start

    assert elapsed < 0.05  # queuing 5 items must be near-instant regardless of the slow worker
    await notifier.stop()  # waits for the (slow) queue to drain before returning


async def test_retries_with_backoff_then_succeeds(monkeypatch):
    notifier = AwsNotifier("mock", base_backoff=0.01)
    attempts: list[int] = []

    async def flaky_send(alert):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("simulated AWS failure")

    monkeypatch.setattr(notifier, "_send_cloudwatch", flaky_send)
    await notifier.start()
    notifier.notify_alert(make_alert())
    await notifier.stop()

    assert len(attempts) == 3  # failed twice, succeeded on the 3rd attempt


async def test_gives_up_after_max_attempts(monkeypatch):
    notifier = AwsNotifier("mock", max_attempts=3, base_backoff=0.01)
    attempts: list[int] = []

    async def always_fails(alert):
        attempts.append(1)
        raise RuntimeError("simulated AWS failure")

    monkeypatch.setattr(notifier, "_send_cloudwatch", always_fails)
    await notifier.start()
    notifier.notify_alert(make_alert())
    await notifier.stop()

    assert len(attempts) == 3
