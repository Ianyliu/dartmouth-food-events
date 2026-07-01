# Free Food @Dartmouth

A rolling three-week calendar of Dartmouth College, Geisel School of Medicine, and
Dartmouth Groups events that are likely to offer food. The project checks both the structured
“Free Food” category and contextual wording in event titles, summaries, and descriptions.

The generated feed is published at:

<https://ianyliu.github.io/dartmouth-food-events/free-food-dartmouth.ics>

Food availability is inferred from public listings. Always verify the original event page.

## How it works

1. Dartmouth events are enumerated through the public date-range search endpoint. Each event's
   JSON-LD, categories, webpage description, and per-event ICS file are parsed.
2. Geisel events are enumerated from the weekly calendar views and enriched from their detail pages.
3. Dartmouth Groups events are enumerated from its public date-range JSON endpoint and enriched
   from detail-page JSON-LD, descriptions, food notes, hosts, tags, and links.
4. A context-aware matcher selects likely food events and rejects common false positives.
5. Overlapping listings are merged using source IDs, external URLs, start
   times, and normalized title similarity.
6. Managed Google Calendar events are updated in place. A missing event is marked
   `[Possibly canceled]` after one complete scan and deleted after a second.
7. `docs/free-food-dartmouth.ics` is regenerated and deployed with GitHub Pages.

## Local usage

This project requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m free_food_dartmouth sync --dry-run --no-google
```

Available options:

```text
--date YYYY-MM-DD   Override the Eastern start date
--window-days N     Change the rolling window (default: 21)
--dry-run           Fetch and report without writes
--no-google         Skip Google Calendar reconciliation
```

## Google Calendar setup

Do not commit or paste service-account credentials into issues, logs, or chat.

1. In Google Calendar, create a calendar named **Free Food @Dartmouth** and set its timezone
   to `America/New_York`.
2. Create or select a Google Cloud project and enable the **Google Calendar API**.
3. Create a dedicated service account and download a JSON key.
4. Share the new calendar with the service-account email and grant **Make changes to events**.
5. In the GitHub repository, open **Settings → Secrets and variables → Actions** and add:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete JSON key
   - `GOOGLE_CALENDAR_ID`: the calendar ID from Google Calendar's integration settings
6. Run **Actions → Sync calendar → Run workflow** once and confirm the resulting events.

The service-account JSON is read directly from the encrypted secret and is never written to disk.

## Automation

- **CI** runs Ruff, mypy, and pytest on pushes and pull requests.
- **Sync calendar** is triggered at 10:00 and 11:00 UTC. A timezone guard allows only the trigger
  corresponding to 6:00 AM Eastern to proceed, handling daylight-saving changes.
- **Deploy calendar feed** publishes `docs/` through GitHub Pages.

GitHub's scheduled workflows can start later than their nominal time during periods of high load.

## License

[MIT](LICENSE)
