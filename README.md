# BSB Calendar Feed

Auto-updating ICS calendar for the **Bennetts British Superbike Championship** — all three races per round **plus practice and qualifying**.

## Subscribe

```
https://raw.githubusercontent.com/Creative-fw/bsb-calendar/main/BSB.ics
```

Subscribe (don't import) in Apple Calendar / Google Calendar. Calendar name: **BSB**.

## What you get

- **Races** (flagged 🏁, 15-min alarm): Race 1/2/3 every round, 45-min blocks.
- **Practice / qualifying / warm up** (silent): FP1–3, Pre-Qualifying, Q1/Q2 (20-min blocks), Warm Up.

## How it works

- `bsb_sync.py` runs daily (05:45 UTC) via GitHub Actions and commits `BSB.ics` if changed.
- The calendar page provides round number, date span and venue; each round page carries the full BSB-class timetable, parsed with class-anchored regexes. Weekday rows map to dates inside each round's span.
- All listed times are UK time (BST/GMT) — including away rounds — converted via zoneinfo (DST-aware, handles the October GMT switch).
- Sponsor prefixes are stripped to canonical session names. `Gates Open` and TBC rows are skipped; TBC sessions appear automatically once published.
- Official pre-season tests are excluded. An abort guard refuses to overwrite the feed if fewer than 6 rounds parse.
