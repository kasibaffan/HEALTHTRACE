"""AWS notifications: CloudWatch Logs (every alert) and SNS (HIGH/CRITICAL
incidents only), modes off|mock|live (SPEC.md section 6.9).

Runs its own async queue and worker so a slow or failing AWS call never
blocks the detection pipeline: ``notify_alert``/``notify_incident`` do a
``put_nowait`` on an unbounded queue and return immediately, no matter how
long the worker is currently stuck retrying a previous message. Retries with
exponential backoff, up to 5 attempts, then logs and drops the message
rather than blocking forever.

The caller decides *when* SNS should fire ("on creation or escalation" —
SPEC.md 6.9): this module only re-checks severity as a safety net.

Credentials are never configured here: in live mode boto3 resolves them
through its default chain (ECS task role, instance profile, SSO, env).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Union

from app.models import Alert, Incident

logger = logging.getLogger(__name__)

AwsMode = Literal["off", "mock", "live"]
Channel = Literal["cloudwatch", "sns"]
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 0.5
STOP_DRAIN_TIMEOUT_SECONDS = 10.0

_KIND_LABELS: dict[str, str] = {
    "error_rate": "error rate spike",
    "latency_degradation": "latency spike",
    "hipaa_bulk_access": "bulk record access",
    "hipaa_bulk_export": "bulk record export",
    "hipaa_off_hours": "off-hours access",
    "hipaa_region_mismatch": "cross-region access",
}

_CloudWatchItem = tuple[Literal["cloudwatch"], Alert]
_SnsItem = tuple[Literal["sns"], Incident, str]
_QueueItem = Union[_CloudWatchItem, _SnsItem]


class SnsNotConfigured(RuntimeError):
    pass


@dataclass
class ChannelStatus:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    retries: int = 0
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: Optional[str] = None
    recent: list[dict[str, Any]] = field(default_factory=list)

    def record(self, outcome: str, subject: str, error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc)
        if outcome == "sent":
            self.sent += 1
            self.last_success_at = now
        elif outcome == "failed":
            self.failed += 1
            self.last_failure_at = now
            self.last_error = error
        else:
            self.skipped += 1
        self.recent.append({"ts": now.isoformat(), "outcome": outcome, "subject": subject, "error": error})
        del self.recent[:-25]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "failed": self.failed,
            "skipped": self.skipped,
            "retries": self.retries,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "last_error": self.last_error,
            "recent": list(reversed(self.recent)),
        }


class AwsNotifier:
    def __init__(
        self,
        mode: AwsMode,
        *,
        region: str = "us-east-1",
        log_group: str = "/medguard/alerts",
        sns_topic_arn: str = "",
        mock_log_path: Optional[Path] = None,
        max_attempts: int = MAX_ATTEMPTS,
        base_backoff: float = BASE_BACKOFF_SECONDS,
    ) -> None:
        self.mode = mode
        self.region = region
        self.log_group = log_group
        self.sns_topic_arn = sns_topic_arn
        self.mock_log_path = mock_log_path
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff

        self._queue: "asyncio.Queue[_QueueItem]" = asyncio.Queue()  # unbounded: never blocks the producer
        self._worker_task: Optional[asyncio.Task] = None
        self._boto_logs_client = None
        self._boto_sns_client = None
        self._ensured_streams: set[str] = set()
        self.status: dict[Channel, ChannelStatus] = {"cloudwatch": ChannelStatus(), "sns": ChannelStatus()}

    async def start(self) -> None:
        if self.mode != "off" and self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())

    async def stop(self, drain_timeout: float = STOP_DRAIN_TIMEOUT_SECONDS) -> None:
        """Drain pending notifications, but never let a failing AWS endpoint
        hold shutdown hostage beyond ``drain_timeout``."""
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
            except asyncio.TimeoutError:
                logger.warning("notifier: shutdown with %d notifications undelivered", self._queue.qsize())
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def notify_alert(self, alert: Alert) -> None:
        """CloudWatch Logs: every alert (SPEC.md 6.9)."""
        if self.mode == "off":
            return
        self._queue.put_nowait(("cloudwatch", alert))

    def notify_incident(self, incident: Incident, explanation: str) -> None:
        """SNS: HIGH/CRITICAL only. Call this on incident creation or
        escalation (SPEC.md 6.9) — this method itself just re-checks severity."""
        if self.mode == "off":
            return
        if incident.peak_severity not in ("HIGH", "CRITICAL"):
            return
        self._queue.put_nowait(("sns", incident, explanation))

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def sns_configured(self) -> bool:
        return bool(self.sns_topic_arn)

    # -- worker ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._process_with_retry(item)
            except Exception:
                logger.exception("notifier: unexpected error processing %r", item)
            finally:
                self._queue.task_done()

    async def _process_with_retry(self, item: _QueueItem) -> None:
        channel: Channel = item[0]
        subject = self._subject_for(item)
        status = self.status[channel]
        for attempt in range(1, self.max_attempts + 1):
            try:
                if item[0] == "cloudwatch":
                    await self._send_cloudwatch(item[1])
                else:
                    await self._send_sns(item[1], item[2])
                status.record("sent", subject)
                return
            except SnsNotConfigured as exc:
                status.record("skipped", subject, str(exc))
                return
            except Exception as exc:
                if attempt == self.max_attempts:
                    logger.error("notifier: giving up after %d attempts (%s): %s", attempt, channel, exc)
                    status.record("failed", subject, f"{type(exc).__name__}: {exc}")
                    return
                status.retries += 1
                await asyncio.sleep(self.base_backoff * (2 ** (attempt - 1)))

    @staticmethod
    def _subject_for(item: _QueueItem) -> str:
        if item[0] == "cloudwatch":
            alert = item[1]
            return f"{alert.severity} {alert.kind} {alert.service or alert.user_id or ''}".strip()
        incident = item[1]
        return f"incident #{incident.id} {incident.peak_severity}"

    # -- senders -----------------------------------------------------------------

    async def _send_cloudwatch(self, alert: Alert) -> None:
        if self.mode == "mock":
            self._append_mock(
                {"aws_service": "cloudwatch_logs", "log_group": self.log_group, "alert": alert.model_dump(mode="json")}
            )
            return
        await self._put_log_event(alert.ts, json.dumps(alert.model_dump(mode="json")))

    async def _put_log_event(self, ts: datetime, message: str) -> None:
        client = self._logs_client()
        stream = ts.strftime("%Y-%m-%d")
        await asyncio.to_thread(self._ensure_log_stream, client, stream)
        await asyncio.to_thread(
            client.put_log_events,
            logGroupName=self.log_group,
            logStreamName=stream,
            logEvents=[{"timestamp": int(ts.timestamp() * 1000), "message": message}],
        )

    async def _send_sns(self, incident: Incident, explanation: str) -> None:
        target = incident.service or incident.user_id or "unknown"
        label = _KIND_LABELS.get(incident.kind, incident.kind)
        subject = f"[MedGuard {incident.peak_severity}] {target}: {label}"[:100]
        body = f"{explanation}\n\nIncident ID: {incident.id}"
        await self._publish(subject, body)

    async def _publish(self, subject: str, body: str) -> None:
        if self.mode == "mock":
            self._append_mock(
                {"aws_service": "sns", "topic_arn": self.sns_topic_arn, "subject": subject, "body": body}
            )
            return
        if not self.sns_topic_arn:
            raise SnsNotConfigured("SNS_TOPIC_ARN is not set")
        client = self._sns_client()
        await asyncio.to_thread(client.publish, TopicArn=self.sns_topic_arn, Subject=subject, Message=body)

    def _append_mock(self, payload: dict) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
        line = json.dumps(record, default=str)
        print(f"[aws:mock] {line}")
        if self.mock_log_path is not None:
            self.mock_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.mock_log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # -- operator actions (AWS page) --------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Read-only reachability check against the configured resources."""
        if self.mode != "live":
            return {
                "mode": self.mode,
                "cloudwatch": {"ok": self.mode == "mock", "detail": f"AWS_MODE={self.mode}: no AWS calls are made"},
                "sns": {"ok": self.mode == "mock", "detail": f"AWS_MODE={self.mode}: no AWS calls are made"},
            }
        return {
            "mode": self.mode,
            "cloudwatch": await self._check(self._check_cloudwatch),
            "sns": await self._check(self._check_sns),
        }

    async def send_test_alert(self) -> dict[str, Any]:
        """Deliver one clearly-labelled test message through each channel,
        bypassing the queue so the operator sees the real outcome."""
        if self.mode == "off":
            return {"mode": self.mode, "cloudwatch": {"ok": False, "detail": "AWS_MODE=off"},
                    "sns": {"ok": False, "detail": "AWS_MODE=off"}}
        now = datetime.now(timezone.utc)
        message = json.dumps({"test": True, "ts": now.isoformat(), "explanation": "HEALTH TRACE test alert"})

        async def cloudwatch() -> str:
            if self.mode == "mock":
                self._append_mock({"aws_service": "cloudwatch_logs", "log_group": self.log_group, "test": True})
                return "written to data/aws_mock.log"
            await self._put_log_event(now, message)
            return f"put 1 event to {self.log_group}"

        async def sns() -> str:
            await self._publish("[MedGuard TEST] HEALTH TRACE test alert", "This is a test notification.")
            return "published" if self.mode == "live" else "written to data/aws_mock.log"

        results = {"mode": self.mode}
        for channel, fn in (("cloudwatch", cloudwatch), ("sns", sns)):
            result = await self._check(fn)
            self.status[channel].record("sent" if result["ok"] else "failed", "test alert",
                                        None if result["ok"] else result["detail"])
            results[channel] = result
        return results

    async def _check(self, fn) -> dict[str, Any]:
        try:
            detail = await asyncio.wait_for(fn(), timeout=10)
            return {"ok": True, "detail": detail}
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    async def _check_cloudwatch(self) -> str:
        client = self._logs_client()
        resp = await asyncio.to_thread(client.describe_log_groups, logGroupNamePrefix=self.log_group, limit=1)
        groups = [g["logGroupName"] for g in resp.get("logGroups", [])]
        return f"log group {self.log_group} {'exists' if self.log_group in groups else 'will be created on first alert'}"

    async def _check_sns(self) -> str:
        if not self.sns_topic_arn:
            raise SnsNotConfigured("SNS_TOPIC_ARN is not set")
        client = self._sns_client()
        attrs = await asyncio.to_thread(client.get_topic_attributes, TopicArn=self.sns_topic_arn)
        confirmed = attrs.get("Attributes", {}).get("SubscriptionsConfirmed", "?")
        return f"topic reachable, {confirmed} confirmed subscription(s)"

    def credentials_source(self) -> Optional[str]:
        """Where boto3 found credentials (e.g. 'container-role', 'env') — never the keys."""
        if self.mode != "live":
            return None
        try:
            import boto3

            creds = boto3.Session().get_credentials()
            return creds.method if creds is not None else None
        except Exception:
            return None

    # -- clients -----------------------------------------------------------------

    def _logs_client(self):
        if self._boto_logs_client is None:
            import boto3

            self._boto_logs_client = boto3.client("logs", region_name=self.region)
        return self._boto_logs_client

    def _sns_client(self):
        if self._boto_sns_client is None:
            import boto3

            self._boto_sns_client = boto3.client("sns", region_name=self.region)
        return self._boto_sns_client

    def _ensure_log_stream(self, client, stream: str) -> None:
        if stream in self._ensured_streams:
            return
        try:
            client.create_log_group(logGroupName=self.log_group)
        except client.exceptions.ResourceAlreadyExistsException:
            pass
        try:
            client.create_log_stream(logGroupName=self.log_group, logStreamName=stream)
        except client.exceptions.ResourceAlreadyExistsException:
            pass
        self._ensured_streams.add(stream)
