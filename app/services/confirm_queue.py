"""Confirm queue — extracted from ScanManager for long-horizon maintainability.

Phase 1.1: Isolate the FIFO queue that holds confirms arriving while a move is
running. ScanManager still owns the ScanPlan and the async task lifecycle;
this class only holds the queued payloads and simple bookkeeping.

The queue holds dicts: {scan_id, item_ids, source_paths, source_prefixes, total}
"""
from __future__ import annotations


class ConfirmQueue:
    def __init__(self) -> None:
        self._entries: list[dict] = []

    def append(self, entry: dict) -> None:
        self._entries.append(entry)

    def popleft(self) -> dict | None:
        if not self._entries:
            return None
        return self._entries.pop(0)

    def peek(self) -> dict | None:
        return self._entries[0] if self._entries else None

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def queue_length(self) -> int:
        return len(self._entries)

    def queue_items_total(self) -> int:
        return sum(e.get("total", 0) for e in self._entries)

    def __iter__(self):
        return iter(self._entries)

    # For tests that inspect internal state directly, expose list view
    @property
    def entries(self) -> list[dict]:
        return self._entries
