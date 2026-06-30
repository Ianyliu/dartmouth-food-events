from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from dateutil.parser import isoparse
from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from free_food_dartmouth.formatting import calendar_description
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN, unique

MANAGER_ID = "free-food-dartmouth"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
URL_PATTERN = re.compile(r"https?://[^\s<>]+")


@dataclass(frozen=True, slots=True)
class ManagedEvent:
    event_id: str
    source_keys: tuple[str, ...]
    missing_count: int
    uid_key: str
    original_title: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SyncResult:
    active_events: list[EventRecord]
    inserted: int = 0
    updated: int = 0
    marked_tentative: int = 0
    deleted: int = 0


class GoogleCalendarSync:
    def __init__(self, service: Any, calendar_id: str) -> None:
        self.service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_environment(cls) -> GoogleCalendarSync:
        raw_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
        if not raw_key or not calendar_id:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_CALENDAR_ID are required "
                "unless --no-google is used"
            )
        credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            json.loads(raw_key), scopes=SCOPES
        )
        return cls(
            build("calendar", "v3", credentials=credentials, cache_discovery=False), calendar_id
        )

    def reconcile(
        self,
        events: list[EventRecord],
        start: date,
        end: date,
        *,
        dry_run: bool = False,
    ) -> SyncResult:
        existing = self._list_managed(start, end)
        by_key: dict[str, ManagedEvent] = {}
        for item in existing:
            for source_key in item.source_keys:
                by_key[source_key] = item

        used_ids: set[str] = set()
        active: list[EventRecord] = []
        inserted = updated = tentative = deleted = 0
        for event in events:
            match = next(
                (
                    by_key[key]
                    for key in event.source_keys
                    if key in by_key and by_key[key].event_id not in used_ids
                ),
                None,
            )
            if match:
                used_ids.add(match.event_id)
                event = event.with_uid_key(match.uid_key or event.uid_key)
                body = self._event_body(event, missing_count=0)
                if not dry_run:
                    self.service.events().update(
                        calendarId=self.calendar_id,
                        eventId=match.event_id,
                        body=body,
                        sendUpdates="none",
                    ).execute()
                updated += 1
            else:
                body = self._event_body(event, missing_count=0)
                if not dry_run:
                    self.service.events().insert(
                        calendarId=self.calendar_id,
                        body=body,
                        sendUpdates="none",
                    ).execute()
                inserted += 1
            active.append(event)

        for item in existing:
            if item.event_id in used_ids:
                continue
            next_count = item.missing_count + 1
            if next_count >= 2:
                if not dry_run:
                    self.service.events().delete(
                        calendarId=self.calendar_id,
                        eventId=item.event_id,
                        sendUpdates="none",
                    ).execute()
                deleted += 1
                continue
            body = dict(item.raw)
            original_title = item.original_title or str(body.get("summary", "")).removeprefix(
                "[Possibly canceled] "
            )
            body["summary"] = f"[Possibly canceled] {original_title}"
            body["status"] = "tentative"
            private = dict(body.get("extendedProperties", {}).get("private", {}))
            private.update({"missingCount": str(next_count), "originalTitle": original_title})
            body["extendedProperties"] = {"private": private}
            if not dry_run:
                self.service.events().update(
                    calendarId=self.calendar_id,
                    eventId=item.event_id,
                    body=body,
                    sendUpdates="none",
                ).execute()
            active.append(self._record_from_body(body, item))
            tentative += 1

        return SyncResult(active, inserted, updated, tentative, deleted)

    def _list_managed(self, start: date, end: date) -> list[ManagedEvent]:
        time_min = datetime.combine(start, time.min, tzinfo=EASTERN).isoformat()
        time_max = datetime.combine(end, time.min, tzinfo=EASTERN).isoformat()
        items: list[ManagedEvent] = []
        page_token: str | None = None
        while True:
            result = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    showDeleted=False,
                    privateExtendedProperty=f"managedBy={MANAGER_ID}",
                    pageToken=page_token,
                )
                .execute()
            )
            for raw in result.get("items", []):
                private = raw.get("extendedProperties", {}).get("private", {})
                source_keys = unique(str(private.get("sourceKeys", "")).split("|"))
                items.append(
                    ManagedEvent(
                        event_id=str(raw["id"]),
                        source_keys=source_keys,
                        missing_count=int(private.get("missingCount", 0)),
                        uid_key=str(private.get("uidKey", "")),
                        original_title=str(private.get("originalTitle", raw.get("summary", ""))),
                        raw=raw,
                    )
                )
            page_token = result.get("nextPageToken")
            if not page_token:
                return items

    @staticmethod
    def _event_body(event: EventRecord, missing_count: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": event.title,
            "description": calendar_description(event),
            "location": event.location,
            "status": "tentative" if event.tentative else "confirmed",
            "extendedProperties": {
                "private": {
                    "managedBy": MANAGER_ID,
                    "sourceKeys": "|".join(event.source_keys),
                    "uidKey": event.uid_key or event.source_keys[0],
                    "missingCount": str(missing_count),
                    "originalTitle": event.title.removeprefix("[Possibly canceled] "),
                }
            },
        }
        if event.all_day:
            assert isinstance(event.start, date) and not isinstance(event.start, datetime)
            assert isinstance(event.end, date) and not isinstance(event.end, datetime)
            body["start"] = {"date": event.start.isoformat()}
            body["end"] = {"date": event.end.isoformat()}
        else:
            assert isinstance(event.start, datetime)
            assert isinstance(event.end, datetime)
            body["start"] = {"dateTime": event.start.isoformat(), "timeZone": "America/New_York"}
            body["end"] = {"dateTime": event.end.isoformat(), "timeZone": "America/New_York"}
        return body

    @staticmethod
    def _record_from_body(body: dict[str, Any], managed: ManagedEvent) -> EventRecord:
        start_value = body.get("start", {})
        end_value = body.get("end", {})
        if "dateTime" in start_value:
            start: date | datetime = isoparse(start_value["dateTime"]).astimezone(EASTERN)
            end: date | datetime = isoparse(end_value["dateTime"]).astimezone(EASTERN)
        else:
            start = date.fromisoformat(start_value["date"])
            end = date.fromisoformat(end_value["date"])
        description = str(body.get("description", ""))
        sources = unique(
            [
                "Dartmouth" if key.startswith("dartmouth:") else "Geisel"
                for key in managed.source_keys
            ]
        )
        return EventRecord(
            title=str(body.get("summary", "")),
            start=start,
            end=end,
            description="",
            location=str(body.get("location", "")),
            urls=unique(URL_PATTERN.findall(description)),
            source_keys=managed.source_keys,
            sources=sources,
            match_reasons=("not found in the latest complete scan",),
            uid_key=managed.uid_key or managed.source_keys[0],
            tentative=True,
            calendar_description=description,
        )
