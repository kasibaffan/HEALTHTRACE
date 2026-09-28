"""Milestone 2: the tailer must handle append, partial lines, rotation,
truncation, and a missing file, without ever crashing (SPEC.md section 6.1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.ingest.tailer import Tailer


async def _drain(queue: "asyncio.Queue[str]") -> list[str]:
    lines = []
    while not queue.empty():
        lines.append(queue.get_nowait())
    return lines


async def test_tailer_starts_at_end_by_default(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("line-before-start\n", encoding="utf-8")

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue)
    await tailer.poll_once()  # establishes starting offset = end of file

    with path.open("a", encoding="utf-8") as f:
        f.write("line-after-start\n")

    await tailer.poll_once()
    assert await _drain(queue) == ["line-after-start"]


async def test_tailer_from_start_reads_existing_content(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("first\nsecond\n", encoding="utf-8")

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True)
    await tailer.poll_once()

    assert await _drain(queue) == ["first", "second"]


async def test_tailer_buffers_partial_last_line(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("", encoding="utf-8")
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True)
    await tailer.poll_once()

    with path.open("a", encoding="utf-8") as f:
        f.write('{"a": 1}\n{"partial": tr')
    await tailer.poll_once()
    assert await _drain(queue) == ['{"a": 1}']

    with path.open("a", encoding="utf-8") as f:
        f.write("ue}\n")
    await tailer.poll_once()
    assert await _drain(queue) == ['{"partial": true}']


async def test_tailer_detects_truncation(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("one\ntwo\n", encoding="utf-8")
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True)
    await tailer.poll_once()
    assert await _drain(queue) == ["one", "two"]

    # Truncate in place: same file/inode, shorter content.
    path.write_text("three\n", encoding="utf-8")
    await tailer.poll_once()
    assert await _drain(queue) == ["three"]


async def test_tailer_detects_rotation(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("old-1\nold-2\n", encoding="utf-8")
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True)
    await tailer.poll_once()
    assert await _drain(queue) == ["old-1", "old-2"]

    # Rotate: remove the old file and create a brand new one at the same path.
    path.unlink()
    path.write_text("new-1\n", encoding="utf-8")
    await tailer.poll_once()
    assert await _drain(queue) == ["new-1"]


async def test_tailer_run_stops_cleanly(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("", encoding="utf-8")
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True, poll_interval=0.01)

    task = asyncio.create_task(tailer.run())
    with path.open("a", encoding="utf-8") as f:
        f.write("hello\n")
    await asyncio.sleep(0.1)
    tailer.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert await _drain(queue) == ["hello"]


async def test_tailer_missing_file_does_not_raise(tmp_path: Path):
    path = tmp_path / "does-not-exist.log"
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    tailer = Tailer(path, queue, from_start=True, poll_interval=0.01)
    task = asyncio.create_task(tailer.run())
    await asyncio.sleep(0.05)
    tailer.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert queue.empty()
