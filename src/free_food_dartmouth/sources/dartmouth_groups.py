from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, easternize, unique

BASE_URL = "https://dartmouthgroups.dartmouth.edu"
LIST_URL = f"{BASE_URL}/mobile_ws/v17/mobile_events_list"
DETAIL_URL = f"{BASE_URL}/rsvp_boot"


@dataclass(frozen=True, slots=True)
class GroupListing:
    event_id: str
    title: str
    dates: str
    location: str
    sponsor: str
    event_url: str
    categories: tuple[str, ...]
    summary: str


class DartmouthGroupsSource:
    def __init__(
        self,
        client: HttpClient | None = None,
        workers: int = 6,
        page_size: int = 40,
    ) -> None:
        self.client = client or HttpClient()
        self.workers = workers
        self.page_size = page_size

    def scan(self, start: date, end: date) -> SourceScan:
        listings = self._listings(start, end)
        events: list[EventRecord] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._event, listing): listing.event_id for listing in listings
            }
            for future in as_completed(futures):
                event_id = futures[future]
                try:
                    event = future.result()
                    if start <= event.start_date < end:
                        events.append(event)
                except Exception as exc:
                    failures.append(f"{event_id}: {exc}")
        return SourceScan(
            "Dartmouth Groups",
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    def _listings(self, start: date, end: date) -> list[GroupListing]:
        offset = 0
        listings: list[GroupListing] = []
        while True:
            response = self.client.get(
                LIST_URL,
                params={
                    "range": offset,
                    "limit": self.page_size,
                    "filter8": start.strftime("%d %b %Y"),
                    "filter9": (end - timedelta(days=1)).strftime("%d %b %Y"),
                    "order": "",
                    "search_word": "",
                },
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("event listing did not return a JSON list")
            page_listings: list[GroupListing] = []
            total = 0
            for item in payload:
                if not isinstance(item, dict):
                    continue
                total = max(total, self._integer(item.get("counter")))
                fields = self._fields(item)
                event_id = fields.get("eventId", "")
                if event_id:
                    tags = clean_html(fields.get("eventTags", ""))
                    categories = unique(
                        [
                            fields.get("eventCategory", ""),
                            *tags.splitlines(),
                        ]
                    )
                    summary = "\n".join(
                        unique(
                            [
                                fields.get("eventPhotoDescription", ""),
                                fields.get("eventFlyerDescription", ""),
                            ]
                        )
                    )
                    page_listings.append(
                        GroupListing(
                            event_id=event_id,
                            title=clean_html(fields.get("eventName", "")),
                            dates=fields.get("eventDates", ""),
                            location=clean_html(fields.get("eventLocation", "")),
                            sponsor=clean_html(fields.get("clubName", "")),
                            event_url=fields.get("eventUrl", ""),
                            categories=categories,
                            summary=clean_html(summary),
                        )
                    )
            listings.extend(page_listings)
            offset += self.page_size
            if not page_listings or offset >= total:
                break
        return list({listing.event_id: listing for listing in listings}.values())

    def _event(self, listing: GroupListing) -> EventRecord:
        event_id = listing.event_id
        detail_url = (
            urljoin(BASE_URL, listing.event_url)
            if listing.event_url
            else (f"{DETAIL_URL}?id={event_id}")
        )
        response = self.client.get(detail_url)
        soup = BeautifulSoup(response.text, "html.parser")
        data = self._json_ld(soup)
        details = self._card(soup, "Details")
        if data:
            start = self._date_value(data.get("startDate"))
            raw_end = data.get("endDate")
            if raw_end:
                end = self._date_value(raw_end)
            elif isinstance(start, datetime):
                end = start + timedelta(hours=1)
            else:
                end = start + timedelta(days=1)
            title = clean_html(str(data.get("name", ""))) or listing.title
            description = (
                self._description(details)
                or clean_html(str(data.get("description", "")))
                or listing.summary
            )
            summary = clean_html(str(data.get("description", ""))) or listing.summary
            location = self._location(data.get("location")) or listing.location
            sponsor = self._sponsor(self._card(soup, "Hosted By")) or listing.sponsor
        else:
            start, end = self._listing_times(listing.dates)
            title = listing.title
            description = self._external_description(soup) or listing.summary
            summary = listing.summary or description[:500]
            location = listing.location
            sponsor = listing.sponsor
        if not title:
            raise ValueError("missing event title")

        categories = unique(
            [
                *listing.categories,
                *[
                    anchor.get_text(" ", strip=True)
                    for anchor in soup.select(
                        'main a[href*="event_type="], main a[href*="topic_tags="]'
                    )
                ],
            ]
        )
        urls = [detail_url]
        final_url = str(response.url)
        if (
            final_url.startswith(("http://", "https://"))
            and urlparse(final_url).netloc != urlparse(detail_url).netloc
        ):
            urls.append(final_url)
        if details is not None:
            for anchor in details.select("a[href]"):
                href = urljoin(BASE_URL, str(anchor.get("href", "")))
                if href.startswith(("http://", "https://")) and "/upload/" not in href:
                    urls.append(href)
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=summary,
            location=location,
            sponsor=sponsor,
            urls=unique(urls),
            categories=categories,
            source_keys=(f"dartmouth-groups:{event_id}",),
            sources=("Dartmouth Groups",),
            uid_key=f"dartmouth-groups:{event_id}",
        )

    @staticmethod
    def _fields(item: dict[str, Any]) -> dict[str, str]:
        names = [name for name in str(item.get("fields", "")).split(",") if name]
        return {name: str(item.get(f"p{index}", "") or "") for index, name in enumerate(names)}

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(str(value))
        except ValueError:
            return 0

    @staticmethod
    def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not isinstance(script, Tag) or not script.string:
                continue
            raw = script.string
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', "", raw))
            if isinstance(parsed, dict) and parsed.get("@type") == "Event":
                return parsed
        return {}

    @staticmethod
    def _date_value(value: object) -> date | datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError("missing event date")
        parsed = date_parser.isoparse(text)
        if len(text) <= 10:
            return parsed.date()
        return easternize(parsed)

    @staticmethod
    def _listing_times(value: str) -> tuple[date | datetime, date | datetime]:
        lines = clean_html(value).splitlines()
        if not lines:
            raise ValueError("missing event date")
        event_date = date_parser.parse(lines[0], fuzzy=True).date()
        time_text = " ".join(lines[1:]).strip()
        if not time_text or "all day" in time_text.casefold():
            return event_date, event_date + timedelta(days=1)
        time_text = re.sub(r"\b(?:EDT|EST)\b", "", time_text).strip()
        pieces = re.split(r"\s+(?:-|\u2013|\u2014|to)\s+", time_text, maxsplit=1)
        default = datetime.combine(event_date, datetime.min.time())
        start_time = date_parser.parse(pieces[0], default=default).time()
        end_time = (
            date_parser.parse(pieces[1], default=default).time()
            if len(pieces) == 2
            else (datetime.combine(event_date, start_time) + timedelta(hours=1)).time()
        )
        start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
        end = datetime.combine(event_date, end_time, tzinfo=EASTERN)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def _card(soup: BeautifulSoup, heading_text: str) -> Tag | None:
        for heading in soup.select("h2"):
            if heading.get_text(" ", strip=True) == heading_text:
                card = heading.find_parent("div", class_="card-block")
                return card if isinstance(card, Tag) else None
        return None

    @staticmethod
    def _description(card: Tag | None) -> str:
        if card is None:
            return ""
        copy = BeautifulSoup(str(card), "html.parser")
        for node in copy.select(".card-block__title, .text-center, button, script, style"):
            node.decompose()
        return clean_html(str(copy))

    @staticmethod
    def _external_description(soup: BeautifulSoup) -> str:
        form_description = soup.select_one(".cBGGJ")
        if form_description is not None:
            return clean_html(str(form_description))
        for script in soup.find_all("script"):
            raw = script.string if isinstance(script, Tag) else None
            if not raw or "FB_PUBLIC_LOAD_DATA_" not in raw:
                continue
            match = re.search(
                r"var\s+FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*\]);\s*$",
                raw,
                re.DOTALL,
            )
            if match is None:
                continue
            try:
                form_data = json.loads(match.group(1))
                description = form_data[1][0]
            except (IndexError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(description, str) and description.strip():
                return clean_html(description)
        for selector in ('meta[name="description"]', 'meta[property="og:description"]'):
            meta = soup.select_one(selector)
            if meta is not None:
                content = clean_html(str(meta.get("content", "")))
                if content:
                    return content
        return ""

    @staticmethod
    def _location(value: object) -> str:
        if not isinstance(value, dict):
            return clean_html(str(value or ""))
        name = clean_html(str(value.get("name", "")))
        raw_address = value.get("address", "")
        if isinstance(raw_address, dict):
            address = ", ".join(
                unique(
                    [
                        str(raw_address.get("streetAddress", "")),
                        str(raw_address.get("addressLocality", "")),
                        str(raw_address.get("addressRegion", "")),
                        str(raw_address.get("postalCode", "")),
                    ]
                )
            )
        else:
            address = clean_html(str(raw_address))
        if address and address != name:
            return f"{name}, {address}" if name else address
        return name

    @staticmethod
    def _sponsor(card: Tag | None) -> str:
        if card is None:
            return ""
        host = card.find("strong")
        host_text = host.get_text(" ", strip=True) if host else ""
        text = card.get_text(" ", strip=True)
        cohost = ""
        if "Co-hosted with:" in text:
            cohost = (
                text.split("Co-hosted with:", 1)[1].split("Contact the organizers", 1)[0].strip()
            )
        return " / ".join(unique((host_text, cohost)))
