# Draft: Which event sources should stay on GitHub sync, and which should move to Muse?

Status: **Draft proposal only — no sync code is changed by this document.**
Date: 2026-10-27. Evidence is from the Free Food @Dartmouth calendar and the
daily Slack free-food watch, Oct 22–27, 2026.

## Summary

| Source | Recommendation | Why, in one line |
|---|---|---|
| South House Mailchimp newsletters | **Keep on GitHub** (watch 1–2 more issues) | PR #5 fixed the parser misalignment; Oct 26–27 replacements are correct |
| Dartmouth Groups ICS feeds (all houses) | **Keep on GitHub** | Titles/starts usually right; Muse cross-checks ends/locations |
| Dartmouth main events, GSC (general) | **Keep on GitHub** | Structured sources; no systematic misalignment found |
| East Wheelock structured Google Calendar | **Keep on GitHub** | Field-separated title/time/location; Oct 27 Scottish Tea matched exactly |
| Slack-origin events that duplicate a sync source (e.g. Trick-or-Treat, Fall Mixer) | **Move ownership to Muse, or exclude from sync** | Two systems fight over the same event; manual fixes are reverted/re-created |
| GSC events whose source page has no location | **Fix sync first, or move to Muse** | Sync overwrites a manually added location with blank on every run |
| Allen House Instagram (@allen_house_dartmouth) and other social announcements | **Move to Muse** | No reliable GitHub parser for free-text/image posts |
| School House Airtable calendar | **Move to Muse** | No live iCal URL from the shared view, so the GitHub feed cannot stay fresh |

## Evidence

### Keep: South House Mailchimp — fixed by PR #5
- Before the fix, the parser shifted every entry by one: the calendar title was
  the previous event's "Where:" line, the description was the next event's body,
  and the time was wrong by about 1–2 hours or on the wrong date (e.g. the
  Oct 26 Risam dinner was listed as Oct 26, 6:30–7:30pm, Fayerweather, with a
  Paint by Numbers description; the newsletter says Oct 26, 5:30–6:30pm,
  5 Sanborn Road).
- PR #5 (merged Oct 25) fixed the block misalignment, am/pm propagation for
  ranges like "5:30-6:30pm", matcher gaps, and dedupe (prefer the later end,
  reject the Groups ICS location placeholder).
- The merge-triggered sync then created correct replacements, verified live
  Oct 26–27: Risam dinner Oct 26, 5:30–6:30pm, 5 Sanborn Road; Cube-o-ween
  Oct 31, 10pm–12am, The Cube; Chuck Sams dinner Nov 2, 5:30–6:30pm,
  7 School Street. The old garbled copies are now cancelled, not live.
- Open question: does the fix hold for the next newsletter (Week 7)? Keep the
  daily Muse house-event check as the safety net until it does.

### Keep, with Muse cross-check: Dartmouth Groups ICS
- Titles and start times are usually right, but end times can be truncated and
  locations often show as "Private Location" where the newsletter or house page
  gives a real room. Example: Doing Well by Doing Good, Oct 28 — Groups said
  5:30–6:30pm, Private Location; the South House newsletter says
  5:30–7:30pm, Fayerweather Great Hall. The Muse correction (location +
  7:30pm end) held on Oct 27, unlike the Fall Mixer case below.

### Move / exclude: Slack duplicates — Trick-or-Treat and Fall Mixer
- Trick-or-Treat on Webster Avenue, Oct 29, 5–7pm: the sync has re-created its
  own thin copy 5 times (Oct 24–27), each time with a "(Required - enter your
  event description here)" placeholder, while the fuller Slack-sourced copy
  (candy, cider, cocoa, music, official page and Canva links merged) is kept
  and the sync copy is deleted. This is not a parser bug; it is two owners
  for one event.
- Guarini / Geisel Fall Mixer, Oct 26, 5:30–7:30pm: the GSC source page has no
  location, so the sync reverted the manually added DOC House location
  (Dartmouth Outing Club, 9 Hilton Field Road) to blank on every run — three
  re-applications by Oct 27.
- Proposed fix, in order of preference: (1) sync preserves a non-blank manual
  location and recognises a fuller existing copy instead of re-creating one;
  (2) if that is not feasible, exclude these titles/event IDs from sync and
  let Muse own them.

### Move to Muse: Allen House Instagram
- Instagram posts are free text and images, with no structured title/time/
  location fields for the sync to parse. The weekly coverage audit already
  treats Allen Instagram as a special-attention source, not a sync source.
  Muse (Instagram connector / browser check) is the better owner, with the
  weekly audit as the backstop.

### Move to Muse: School House Airtable
- The shared Airtable view exposes no live iCal subscription URL — only a CSV
  download or a one-time .ics download — so a GitHub feed built on it cannot
  stay fresh automatically. A periodic Muse check of the School House calendar
  or Airtable export is more honest than a stale automated feed.

## What moving a source to Muse actually means
- The daily Muse watch already covers: Slack #general/#random, house events
  in the next 2–3 days against their original source, re-applying corrections
  the sync reverts, and RSVP reminders. That coverage is what makes the
  "move to Muse" options above workable for house and Slack events.
- It does **not** yet cover Allen Instagram daily or School House Airtable on
  a daily cadence — those are weekly-audit items today. If Allen or School
  House moves to Muse, add an explicit daily/weekly Muse check for that source
  to the watch, rather than assuming the existing watch already covers it.
- Stopping GitHub sync for a source means its events will not appear unless
  Muse adds them. Do not disable a source until the Muse coverage for it is
  in place.

## Proposed next steps (for review, not yet implemented)
1. Confirm the keep/move table above, source by source.
2. Implement the sync "preserve manual location / recognise fuller copy" rule,
   or, failing that, the exclusion list for Slack-duplicate titles.
3. Add explicit Muse coverage for Allen Instagram and School House Airtable
   if those two move to Muse.
4. Re-check South House after the Week 7 newsletter; if it holds, remove the
   extra Muse safety-net wording for that source.
