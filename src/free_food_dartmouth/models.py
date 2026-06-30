from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

DateValue = date | datetime


@dataclass(frozen=True, slots=True)
class EventRecord:
    title: str
    start: DateValue
    end: DateValue
    description: str
    summary: str = ""
    location: str = ""
    sponsor: str = ""
    audience: str = ""
    urls: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    source_keys: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    match_reasons: tuple[str, ...] = ()
    uid_key: str = ""
    tentative: bool = False
    calendar_description: str = ""

    @property
    def all_day(self) -> bool:
        return isinstance(self.start, date) and not isinstance(self.start, datetime)

    @property
    def primary_url(self) -> str:
        return self.urls[0] if self.urls else ""

    @property
    def start_date(self) -> date:
        return self.start.date() if isinstance(self.start, datetime) else self.start

    def with_match_reasons(self, reasons: tuple[str, ...]) -> EventRecord:
        return replace(self, match_reasons=reasons)

    def with_uid_key(self, uid_key: str) -> EventRecord:
        return replace(self, uid_key=uid_key)


@dataclass(frozen=True, slots=True)
class SourceScan:
    source: str
    events: tuple[EventRecord, ...]
    complete: bool = True
