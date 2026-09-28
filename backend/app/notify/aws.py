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
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Union

from app.models import Alert, Incident

logger = logging.getLogger(__name__)

AwsMode = Literal["off", "mock", "live"]
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 0.5

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

    async def start(self) -> None:
        if self.mode != "off" and self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker_task is not None:
            await self._queue.join()
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
        for attempt in range(1, self.max_attempts + 1):
            try:
                if item[0] == "cloudwatch":
                    await self._send_cloudwatch(item[1])
                else:
                    await self._send_sns(item[1], item[2])
                return
            except Exception as exc:
                if attempt == self.max_attempts:
                    logger.error("notifier: giving up after %d attempts (%s): %s", attempt, item[0], exc)
                    return
                await asyncio.sleep(self.base_backoff * (2 ** (attempt - 1)))

    async def _send_cloudwatch(self, alert: Alert) -> None:
        if self.mode == "mock":
            self._append_mock(
                {"aws_service": "cloudwatch_logs", "log_group": self.log_group, "alert": alert.model_dump(mode="json")}
            )
            return
        client = self._logs_client()
        stream = alert.ts.strftime("%Y-%m-%d")
        await asyncio.to_thread(self._ensure_log_stream, client, stream)
        await asyncio.to_thread(
            client.put_log_events,
            logGroupName=self.log_group,
            logStreamName=stream,
            logEvents=[
                {"timestamp": int(alert.ts.timestamp() * 1000), "message": json.dumps(alert.model_dump(mode="json"))}
            ],
        )

    async def _send_sns(self, incident: Incident, explanation: str) -> None:
        target = incident.service or incident.user_id or "unknown"
        label = _KIND_LABELS.get(incident.kind, incident.kind)
        subject = f"[MedGuard {incident.peak_severity}] {target}: {label}"[:100]
        body = f"{explanation}\n\nIncident ID: {incident.id}"

        if self.mode == "mock":
            self._append_mock(
                {"aws_service": "sns", "topic_arn": self.sns_topic_arn, "subject": subject, "body": body}
            )
            return
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
