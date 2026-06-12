#!/usr/bin/env python3
"""
British Superbike (BSB) -> auto-updating ICS feed.

Source: britishsuperbike.com (server-rendered HTML; no public API).
- /calendar cards give round number, date span, venue and slug
- each round page carries the full BSB-class timetable inline
  (day <strong> + session <span> + <span class="time">HH:MM BST</span>)

- All times are listed in UK time (BST/GMT) -> Europe/London via zoneinfo,
  including away rounds (Assen is listed in UK broadcast time)
- Weekday rows map to dates inside the round's date span
- Races (Race N) are flagged + 15-min alarm; practice, qualifying and
  warm up are silent
- Sponsor prefixes are stripped to canonical session names
- 'Gates Open' and TBC rows are skipped; TBC sessions appear automatically
  once the site publishes times (daily sync)
- Season year comes from the calendar's own links (self-rolling)
- Abort guard keeps the feed stale-but-valid on redesign
"""
import html
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = "https://www.britishsuperbike.com"
UK = ZoneInfo("Europe/London")
MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
MIN_ROUNDS = 6
ALARM_MINUTES = 15
RACE_MINUTES = 45
QUALI_MINUTES = 20
SESSION_MINUTES = 45
FLAG = "\U0001F3C1 "
CANONICAL = [r"Pre Qualifying", r"Free Practice \d+", r"Qualifying \d+",
             r"Qualifying", r"Warm ?up", r"Race \d+"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bsb-ics-sync)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def canonical_name(raw):
    for pat in CANONICAL:
        m = re.search(pat, raw, re.I)
        if m:
            return m.group(0)
    return raw


def esc(x):
    return x.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def parse_rounds(page):
    rounds = []
    for chunk in page.split('class="card round-info')[1:]:
        href = re.search(r'href="/calendar/(\d{4})/([a-z0-9-]+)"', chunk)
        head = re.search(r'<div class="header">([^<]+)</div>', chunk)
        h3s = re.findall(r'<h3>([^<]+)</h3>', chunk)
        if not (href and head and len(h3s) >= 2):
            continue
        header = html.unescape(head.group(1)).strip()
        rm = re.match(r'Round (\d+)', header)
        if not rm:
            continue  # skip official tests
        span = h3s[0].strip()
        venue = html.unescape(h3s[1]).strip()
        sm = re.match(r'(\d{1,2})(?:\s+([A-Z][a-z]{2}))?\s*[-\u2013]\s*(\d{1,2})\s+([A-Z][a-z]{2})', span)
        if not sm or sm.group(4) not in MONTHS:
            continue
        year = int(href.group(1))
        m1 = MONTHS.get(sm.group(2)) if sm.group(2) else MONTHS[sm.group(4)]
        start = datetime(year, m1, int(sm.group(1)))
        end = datetime(year, MONTHS[sm.group(4)], int(sm.group(3)))
        rounds.append({"num": int(rm.group(1)), "year": year, "slug": href.group(2),
                       "venue": venue, "start": start, "end": end})
    return rounds


def day_date(rnd, abbr):
    d = rnd["start"]
    while d <= rnd["end"]:
        if d.strftime("%a") == abbr:
            return d
        d += timedelta(days=1)
    return None


def parse_timetable(page):
    rows = []
    pat = re.compile(r'<strong>(Mon|Tue|Wed|Thu|Fri|Sat|Sun)</strong></div>\s*'
                     r'<div class="cell auto"><span>([^<]+)</span></div>\s*'
                     r'<div[^>]*><span class="time">([^<]+)</span>')
    for m in pat.finditer(page):
        rows.append((m.group(1), html.unescape(m.group(2)).strip(), m.group(3).strip()))
    return rows


def main(out_path):
    cal = fetch(BASE + "/calendar")
    rounds = parse_rounds(cal)
    if len(rounds) < MIN_ROUNDS:
        print(f"ABORT: only {len(rounds)} rounds - refusing to overwrite feed.", file=sys.stderr)
        sys.exit(1)

    rounds.sort(key=lambda r: r["start"])
    season = rounds[0]["year"]
    events = []
    seen = set()
    for rnd in rounds:
        try:
            page = fetch(f"{BASE}/calendar/{rnd['year']}/{rnd['slug']}")
        except Exception:
            continue
        for abbr, raw, time_s in parse_timetable(page):
            if re.search(r'gates? open', raw, re.I):
                continue
            tm = re.match(r'(\d{1,2}):(\d{2})\s*(BST|GMT)$', time_s)
            if not tm:
                continue  # TBC etc - appears once published
            d = day_date(rnd, abbr)
            if not d:
                continue
            name = canonical_name(raw)
            start = datetime(d.year, d.month, d.day, int(tm.group(1)), int(tm.group(2)),
                             tzinfo=UK).astimezone(timezone.utc)
            key = (rnd["slug"], name, start.strftime("%Y%m%d%H%M"))
            if key in seen:
                continue
            seen.add(key)
            is_race = bool(re.fullmatch(r'Race \d+', name))
            if is_race:
                minutes = RACE_MINUTES
            elif name.lower().startswith("qualifying"):
                minutes = QUALI_MINUTES
            else:
                minutes = SESSION_MINUTES
            events.append((start, name, is_race, minutes, rnd))

    events.sort(key=lambda e: e[0])
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//LGS//BSB Auto-Sync//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:BSB",
             "X-WR-CALDESC:" + esc(f"Bennetts British Superbike Championship (season {season}), "
                                   "races + practice/qualifying, auto-synced daily from "
                                   "britishsuperbike.com"),
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
             "X-PUBLISHED-TTL:PT12H"]

    n_races = n_sessions = 0
    for start, name, is_race, minutes, rnd in events:
        end = start + timedelta(minutes=minutes)
        nslug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        uid = f"bsb-{rnd['year']}-{rnd['slug']}-{nslug}"
        summary = (FLAG if is_race else "") + f"BSB {rnd['venue']} - {name}"
        desc = (f"{name} - BSB Round {rnd['num']}, {rnd['venue']}, season {rnd['year']}. "
                "Times listed in UK time on britishsuperbike.com, auto-converted to your "
                "timezone. Auto-synced daily.")
        lines += ["BEGIN:VEVENT", f"UID:{uid}@lgs-bsb", f"DTSTAMP:{now}",
                  f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}Z",
                  f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}Z",
                  "SUMMARY:" + esc(summary),
                  "LOCATION:" + esc(rnd["venue"]),
                  "DESCRIPTION:" + esc(desc)]
        if is_race:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY",
                      "DESCRIPTION:" + esc(f"{summary} starts in {ALARM_MINUTES} minutes"),
                      f"TRIGGER:-PT{ALARM_MINUTES}M", "END:VALARM"]
            n_races += 1
        else:
            n_sessions += 1
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    with open(out_path, "w", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    print(f"OK: {len(rounds)} rounds - {n_races} races + {n_sessions} sessions "
          f"(season {season}) -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BSB.ics")
