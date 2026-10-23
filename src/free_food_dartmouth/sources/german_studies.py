"""German Studies news announcements mentioning Allen House or West House.

The department news page is a news list, not an events feed: it mixes
prospective announcements with retrospective recaps, and event dates
appear only in free text (article titles and bodies). This source
therefore applies strict guards and never invents a date:

- the article must name Allen House or West House;
- the title or body must state an explicit event date (month and day)
  together with a time range (or a single start time);
- the event date must fall inside the scan window, which also excludes
  retrospective recaps (their event dates are in the past);
- an item whose body reads as a recap of an event before its publication
  date is excluded even if a date is present;
- bare time ranges without am/pm markers are read as afternoon/evening
  times: department social announcements use bare ranges for evening
  events, and a morning event is expected to say "morning" or "am". This
  heuristic is documented here because it is the one inference this
  source makes; items with no time at all are skipped, not dated.

An item that fails any guard is skipped, not failed: a news item without
a usable event date is not a source error. A listing page that yields no
article links at all is treated as a structural failure, so a markup
change fails loudly instead of silently returning nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html

LIST_URL = "https://german.dartmouth.edu/news-events/news"
SOURCE_NAME = "German Studies"
MAX_PAGES = 5
LOOKBACK_DAYS = 120

HOST_PATTERN = re.compile(r"\b(Allen|West) House\b")
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_ALTERNATION = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERN = re.compile(
    r"\b(" + _MONTH_ALTERNATION + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
PUB_DATE_PATTERN = re.compile(
    r"\b(" + _MONTH_ALTERNATION + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
_TIME_TOKEN = r"(\d{1,2}(?::\d{2})?\s*(?:[aApP]\.?[mM]\.?)?)"
TIME_RANGE_PATTERN = re.compile(
    _TIME_TOKEN + r"\s*(?:-|‑|—|to)\s*" + _TIME_TOKEN,  # noqa: RUF001
    re.IGNORECASE,
)
TIME_SINGLE_PATTERN = re.compile(r"\b(?:at|from)\s+" + _TIME_TOKEN, re.IGNORECASE)
ARTICLE_URL_PATTERN = re.compile(r"^/news/\d{4}/\d{2}/[^/]+/?$")
RECAP_PATTERN = re.compile(
    r"\b(turned out|came out|was held|took place|thank you to everyone who came)\b",
    re.IGNORECASE,
)
CONTEXT_PATTERN = re.compile(r"\b(morning|afternoon|evening|night)\b", re.IGNORECASE)
LOCATION_PATTERN = re.compile(
    r"\bat\s+((?:[A-Z][\w&'’.\-]+)(?:\s+[A-Z][\w&'’.\-]+)*)"  # noqa: RUF001
)


@dataclass(frozen=True, slots=True)
class _ListingItem:
    url: str
    title: str
    pub_date: date | None


def _parse_pub_date(text: str) -> date | None:
    match = PUB_DATE_PATTERN.search(text)
    if match is None:
        return None
    month = MONTHS[match.group(1).lower().rstrip(".")]
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _parse_time_token(token: str, *, default_pm: bool) -> int | None:
    """Parse a 12-hour token to minutes since midnight, or None."""
    cleaned = token.strip().lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?", cleaned)
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    marker = match.group(3)
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if marker == "am":
        hour_24 = 0 if hour == 12 else hour
    elif marker == "pm":
        hour_24 = 12 if hour == 12 else hour + 12
    elif hour == 12:
        hour_24 = 12
    elif default_pm:
        hour_24 = hour + 12
    else:
        hour_24 = hour
    return hour_24 * 60 + minute


def _resolve_times(start_token: str, end_token: str | None, context: str) -> tuple[int, int] | None:
    """Resolve a time range to minute offsets (end may exceed 1440)."""
    context_match = CONTEXT_PATTERN.search(context)
    default_pm = context_match is None or context_match.group(1).lower() != "morning"
    start = _parse_time_token(start_token, default_pm=default_pm)
    if start is None:
        return None
    if end_token is None:
        return start, start + 60
    end = _parse_time_token(end_token, default_pm=default_pm)
    if end is None:
        return None
    if end <= start:
        end += 12 * 60
    if end <= start:
        end = start + 60
    return start, end


def _sentence_around(text: str, start: int, end: int) -> str:
    sentence_start = 0
    for delimiter in ("\n", ". ", "! ", "? "):
        position = text.rfind(delimiter, 0, start)
        if position >= 0:
            sentence_start = max(sentence_start, position + len(delimiter))
    sentence_end = len(text)
    for delimiter in ("\n", ". ", "! ", "? "):
        position = text.find(delimiter, end)
        if position >= 0:
            sentence_end = min(sentence_end, position)
    return text[sentence_start:sentence_end]


def _extract_event(
    title: str, body: str, pub_date: date | None
) -> tuple[date, int, int, str] | None:
    """Return (event date, start minutes, end minutes, location) or None."""
    combined = f"{title}\n{body}"
    if not HOST_PATTERN.search(combined):
        return None
    date_match = DATE_PATTERN.search(combined)
    if date_match is None or pub_date is None:
        return None
    month = MONTHS[date_match.group(1).lower().rstrip(".")]
    day = int(date_match.group(2))
    try:
        event_date = date(pub_date.year, month, day)
    except ValueError:
        return None
    if (pub_date - event_date).days > 180:
        try:
            event_date = date(pub_date.year + 1, month, day)
        except ValueError:
            return None
    sentence = _sentence_around(combined, date_match.start(), date_match.end())
    time_match = TIME_RANGE_PATTERN.search(sentence)
    start_token: str | None
    end_token: str | None
    time_sentence = sentence
    if time_match is not None:
        start_token, end_token = time_match.group(1), time_match.group(2)
    else:
        single = TIME_SINGLE_PATTERN.search(sentence)
        if single is None:
            return None
        start_token, end_token = single.group(1), None
    times = _resolve_times(start_token, end_token, sentence)
    if times is None:
        return None
    start_minutes, end_minutes = times
    if RECAP_PATTERN.search(body) and event_date < pub_date:
        return None
    location = ""
    location_matches = LOCATION_PATTERN.findall(time_sentence)
    if location_matches:
        location = location_matches[-1].strip().rstrip(".,;")
    else:
        # The date may sit in the title while the venue sits in the body,
        # and the body repeats the title, so scan every dated sentence.
        for body_date_match in DATE_PATTERN.finditer(body):
            body_sentence = _sentence_around(body, body_date_match.start(), body_date_match.end())
            body_locations = LOCATION_PATTERN.findall(body_sentence)
            if body_locations:
                location = body_locations[-1].strip().rstrip(".,;")
                break
    return event_date, start_minutes, end_minutes, location


class GermanStudiesSource:
    """German Studies news announcements co-hosted with a house."""

    def __init__(self, client: HttpClient | None = None):
        self.client = client or HttpClient()

    def _listing_items(self, html: str) -> tuple[list[_ListingItem], str | None]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[_ListingItem] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link["href"])
            if not ARTICLE_URL_PATTERN.match(href):
                continue
            url = urljoin(LIST_URL, href)
            if url in seen:
                continue
            seen.add(url)
            title = link.get_text(" ", strip=True)
            pub_date: date | None = None
            node = link.parent
            for _ in range(3):
                if node is None:
                    break
                pub_date = _parse_pub_date(node.get_text(" ", strip=True))
                if pub_date is not None:
                    break
                node = node.parent
            if pub_date is None:
                url_match = re.search(r"/news/(\d{4})/(\d{2})/", href)
                if url_match is not None:
                    pub_date = date(int(url_match.group(1)), int(url_match.group(2)), 1)
            items.append(_ListingItem(url=url, title=title, pub_date=pub_date))
        next_url: str | None = None
        for link in soup.find_all("a", href=True):
            rel_value = link.get("rel")
            rel_list = rel_value if isinstance(rel_value, list) else []
            text = link.get_text(" ", strip=True).lower()
            if "next" in rel_list or text in ("next", "›", "»"):  # noqa: RUF001
                href = str(link["href"])
                if href.startswith("/news-events/news"):
                    next_url = urljoin(LIST_URL, href)
                    break
        return items, next_url

    def scan(self, start: date, end: date) -> SourceScan:
        failures: list[str] = []
        items: list[_ListingItem] = []
        url: str | None = LIST_URL
        pages = 0
        while url is not None and pages < MAX_PAGES:
            response = self.client.get(url)
            page_items, next_url = self._listing_items(response.text)
            if pages == 0 and not page_items:
                raise ValueError("no articles found on the German Studies news page")
            items.extend(page_items)
            pages += 1
            oldest = min(
                (item.pub_date for item in page_items if item.pub_date is not None),
                default=None,
            )
            if next_url is None or oldest is None:
                break
            if oldest < start - timedelta(days=LOOKBACK_DAYS):
                break
            url = next_url
        events: list[EventRecord] = []
        cutoff = start - timedelta(days=LOOKBACK_DAYS)
        for item in items:
            if item.pub_date is None or item.pub_date < cutoff or item.pub_date >= end:
                continue
            try:
                detail = self.client.get(item.url)
            except Exception as exc:
                failures.append(f"{item.url}: {exc}")
                continue
            detail_soup = BeautifulSoup(detail.text, "html.parser")
            heading = detail_soup.find("h1")
            article_title = heading.get_text(" ", strip=True) if heading else item.title
            if " | " in article_title:
                article_title = article_title.split(" | ", 1)[0]
            main = detail_soup.find("main") or detail_soup.find("article") or detail_soup
            body = clean_html(str(main))
            extracted = _extract_event(article_title, body, item.pub_date)
            if extracted is None:
                continue
            event_date, start_minutes, end_minutes, location = extracted
            if not (start <= event_date < end):
                continue
            day_start = datetime.combine(event_date, time.min, tzinfo=EASTERN)
            event_start = day_start + timedelta(minutes=start_minutes)
            event_end = day_start + timedelta(minutes=end_minutes)
            slug = item.url.rstrip("/").rsplit("/", 1)[-1]
            source_key = f"german-studies:{slug}"
            events.append(
                EventRecord(
                    title=article_title,
                    start=event_start,
                    end=event_end,
                    description=body,
                    summary=body.split("\n", 1)[0][:500],
                    location=location,
                    sponsor=SOURCE_NAME,
                    urls=(item.url,),
                    categories=("Department News", SOURCE_NAME),
                    source_keys=(source_key,),
                    sources=(SOURCE_NAME,),
                    uid_key=source_key,
                )
            )
        events.sort(key=lambda event: (str(event.start), event.title.casefold()))
        return SourceScan(
            SOURCE_NAME,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )
