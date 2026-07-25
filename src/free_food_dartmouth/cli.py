from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from free_food_dartmouth.dedupe import deduplicate
from free_food_dartmouth.google_calendar import GoogleCalendarSync, SyncResult
from free_food_dartmouth.ics import write_outputs
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.sources.dartmouth import DartmouthSource
from free_food_dartmouth.sources.dartmouth_groups import DartmouthGroupsSource
from free_food_dartmouth.sources.geisel import GeiselSource
from free_food_dartmouth.sources.guarini import GuariniSource
from free_food_dartmouth.utils import EASTERN

DEFAULT_WINDOW_DAYS = 21


class EventSource(Protocol):
    def scan(self, start: date, end: date) -> SourceScan: ...


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="free-food-dartmouth")
    commands = root.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="Fetch, filter, and synchronize the rolling calendar")
    sync.add_argument("--date", type=date.fromisoformat, help="Eastern start date (YYYY-MM-DD)")
    sync.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    sync.add_argument("--dry-run", action="store_true", help="Fetch and report without writes")
    sync.add_argument(
        "--no-google", action="store_true", help="Skip Google Calendar reconciliation"
    )
    sync.add_argument(
        "--google-best-effort",
        action="store_true",
        help="Keep publishing ICS if Google Calendar is temporarily unavailable",
    )
    sync.add_argument("--output-dir", type=Path, default=Path("docs"), help=argparse.SUPPRESS)
    return root


def _matched(events: tuple[EventRecord, ...]) -> list[EventRecord]:
    matched: list[EventRecord] = []
    for event in events:
        reasons = match_event(event)
        if reasons:
            matched.append(event.with_match_reasons(reasons))
    return matched


def _safe_scan(source: EventSource, name: str, start: date, end: date) -> SourceScan:
    try:
        return source.scan(start, end)
    except Exception as exc:
        return SourceScan(name, (), complete=False, errors=(str(exc),))


def sync(args: argparse.Namespace) -> int:
    if args.window_days < 1:
        raise ValueError("--window-days must be positive")
    start: date = args.date or datetime.now(EASTERN).date()
    end = start + timedelta(days=args.window_days)
    print(f"Scanning {start.isoformat()} through {(end - timedelta(days=1)).isoformat()} (Eastern)")

    scans = [
        _safe_scan(DartmouthSource(), "Dartmouth", start, end),
        _safe_scan(GeiselSource(), "Geisel", start, end),
        _safe_scan(DartmouthGroupsSource(), "Dartmouth Groups", start, end),
        _safe_scan(GuariniSource(), "Guarini", start, end),
    ]
    for scan in scans:
        if not scan.complete:
            details = "; ".join(scan.errors[:3]) or "unknown source error"
            print(
                f"warning: {scan.source} scan incomplete ({len(scan.errors)} error(s)): {details}",
                file=sys.stderr,
            )
    matched = [event for scan in scans for event in _matched(scan.events)]
    events = deduplicate(matched)
    found = ", ".join(f"{len(scan.events)} {scan.source}" for scan in scans)
    scan_complete = all(scan.complete for scan in scans)
    print(f"Found {found}; {len(matched)} matched and {len(events)} remain after deduplication")

    result = SyncResult(events)
    if not args.no_google:
        try:
            result = GoogleCalendarSync.from_environment().reconcile(
                events,
                start,
                end,
                dry_run=args.dry_run,
                scan_complete=scan_complete,
            )
            print(
                "Google actions: "
                f"{result.inserted} insert, {result.updated} update, "
                f"{result.unchanged} unchanged, {result.marked_tentative} tentative, "
                f"{result.deleted} delete"
            )
        except Exception as exc:
            if not args.google_best_effort:
                raise
            if not scan_complete:
                raise RuntimeError(
                    "Google Calendar failed during an incomplete source scan; "
                    "refusing to replace the public feed with partial data"
                ) from exc
            print(
                f"warning: Google Calendar sync failed ({exc}); "
                "continuing with the Outlook-compatible ICS feed",
                file=sys.stderr,
            )
    elif not scan_complete:
        print(
            "warning: generated output contains only successfully fetched events because "
            "--no-google cannot recover entries from an earlier complete scan",
            file=sys.stderr,
        )

    if args.dry_run:
        print(
            json.dumps(
                [
                    {
                        "title": event.title,
                        "start": event.start.isoformat(),
                        "sources": event.sources,
                        "reasons": event.match_reasons,
                        "urls": event.urls,
                    }
                    for event in result.active_events
                ],
                indent=2,
            )
        )
    else:
        generated_at = datetime.now(EASTERN)
        write_outputs(args.output_dir, result.active_events, generated_at)
        print(f"Wrote {len(result.active_events)} events to {args.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "sync":
            return sync(args)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
