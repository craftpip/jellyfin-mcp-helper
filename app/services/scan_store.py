"""Scan store — in-memory ledger for ScanPlans.

Phase 1.1: Extract the mutable scan state out of ScanManager so the orchestrator
is easier to test. This is a thin in-memory repository; persistence (sqlite) is
Phase 3.1. Kept intentionally small and synchronous.
"""
from __future__ import annotations

import threading

from fastapi import HTTPException

from app.models.schemas import ScanPlan


class ScanStore:
    def __init__(self) -> None:
        self._current_scan: ScanPlan | None = None
        self._plans: dict[str, ScanPlan] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._tasks: dict[str, object] = {}

    @property
    def current(self) -> ScanPlan | None:
        return self._current_scan

    @current.setter
    def current(self, scan: ScanPlan | None) -> None:
        self._current_scan = scan
        if scan is not None:
            self._plans[scan.scan_id] = scan

    def get(self, scan_id: str) -> ScanPlan:
        if not self._current_scan or self._current_scan.scan_id != scan_id:
            raise HTTPException(status_code=404, detail="Scan not found. Run 'scan library' first.")
        return self._current_scan

    def get_or_none(self, scan_id: str) -> ScanPlan | None:
        if self._current_scan and self._current_scan.scan_id == scan_id:
            return self._current_scan
        return self._plans.get(scan_id)

    def put(self, scan: ScanPlan) -> None:
        self._plans[scan.scan_id] = scan
        self._current_scan = scan

    def cancel_event(self, scan_id: str) -> threading.Event:
        ev = self._cancel_events.get(scan_id)
        if ev is None:
            ev = threading.Event()
            self._cancel_events[scan_id] = ev
        return ev

    @property
    def cancel_events(self) -> dict[str, threading.Event]:
        return self._cancel_events

    @property
    def tasks(self) -> dict[str, object]:
        return self._tasks

    def task(self, scan_id: str) -> object | None:
        return self._tasks.get(scan_id)

    def set_task(self, scan_id: str, task: object) -> None:
        self._tasks[scan_id] = task

    def clear_task(self, scan_id: str) -> None:
        self._tasks.pop(scan_id, None)

    def all_plans(self) -> dict[str, ScanPlan]:
        return self._plans
