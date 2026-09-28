"""Async, rotation/truncation-safe file tailer (SPEC.md section 6.1).

Polls a file for growth rather than using OS file-change notifications, so it
behaves the same on every platform. Each poll:

- detects rotation (the path now resolves to a different inode/file id) and
  reopens from the start of the new file;
- detects truncation (the file shrank below our last-known offset) and seeks
  back to 0;
- reads at most ``max_chunk_bytes`` of new data, splits on newlines, and
  buffers a trailing partial line until the rest of it arrives;
- pushes complete, non-empty lines onto a bounded ``asyncio.Queue`` so a slow
  downstream parser applies backpressure instead of unbounded memory growth.

Reads are bounded and byte-oriented: a first-run replay of a multi-hundred-MB
backfill is streamed a chunk at a time instead of being loaded whole, and
offsets are true byte positions that can be persisted and resumed from.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

DEFAULT_MAX_CHUNK_BYTES = 1 << 20


class Tailer:
    def __init__(
        self,
        path: Path,
        queue: "asyncio.Queue[str]",
        *,
        from_start: bool = False,
        poll_interval: float = 0.1,
        resume_offset: Optional[int] = None,
        resume_file_id: Optional[int] = None,
        max_chunk_bytes: int = DEFAULT_MAX_CHUNK_BYTES,
    ) -> None:
        self.path = Path(path)
        self.queue = queue
        self.from_start = from_start
        self.poll_interval = poll_interval
        self.max_chunk_bytes = max_chunk_bytes
        self._resume_offset = resume_offset
        self._resume_file_id = resume_file_id

        self._buffer = b""
        self._offset = 0
        self._inode: Optional[int] = None
        self._stopped = False
        self.caught_up = False
        self.file_size = 0

    def stop(self) -> None:
        self._stopped = True

    @property
    def file_id(self) -> Optional[int]:
        return self._inode

    @property
    def committed_offset(self) -> int:
        """Byte offset of the end of the last complete line handed to the queue."""
        return self._offset - len(self._buffer)

    async def run(self) -> None:
        """Poll until :meth:`stop` is called. Sleeps only once caught up, so a
        large backlog is drained as fast as the downstream queue allows."""
        while not self._stopped:
            try:
                await self.poll_once()
            except FileNotFoundError:
                self.caught_up = True
            if self.caught_up:
                await asyncio.sleep(self.poll_interval)
            else:
                await asyncio.sleep(0)

    def _initial_offset(self, file_id: int, size: int) -> int:
        if self._resume_offset is not None:
            same_file = self._resume_file_id is None or self._resume_file_id == file_id
            if same_file and self._resume_offset <= size:
                return self._resume_offset
            return 0  # rotated or truncated since the position was saved: read the new file whole
        return 0 if self.from_start else size

    async def poll_once(self) -> int:
        """Read up to one chunk of whatever is new since the last poll.
        Returns the number of complete lines queued."""
        stat = self.path.stat()
        self.file_size = stat.st_size

        if self._inode is None:
            self._inode = stat.st_ino
            self._offset = self._initial_offset(stat.st_ino, stat.st_size)
        elif stat.st_ino != self._inode:
            self._inode = stat.st_ino
            self._offset = 0
            self._buffer = b""
        elif stat.st_size < self._offset:
            self._offset = 0
            self._buffer = b""

        if stat.st_size <= self._offset:
            self.caught_up = True
            return 0

        with self.path.open("rb") as f:
            f.seek(self._offset)
            chunk = f.read(self.max_chunk_bytes)
            self._offset = f.tell()

        self.caught_up = self._offset >= stat.st_size
        if not chunk:
            return 0

        self._buffer += chunk
        *complete_lines, self._buffer = self._buffer.split(b"\n")

        queued = 0
        for raw in complete_lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if line:
                await self.queue.put(line)
                queued += 1
        return queued
