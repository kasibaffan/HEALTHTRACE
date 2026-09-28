"""Async, rotation/truncation-safe file tailer (SPEC.md section 6.1).

Polls a file for growth rather than using OS file-change notifications, so it
behaves the same on every platform. Each poll:

- detects rotation (the path now resolves to a different inode/file id) and
  reopens from the start of the new file;
- detects truncation (the file shrank below our last-known offset) and seeks
  back to 0;
- reads any new bytes, splits on newlines, and buffers a trailing partial
  line until the rest of it arrives;
- pushes complete, non-empty lines onto a bounded ``asyncio.Queue`` so a slow
  downstream parser applies backpressure instead of unbounded memory growth.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional


class Tailer:
    def __init__(
        self,
        path: Path,
        queue: "asyncio.Queue[str]",
        *,
        from_start: bool = False,
        poll_interval: float = 0.1,
    ) -> None:
        self.path = Path(path)
        self.queue = queue
        self.from_start = from_start
        self.poll_interval = poll_interval

        self._buffer = ""
        self._offset = 0
        self._inode: Optional[int] = None
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        """Poll forever until :meth:`stop` is called."""
        while not self._stopped:
            try:
                await self.poll_once()
            except FileNotFoundError:
                pass
            await asyncio.sleep(self.poll_interval)

    async def poll_once(self) -> int:
        """Read whatever is new since the last poll. Returns the number of
        complete lines queued (0 if the file hasn't grown, doesn't exist yet,
        or nothing is new).
        """
        stat = self.path.stat()

        if self._inode is None:
            # First sighting of this path: decide where to start reading from.
            self._inode = stat.st_ino
            self._offset = 0 if self.from_start else stat.st_size
        elif stat.st_ino != self._inode:
            # Rotated: the name now points at a different (fresh) file.
            self._inode = stat.st_ino
            self._offset = 0
            self._buffer = ""
        elif stat.st_size < self._offset:
            # Truncated in place.
            self._offset = 0
            self._buffer = ""

        if stat.st_size <= self._offset:
            return 0

        with self.path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self._offset)
            chunk = f.read()
            self._offset = f.tell()

        if not chunk:
            return 0

        self._buffer += chunk
        *complete_lines, self._buffer = self._buffer.split("\n")

        queued = 0
        for line in complete_lines:
            line = line.rstrip("\r")
            if line:
                await self.queue.put(line)
                queued += 1
        return queued
