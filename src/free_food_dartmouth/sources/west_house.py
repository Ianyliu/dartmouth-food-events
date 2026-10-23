"""West House events from its public Google Calendar.

West House's Dartmouth Groups feed is currently empty. This source reads
the separate "West House events" Google Calendar linked from the
Westletter and embedded on the house's calendar page. The feed is public
but currently carries no Fall 2026 events; a successful fetch with no
events in the window is a complete, empty scan, not a failure.
"""

from __future__ import annotations

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.sources.public_google_calendar import (
    PublicGoogleCalendarConfig,
    PublicGoogleCalendarSource,
)

CALENDAR_ID = "r78s4hhirap90na39ol3e56nq4@group.calendar.google.com"
CALENDAR_PAGE_URL = "https://sites.dartmouth.edu/west-house/house-calendar/"
SOURCE_NAME = "West House"


class WestHouseSource(PublicGoogleCalendarSource):
    """West House events from its public Google Calendar."""

    def __init__(self, client: HttpClient | None = None):
        super().__init__(
            PublicGoogleCalendarConfig(
                name=SOURCE_NAME,
                calendar_id=CALENDAR_ID,
                key_prefix="west-house",
                page_url=CALENDAR_PAGE_URL,
            ),
            client,
        )
