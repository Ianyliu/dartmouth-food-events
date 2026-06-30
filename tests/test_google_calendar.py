from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from free_food_dartmouth.google_calendar import MANAGER_ID, GoogleCalendarSync
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN


class FakeRequest:
    def __init__(self, value: dict[str, Any] | None = None) -> None:
        self.value = value or {}

    def execute(self) -> dict[str, Any]:
        return self.value


class FakeEvents:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.inserted: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[str] = []

    def list(self, **_: Any) -> FakeRequest:
        return FakeRequest({"items": self.items})

    def insert(self, *, body: dict[str, Any], **_: Any) -> FakeRequest:
        self.inserted.append(body)
        return FakeRequest({"id": "new"})

    def update(self, *, eventId: str, body: dict[str, Any], **_: Any) -> FakeRequest:
        self.updated.append((eventId, body))
        return FakeRequest(body)

    def delete(self, *, eventId: str, **_: Any) -> FakeRequest:
        self.deleted.append(eventId)
        return FakeRequest()


class FakeService:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.resource = FakeEvents(items)

    def events(self) -> FakeEvents:
        return self.resource


def candidate() -> EventRecord:
    start = datetime(2026, 7, 9, 12, tzinfo=EASTERN)
    return EventRecord(
        "Seminar with lunch",
        start,
        start + timedelta(hours=1),
        "A light lunch will be provided.",
        urls=("https://example.org/event",),
        source_keys=("geisel:1:2026-7-9",),
        sources=("Geisel",),
        match_reasons=("explicit food-service wording",),
        uid_key="geisel:1:2026-7-9",
    )


def existing(missing_count: int = 0, title: str = "Seminar with lunch") -> dict[str, Any]:
    return {
        "id": "google-1",
        "summary": title,
        "description": "Original event page(s):\nhttps://example.org/event",
        "location": "Auditorium",
        "status": "confirmed",
        "start": {"dateTime": "2026-07-09T12:00:00-04:00"},
        "end": {"dateTime": "2026-07-09T13:00:00-04:00"},
        "extendedProperties": {
            "private": {
                "managedBy": MANAGER_ID,
                "sourceKeys": "geisel:1:2026-7-9",
                "uidKey": "geisel:1:2026-7-9",
                "missingCount": str(missing_count),
                "originalTitle": "Seminar with lunch",
            }
        },
    }


def test_insert_and_update_are_keyed_by_private_source_id() -> None:
    new_service = FakeService([])
    new_result = GoogleCalendarSync(new_service, "calendar").reconcile(
        [candidate()], date(2026, 7, 1), date(2026, 7, 15)
    )
    assert new_result.inserted == 1
    assert new_service.resource.inserted[0]["extendedProperties"]["private"]["sourceKeys"]

    update_service = FakeService([existing()])
    update_result = GoogleCalendarSync(update_service, "calendar").reconcile(
        [candidate()], date(2026, 7, 1), date(2026, 7, 15)
    )
    assert update_result.updated == 1
    assert update_service.resource.updated[0][1]["summary"] == "Seminar with lunch"
    assert update_service.resource.updated[0][1]["status"] == "confirmed"


def test_missing_event_is_marked_then_deleted_on_second_scan() -> None:
    first_service = FakeService([existing()])
    first = GoogleCalendarSync(first_service, "calendar").reconcile(
        [], date(2026, 7, 1), date(2026, 7, 15)
    )
    assert first.marked_tentative == 1
    assert first_service.resource.updated[0][1]["summary"].startswith("[Possibly canceled]")
    assert first.active_events[0].tentative

    second_service = FakeService([existing(1, "[Possibly canceled] Seminar with lunch")])
    second = GoogleCalendarSync(second_service, "calendar").reconcile(
        [], date(2026, 7, 1), date(2026, 7, 15)
    )
    assert second.deleted == 1
    assert second_service.resource.deleted == ["google-1"]


def test_reappearing_event_restores_original_title_and_status() -> None:
    service = FakeService([existing(1, "[Possibly canceled] Seminar with lunch")])
    result = GoogleCalendarSync(service, "calendar").reconcile(
        [candidate()], date(2026, 7, 1), date(2026, 7, 15)
    )
    assert result.updated == 1
    body = service.resource.updated[0][1]
    assert body["summary"] == "Seminar with lunch"
    assert body["status"] == "confirmed"
    assert body["extendedProperties"]["private"]["missingCount"] == "0"
