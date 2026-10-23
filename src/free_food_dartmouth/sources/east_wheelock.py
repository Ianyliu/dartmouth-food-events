"""East Wheelock House events from its public Google Calendar.

The house's standalone site (ewhousedartmouth.com) no longer resolves, so
this source pins the calendar ID of the calendar embedded on the house's
Dartmouth-hosted calendar page instead of deriving it from a homepage
scrape.
"""

from __future__ import annotations

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.sources.public_google_calendar import (
    PublicGoogleCalendarConfig,
    PublicGoogleCalendarSource,
)

CALENDAR_ID = "3mb4ulgbkvdpt5f3u60riaga98@group.calendar.google.com"
CALENDAR_PAGE_URL = "https://sites.dartmouth.edu/ew/calendar/"
SOURCE_NAME = "East Wheelock House"


class EastWheelockSource(PublicGoogleCalendarSource):
    """East Wheelock House events from its public Google Calendar."""

    def __init__(self, client: HttpClient | None = None):
        super().__init__(
            PublicGoogleCalendarConfig(
                name=SOURCE_NAME,
                calendar_id=CALENDAR_ID,
                key_prefix="east-wheelock",
                page_url=CALENDAR_PAGE_URL,
            ),
            client,
        )
