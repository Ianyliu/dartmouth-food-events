from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, unique

ARCHIVE_URL = "https://sites.dartmouth.edu/south-house/south-house-weekly/"
SOURCE_NAME = "South House"

ISSUE_DATE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)
EVENT_DATE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tue|Wed|Thu|Fri|Sat|Sun)?[,]?\s*"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2}(?:,?\s+\d{4})?",
    re.IGNORECASE,
)
EVENT_TIME = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))"
    r"(?:\s*(?:-|to|\u2013|\u2014)\s*"
    r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)))?",
    re.IGNORECASE,
)
LOCATION = re.compile(r"\b(?:location|where)\s*:\s*([^\n|]+)", re.IGNORECASE)


class SouthHouseSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        response = self.client.get(ARCHIVE_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        issues = self._relevant_issues(soup, start, end)

        events: list[EventRecord] = []
        failures: list[str] = []
        for issue_date, issue_url in issues:
            try:
                newsletter = self.client.get(issue_url)
                content_type = newsletter.headers.get("Content-Type", "").casefold()
                if "html" not in content_type and "text" not in content_type:
                    failures.append(
                        f"{issue_url}: unsupported newsletter content type "
                        f"{content_type or 'unknown'}"
                    )
                    continue
                events.extend(self._events(newsletter.text, issue_date, issue_url, start, end))
            except Exception as exc:
                failures.append(f"{issue_url}: {exc}")

        return SourceScan(
            SOURCE_NAME,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    @staticmethod
    def _relevant_issues(soup: BeautifulSoup, start: date, end: date) -> list[tuple[date, str]]:
        earliest = start - timedelta(days=7)
        issues: list[tuple[date, str]] = []
        for anchor in soup.select("a[href]"):
            text = anchor.get_text(" ", strip=True)
            match = ISSUE_DATE.search(text)
            if match is None:
                continue
            issue_date = date_parser.parse(match.group(0), fuzzy=True).date()
            if not earliest <= issue_date < end:
                continue
            href = urljoin(ARCHIVE_URL, str(anchor.get("href", "")))
            if href.startswith(("http://", "https://")):
                issues.append((issue_date, href))
        return list(dict.fromkeys(issues))

    @classmethod
    def _events(
        cls,
        html: str,
        issue_date: date,
        issue_url: str,
        start: date,
        end: date,
    ) -> list[EventRecord]:
        soup = BeautifulSoup(html, "html.parser")
        lines = [
            node.get_text(" ", strip=True)
            for node in soup.select("h1, h2, h3, h4, h5, p, li")
            if node.get_text(" ", strip=True)
        ]
        events: list[EventRecord] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            metadata = " ".join(lines[index : index + 2])
            date_match = EVENT_DATE.search(metadata)
            time_match = EVENT_TIME.search(metadata)
            if date_match is None or time_match is None:
                continue

            event_date = cls._event_date(date_match.group(0), issue_date)
            if not start <= event_date < end:
                continue
            title = cls._title(lines, index)
            if not title:
                continue
            start_value, end_value = cls._times(event_date, time_match)
            description = "\n".join(lines[index + 1 : index + 5])
            location_match = LOCATION.search(description)
            location = location_match.group(1).strip() if location_match is not None else ""
            slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:80]
            source_key = (
                f"south-house:{event_date.isoformat()}:"
                f"{start_value.strftime('%H%M')}:{slug}"
            )
            if source_key in seen:
                continue
            seen.add(source_key)
            events.append(
                EventRecord(
                    title=title,
                    start=start_value,
                    end=end_value,
                    description=description,
                    summary=description.split("\n", 1)[0][:500],
                    location=location,
                    sponsor=SOURCE_NAME,
                    urls=unique([issue_url, ARCHIVE_URL]),
                    categories=("House Community", SOURCE_NAME),
                    source_keys=(source_key,),
                    sources=(SOURCE_NAME,),
                    uid_key=source_key,
                )
            )
        return events

    @staticmethod
    def _event_date(value: str, issue_date: date) -> date:
        default = datetime.combine(issue_date, time.min)
        return date_parser.parse(value, default=default, fuzzy=True).date()

    @staticmethod
    def _title(lines: list[str], index: int) -> str:
        for candidate in reversed(lines[max(0, index - 3) : index]):
            if EVENT_DATE.search(candidate) is None and EVENT_TIME.search(candidate) is None:
                return candidate[:200]
        return ""

    @staticmethod
    def _times(event_date: date, match: re.Match[str]) -> tuple[datetime, datetime]:
        default = datetime.combine(event_date, time.min)
        start_time = date_parser.parse(match.group(1), default=default).time()
        start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
        if match.group(2):
            end_time = date_parser.parse(match.group(2), default=default).time()
            end = datetime.combine(event_date, end_time, tzinfo=EASTERN)
            if end <= start:
                end += timedelta(days=1)
        else:
            end = start + timedelta(hours=1)
        return start, end
