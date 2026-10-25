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
    # The first time in a range may carry no am/pm suffix ("5:30-6:30pm",
    # "8-10:30pm"); _times() propagates the suffix from the second time.
    # A match with no suffix on either time is rejected by the caller.
    r"\b(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)"
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

        def _append(
            title: str,
            start_value: datetime,
            end_value: datetime,
            description: str,
            location: str,
            event_date: date,
        ) -> None:
            slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:80]
            source_key = (
                f"south-house:{event_date.isoformat()}:{start_value.strftime('%H%M')}:{slug}"
            )
            if source_key in seen:
                return
            seen.add(source_key)
            events.append(
                EventRecord(
                    title=title,
                    start=start_value,
                    end=end_value,
                    description=description,
                    summary=description.split("\n", 1)[0][:500] if description else title[:500],
                    location=location,
                    sponsor=SOURCE_NAME,
                    urls=unique([issue_url, ARCHIVE_URL]),
                    categories=("House Community", SOURCE_NAME),
                    source_keys=(source_key,),
                    sources=(SOURCE_NAME,),
                    uid_key=source_key,
                )
            )

        # Mailchimp-style blocks ("Where:" / "When:" lines) are parsed
        # block-wise first. The old line-triggered logic below skips
        # "When:" lines, so a Mailchimp event is never also produced
        # with its title shifted to the previous event's "Where:" line
        # and its description taken from the next event.
        for parsed in cls._mailchimp_events(lines, issue_date, start, end):
            _append(*parsed)

        for index, line in enumerate(lines):
            if line.strip().lower().startswith("when:"):
                continue
            date_match = EVENT_DATE.search(line)
            if date_match is None:
                continue
            metadata = " ".join(lines[index : index + 2])
            time_match = cls._find_time(metadata)
            if time_match is None:
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
            _append(title, start_value, end_value, description, location, event_date)
        return events

    @staticmethod
    def _is_section_header(line: str) -> bool:
        stripped = line.strip()
        return (
            bool(stripped)
            and stripped.upper() == stripped
            and any(char.isalpha() for char in stripped)
            and len(stripped) <= 60
        )

    @staticmethod
    def _is_location_line(line: str) -> bool:
        stripped = line.strip().lower()
        return stripped.startswith("where:") or stripped.startswith("location:")

    @staticmethod
    def _has_meridiem(text: str) -> bool:
        lowered = text.casefold()
        return "a.m" in lowered or "p.m" in lowered or "am" in lowered or "pm" in lowered

    @classmethod
    def _find_time(cls, text: str) -> re.Match[str] | None:
        # With the first am/pm suffix optional, EVENT_TIME can match
        # bare numbers (a day of month, a year fragment) first; take
        # the first match that actually carries an am/pm suffix.
        for match in EVENT_TIME.finditer(text):
            if cls._has_meridiem(match.group(0)):
                return match
        return None

    @classmethod
    def _mailchimp_events(
        cls,
        lines: list[str],
        issue_date: date,
        start: date,
        end: date,
    ) -> list[tuple[str, datetime, datetime, str, str, date]]:
        """Parse Mailchimp blocks of the form Title / Description / Where / When.

        The block for a "When:" line runs from just after the previous
        "When:" line (or, for the first such line, the preceding few
        lines) to that "When:" line. The title is the first line in the
        block that is not a section header, a "Where:"/"Location:" line,
        or a line carrying a date or time; a title ending in ":" takes
        the following line as a continuation (e.g. Chuck Sams).
        """
        when_indices = [
            index for index, line in enumerate(lines) if line.strip().lower().startswith("when:")
        ]
        parsed: list[tuple[str, datetime, datetime, str, str, date]] = []
        previous_when: int | None = None
        for index in when_indices:
            when_line = lines[index]
            date_match = EVENT_DATE.search(when_line)
            time_match = cls._find_time(when_line)
            if date_match is None or time_match is None:
                previous_when = index
                continue
            if not cls._has_meridiem(time_match.group(0)):
                previous_when = index
                continue
            event_date = cls._event_date(date_match.group(0), issue_date)
            if not start <= event_date < end:
                previous_when = index
                continue
            block_start = previous_when + 1 if previous_when is not None else max(0, index - 6)
            block = lines[block_start:index]
            # Locate the "Where:" line (immediately before "When:" in
            # practice) and the title within the block.
            where_pos: int | None = None
            for pos in range(len(block) - 1, -1, -1):
                if cls._is_location_line(block[pos]):
                    where_pos = pos
                    break
            location = ""
            if where_pos is not None:
                location = re.sub(
                    r"(?i)^\s*(?:where|location)\s*:\s*", "", block[where_pos]
                ).strip()
            title_pos: int | None = None
            for pos, candidate in enumerate(block):
                if cls._is_section_header(candidate):
                    continue
                if cls._is_location_line(candidate):
                    continue
                if EVENT_DATE.search(candidate) is not None:
                    continue
                if EVENT_TIME.search(candidate) is not None:
                    continue
                title_pos = pos
                break
            if title_pos is None:
                previous_when = index
                continue
            title = block[title_pos]
            title_end = title_pos + 1
            if title.rstrip().endswith(":") and title_end < len(block):
                following = block[title_end]
                if (
                    not cls._is_location_line(following)
                    and EVENT_DATE.search(following) is None
                    and EVENT_TIME.search(following) is None
                ):
                    title = f"{title} {following}"
                    title_end += 1
            desc_end = where_pos if where_pos is not None else len(block)
            description_lines = block[title_end:desc_end]
            description = "\n".join(description_lines)
            start_value, end_value = cls._times(event_date, time_match)
            parsed.append((title[:200], start_value, end_value, description, location, event_date))
            previous_when = index
        return parsed

    @staticmethod
    def _event_date(value: str, issue_date: date) -> date:
        default = datetime.combine(issue_date, time.min)
        return date_parser.parse(value, default=default, fuzzy=True).date()

    @staticmethod
    def _title(lines: list[str], index: int) -> str:
        for candidate in reversed(lines[max(0, index - 3) : index]):
            if SouthHouseSource._is_location_line(candidate):
                continue
            if EVENT_DATE.search(candidate) is None and EVENT_TIME.search(candidate) is None:
                return candidate[:200]
        return ""

    @staticmethod
    def _times(event_date: date, match: re.Match[str]) -> tuple[datetime, datetime]:
        default = datetime.combine(event_date, time.min)
        start_raw = match.group(1).strip()
        end_raw = match.group(2).strip() if match.group(2) else None
        # Propagate an am/pm suffix from the end of a range to a bare
        # start ("5:30-6:30pm" starts at 5:30pm, not 6:30pm).
        if end_raw is not None and not SouthHouseSource._has_meridiem(start_raw):
            suffix = re.search(r"a\.?m\.?|p\.?m\.?", end_raw, re.IGNORECASE)
            if suffix is not None:
                start_raw = f"{start_raw} {suffix.group(0)}"
        start_time = date_parser.parse(start_raw, default=default).time()
        start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
        if end_raw:
            end_time = date_parser.parse(end_raw, default=default).time()
            end = datetime.combine(event_date, end_time, tzinfo=EASTERN)
            if end <= start:
                end += timedelta(days=1)
        else:
            end = start + timedelta(hours=1)
        return start, end
