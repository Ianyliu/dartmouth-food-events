"""Events from a public Google Calendar ICS feed.

A public Google Calendar exposes its events without authentication at
``https://calendar.google.com/calendar/ical/<id>/public/basic.ics``. This
module fetches that feed, expands recurring events (including recurrence
exceptions and moved occurrences), and drops cancelled events before they
reach the food matcher.

The calendar ID is pinned in each house module. Deriving it from a house
homepage broke for East Wheelock when its standalone site stopped
resolving, and a pinned ID keeps the feed working without a homepage
scrape.

Two safeguards matter here:

- A feed that cannot be fetched or parsed raises instead of returning an
  empty scan, so an outage is never mistaken for "no events" (the sync
  treats an incomplete scan as a reason to keep previously published
  events, never as proof they were cancelled). A successful fetch that
  genuinely contains no events in the window is a complete, empty scan.
- Event URLs never contain the shared feed URL or the shared calendar
  page URL. Those URLs are identical for every event from one calendar,
  and the deduplicator treats a shared URL at the same start time as the
  same event, which would falsely merge unrelated same-time events. Only
  an event-specific URL from the feed itself is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from dateutil.rrule import rruleset, rrulestr
from icalendar import Calendar

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, easternize, unique

CANCELLED_TITLE = re.compile(r"^\s*(?:cancell?ed|postponed)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PublicGoogleCalendarConfig:
    """Identity of one public Google Calendar."""

    name: str
    calendar_id: str
    key_prefix: str
    page_url: str


@dataclass(frozen=True, slots=True)
class _RawEvent:
    uid: str
    title: str
    status: str
    description: str
    location: str
    url: str
    start: date | datetime
    end: date | datetime | None
    rrule_text: str | None
    rdates: tuple[date | datetime, ...]
    exdates: tuple[date | datetime, ...]
    recurrence_id: date | datetime | None


@dataclass(frozen=True, slots=True)
class _Occurrence:
    identity: str
    start: date | datetime
    end: date | datetime
    title: str
    description: str
    location: str
    url: str


def _is_cancelled(title: str, status: str) -> bool:
    return status.upper() == "CANCELLED" or CANCELLED_TITLE.match(title) is not None


def _single_datetime(raw: object) -> date | datetime | None:
    candidate = getattr(raw, "dt", raw)
    if isinstance(candidate, (list, tuple)):
        candidate = candidate[0] if candidate else None
    if isinstance(candidate, (date, datetime)):
        return candidate
    return None


def _datetime_values(raw: object) -> list[date | datetime]:
    if raw is None:
        return []
    if isinstance(raw, (date, datetime)):
        return [raw]
    if isinstance(raw, (list, tuple)):
        items: list[object] = list(raw)
    else:
        unwrapped = getattr(raw, "dt", None)
        if unwrapped is None:
            # icalendar's vDDDLists exposes its values as .dts.
            unwrapped = getattr(raw, "dts", None)
        if isinstance(unwrapped, (list, tuple)):
            items = list(unwrapped)
        elif isinstance(unwrapped, (date, datetime)):
            items = [unwrapped]
        else:
            items = [raw]
    values: list[date | datetime] = []
    for item in items:
        candidate = getattr(item, "dt", item)
        if isinstance(candidate, (list, tuple)):
            values.extend(value for value in candidate if isinstance(value, (date, datetime)))
        elif isinstance(candidate, (date, datetime)):
            values.append(candidate)
    return values


def _parse_component(component: object) -> _RawEvent:
    if not hasattr(component, "decoded") or not hasattr(component, "get"):
        raise TypeError("invalid iCalendar component")
    decoded = component.decoded
    get = component.get
    uid = str(get("uid", "") or "").strip()
    if not uid:
        raise ValueError("missing event UID")
    title = str(get("summary", "") or "").strip()
    if not title:
        raise ValueError("missing event title")
    start = _single_datetime(decoded("dtstart", None))
    if start is None:
        raise ValueError("missing event start")
    end = _single_datetime(decoded("dtend", None)) if get("dtend") is not None else None
    raw_rrule = get("rrule")
    rrule_text: str | None = None
    if raw_rrule is not None:
        to_ical = getattr(raw_rrule, "to_ical", None)
        if callable(to_ical):
            encoded = to_ical()
            rrule_text = encoded.decode() if isinstance(encoded, bytes) else str(encoded)
        else:
            rrule_text = str(raw_rrule)
    recurrence_id = (
        _single_datetime(decoded("recurrence-id", None))
        if get("recurrence-id") is not None
        else None
    )
    event_url = str(get("url", "") or "").strip()
    if not event_url.startswith(("http://", "https://")):
        event_url = ""
    return _RawEvent(
        uid=uid,
        title=title,
        status=str(get("status", "") or "").strip(),
        description=str(get("description", "") or "").strip(),
        location=str(get("location", "") or "").strip(),
        url=event_url,
        start=easternize(start),
        end=easternize(end) if end is not None else None,
        rrule_text=rrule_text,
        rdates=tuple(easternize(value) for value in _datetime_values(get("rdate"))),
        exdates=tuple(easternize(value) for value in _datetime_values(get("exdate"))),
        recurrence_id=easternize(recurrence_id) if recurrence_id is not None else None,
    )


def _occurrence_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _to_aware(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=EASTERN)
    return datetime.combine(value, time.min, tzinfo=EASTERN)


def _duration(master: _RawEvent) -> timedelta:
    if master.end is not None:
        start_dt = _to_aware(master.start)
        end_dt = _to_aware(master.end)
        if end_dt > start_dt:
            return end_dt - start_dt
    if isinstance(master.start, datetime):
        return timedelta(hours=1)
    return timedelta(days=1)


def _end_for(
    start: date | datetime, end: date | datetime | None, duration: timedelta
) -> date | datetime:
    if end is not None:
        return end
    if isinstance(start, datetime):
        return _to_aware(start) + duration
    return start + duration


def _expand_group(
    master: _RawEvent | None,
    overrides: dict[str, _RawEvent],
    start: date,
    end: date,
) -> list[_Occurrence]:
    """Expand one UID group into occurrences inside [start, end)."""
    if master is None:
        # Overrides without a master: each is an event in its own right.
        occurrences: list[_Occurrence] = []
        for identity, override in overrides.items():
            if _is_cancelled(override.title, override.status):
                continue
            if not (start <= _occurrence_date(override.start) < end):
                continue
            occurrences.append(
                _Occurrence(
                    identity=identity,
                    start=override.start,
                    end=_end_for(override.start, override.end, timedelta(hours=1)),
                    title=override.title,
                    description=override.description,
                    location=override.location,
                    url=override.url,
                )
            )
        return occurrences

    duration = _duration(master)
    all_day = not isinstance(master.start, datetime)

    def fields_for(override: _RawEvent | None) -> tuple[str, str, str, str]:
        if override is None:
            return master.title, master.description, master.location, master.url
        return (
            override.title or master.title,
            override.description or master.description,
            override.location or master.location,
            override.url or master.url,
        )

    occurrences = []
    emitted: set[str] = set()

    def emit(
        identity: str,
        occ_start: date | datetime,
        occ_end: date | datetime,
        override: _RawEvent | None,
    ) -> None:
        if identity in emitted:
            return
        if not (start <= _occurrence_date(occ_start) < end):
            return
        emitted.add(identity)
        title, description, location, url = fields_for(override)
        occurrences.append(
            _Occurrence(
                identity=identity,
                start=occ_start,
                end=occ_end,
                title=title,
                description=description,
                location=location,
                url=url,
            )
        )

    if master.rrule_text is None and not master.rdates:
        if not _is_cancelled(master.title, master.status):
            emit(
                "",
                master.start,
                _end_for(master.start, master.end, duration),
                None,
            )
        # A non-recurring master cannot own occurrences, so any override
        # attached to it is emitted on its own start time instead.
        for identity, override in overrides.items():
            if _is_cancelled(override.title, override.status):
                continue
            emit(
                identity,
                override.start,
                _end_for(override.start, override.end, duration),
                override,
            )
        return occurrences

    if _is_cancelled(master.title, master.status):
        return occurrences

    master_tz = _to_aware(master.start).tzinfo or EASTERN
    window_start = datetime.combine(start, time.min, tzinfo=EASTERN).astimezone(master_tz)
    window_end = datetime.combine(end, time.min, tzinfo=EASTERN).astimezone(master_tz)
    if master.rrule_text is not None:
        rules = rrulestr(master.rrule_text, dtstart=_to_aware(master.start), forceset=True)
        if not isinstance(rules, rruleset):
            raise ValueError("unsupported recurrence rule")
    else:
        rules = rruleset()
    # DTSTART is the first instance in the recurrence set (RFC 5545), so
    # it is always included; the emit step dedupes it when the rule yields it.
    rules.rdate(_to_aware(master.start))
    for rdate in master.rdates:
        rules.rdate(_to_aware(rdate))
    for exdate in master.exdates:
        rules.exdate(_to_aware(exdate))
    excluded = {value.isoformat() for value in master.exdates}

    for generated in rules.between(window_start, window_end, inc=True):
        eastern = generated.astimezone(EASTERN)
        identity = eastern.date().isoformat() if all_day else eastern.isoformat()
        if identity in excluded:
            continue
        replacement = overrides.get(identity)
        if replacement is not None:
            if _is_cancelled(replacement.title, replacement.status):
                continue
            emit(
                identity,
                replacement.start,
                _end_for(replacement.start, replacement.end, duration),
                replacement,
            )
        else:
            occ_start: date | datetime = eastern.date() if all_day else eastern
            occ_end: date | datetime = eastern.date() + duration if all_day else eastern + duration
            emit(identity, occ_start, occ_end, None)

    # Overrides that move an occurrence into the window from outside it.
    for identity, override in overrides.items():
        if identity in emitted or _is_cancelled(override.title, override.status):
            continue
        emit(
            identity,
            override.start,
            _end_for(override.start, override.end, duration),
            override,
        )
    return occurrences


class PublicGoogleCalendarSource:
    """One public Google Calendar, fetched as ICS and expanded."""

    def __init__(self, config: PublicGoogleCalendarConfig, client: HttpClient | None = None):
        self.config = config
        self.client = client or HttpClient()

    @property
    def ics_url(self) -> str:
        return (
            "https://calendar.google.com/calendar/ical/"
            f"{quote(self.config.calendar_id, safe='')}/public/basic.ics"
        )

    def scan(self, start: date, end: date) -> SourceScan:
        response = self.client.get(self.ics_url)
        payload = response.content
        if not payload.lstrip().startswith(b"BEGIN:VCALENDAR"):
            raise ValueError("not an iCalendar feed")
        calendar = Calendar.from_ical(payload)
        masters: dict[str, _RawEvent] = {}
        overrides: dict[str, dict[str, _RawEvent]] = {}
        failures: list[str] = []
        for component in calendar.walk("VEVENT"):
            try:
                raw = _parse_component(component)
            except (ValueError, TypeError) as exc:
                failures.append(str(exc))
                continue
            if raw.recurrence_id is not None:
                overrides.setdefault(raw.uid, {})[raw.recurrence_id.isoformat()] = raw
            elif raw.uid in masters:
                failures.append(f"duplicate event {raw.uid}")
            else:
                masters[raw.uid] = raw
        events: list[EventRecord] = []
        for uid, master in masters.items():
            try:
                occurrences = _expand_group(master, overrides.get(uid, {}), start, end)
            except ValueError as exc:
                failures.append(f"{uid}: {exc}")
                continue
            for occurrence in occurrences:
                source_key = (
                    f"{self.config.key_prefix}:{uid}"
                    if not occurrence.identity
                    else f"{self.config.key_prefix}:{uid}:{occurrence.identity}"
                )
                events.append(
                    EventRecord(
                        title=occurrence.title,
                        start=occurrence.start,
                        end=occurrence.end,
                        description=occurrence.description,
                        summary=occurrence.description.split("\n", 1)[0][:500],
                        location=occurrence.location,
                        sponsor=self.config.name,
                        urls=unique((occurrence.url,)),
                        categories=("House Community", self.config.name),
                        source_keys=(source_key,),
                        sources=(self.config.name,),
                        uid_key=source_key,
                    )
                )
        for uid, orphan_overrides in overrides.items():
            if uid in masters:
                continue
            for occurrence in _expand_group(None, orphan_overrides, start, end):
                source_key = f"{self.config.key_prefix}:{uid}:{occurrence.identity}"
                events.append(
                    EventRecord(
                        title=occurrence.title,
                        start=occurrence.start,
                        end=occurrence.end,
                        description=occurrence.description,
                        summary=occurrence.description.split("\n", 1)[0][:500],
                        location=occurrence.location,
                        sponsor=self.config.name,
                        urls=unique((occurrence.url,)),
                        categories=("House Community", self.config.name),
                        source_keys=(source_key,),
                        sources=(self.config.name,),
                        uid_key=source_key,
                    )
                )
        events.sort(key=lambda event: (str(event.start), event.title.casefold()))
        return SourceScan(
            self.config.name,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )
