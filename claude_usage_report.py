#!/usr/bin/env python3
"""
claude-code-usage — a local, self-contained usage report for Claude Code.

Generates a single standalone HTML file summarising your Claude Code activity,
month by month, with interactive filters (3M / 6M / 12M / All):

  • Time together   — engaged time, from gaps between log events (<= idle cutoff)
  • Lines written   — code emitted via Write / Edit / MultiEdit / NotebookEdit
  • Estimated value — token cost at public API list prices (via `ccusage`)
  • Messages        — your prompts + Claude's replies, and your favorite model
  • Tokens & active days
  • Achievements    — all-time local badges (streaks, night owl, marathons, …)

It can also emit a shareable "Claude Code Wrapped" card (--wrapped).

Everything runs locally against ~/.claude/projects. No data ever leaves your
machine. The report is a single HTML file with inline CSS + a little vanilla JS
for the filters — no external requests, opens offline anywhere. On a Pro/Max
subscription the dollar figure is the *equivalent* API value, not money billed.

Note: "All" is bounded by Claude Code's log retention (~30 days by default),
so older months may not exist locally. History accumulates going forward.

Usage:
    python3 claude_usage_report.py [options]

Examples:
    python3 claude_usage_report.py --open
    python3 claude_usage_report.py --wrapped --open
    python3 claude_usage_report.py --default-filter 3m --open
    python3 claude_usage_report.py --demo --wrapped --open   # synthetic sample

See --help for all options. MIT licensed.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime

DEFAULT_PROJECTS = os.path.expanduser("~/.claude/projects")
DEFAULT_OUTDIR = os.path.expanduser("~/claude-code-usage-reports")
REPO = "github.com/alessandr0b/claude-code-usage"


# --------------------------------------------------------------------- ccusage
def ccusage_monthly():
    """Return {period: monthly_record} from `npx ccusage@latest monthly --json`."""
    try:
        proc = subprocess.run(
            ["npx", "ccusage@latest", "monthly", "--json"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            print(f"warning: ccusage exited {proc.returncode}: {proc.stderr.strip()[:200]}",
                  file=sys.stderr)
        return {m["period"]: m for m in json.loads(proc.stdout).get("monthly", [])}
    except FileNotFoundError:
        print("warning: `npx` not found — token/cost columns will be empty. "
              "Install Node.js to enable them.", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"warning: ccusage failed ({e}) — token/cost columns will be empty.",
              file=sys.stderr)
    return {}


# ------------------------------------------------------ parse local transcripts
def _lines(s):
    if not s:
        return 0
    return s.count("\n") + (0 if s.endswith("\n") else 1)


def _parse_dt(ts):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _is_real_user_prompt(msg):
    """True for a human-typed prompt; False for synthetic tool_result turns."""
    content = msg.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result"
                       for b in content)
    return False


def parse_logs(projects_dir):
    """Walk *.jsonl transcripts. Returns (events, loc, newfiles, msgs, models).

    events   — sorted list of datetimes (one per log entry with a timestamp)
    loc      — {month: lines written}
    newfiles — {month: Write count}
    msgs     — {month: messages exchanged} (your prompts + Claude's replies)
    models   — {model: replies} all-time, for the "favorite model" stat
    """
    files = glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True)
    events, loc, newfiles, msgs, models = [], {}, {}, {}, {}

    for f in files:
        try:
            with open(f, errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = d.get("timestamp")
                    if not ts:
                        continue
                    dt = _parse_dt(ts)
                    if dt is not None:
                        events.append(dt)
                    key = ts[:7]
                    msg = d.get("message") or {}
                    t = d.get("type")
                    if t == "assistant":
                        msgs[key] = msgs.get(key, 0) + 1
                        model = msg.get("model")
                        if model and model != "<synthetic>":
                            models[model] = models.get(model, 0) + 1
                    elif t == "user" and _is_real_user_prompt(msg):
                        msgs[key] = msgs.get(key, 0) + 1
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for b in content:
                        if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                            continue
                        name, inp = b.get("name"), (b.get("input") or {})
                        add = 0
                        if name == "Write":
                            add = _lines(inp.get("content", ""))
                            newfiles[key] = newfiles.get(key, 0) + 1
                        elif name == "Edit":
                            add = _lines(inp.get("new_string", ""))
                        elif name == "MultiEdit":
                            for e in inp.get("edits", []) or []:
                                add += _lines(e.get("new_string", ""))
                        elif name == "NotebookEdit":
                            add = _lines(inp.get("new_source", ""))
                        if add:
                            loc[key] = loc.get(key, 0) + add
        except OSError:
            pass

    events.sort()
    return events, loc, newfiles, msgs, models


def compute_stats(events, months, idle_cutoff):
    """Per-month time/active-days + all-time badge inputs for events in `months`.

    Each sub-cutoff gap's seconds are attributed to the *later* event's time
    bucket (consistent with total time-together).
    """
    mset = set(months)
    secs_by_month, days_by_month = {}, {}
    night = morning = weekend = total = 0.0
    longest_session = session_secs = 0.0
    session_start = None
    active_days = set()
    prev = None

    for dt in events:
        key = dt.strftime("%Y-%m")
        if key not in mset:
            prev = None
            continue
        active_days.add(dt.date())
        days_by_month.setdefault(key, set()).add(dt.date())
        if prev is not None:
            gap = (dt - prev).total_seconds()
            if 0 < gap <= idle_cutoff:
                secs_by_month[key] = secs_by_month.get(key, 0) + gap
                total += gap
                if dt.hour < 5:
                    night += gap
                elif dt.hour < 8:
                    morning += gap
                if dt.weekday() >= 5:
                    weekend += gap
                session_secs += gap
            else:
                longest_session = max(longest_session, session_secs)
                session_secs, session_start = 0.0, dt
        else:
            session_start = dt
        prev = dt
    longest_session = max(longest_session, session_secs)

    return {
        "secs_by_month": secs_by_month,
        "days_by_month": {k: len(v) for k, v in days_by_month.items()},
        "extras": {
            "total_secs": total, "night_secs": night, "morning_secs": morning,
            "weekend_secs": weekend, "longest_session": longest_session,
            "longest_streak": _longest_streak(active_days),
        },
    }


def _longest_streak(active_days):
    if not active_days:
        return 0
    days = sorted(active_days)
    best = run = 1
    for i in range(1, len(days)):
        run = run + 1 if (days[i] - days[i - 1]).days == 1 else 1
        best = max(best, run)
    return best


# ----------------------------------------------------------------- achievements
def compute_badges(extras, totals):
    """Return an ordered list of badge dicts (earned first). All-time."""
    tot = extras["total_secs"] or 1
    defs = [
        ("🔥", "On Fire", extras["longest_streak"] >= 5,
         f'{extras["longest_streak"]}-day streak', "5-day streak"),
        ("🏃", "Marathoner", extras["longest_session"] >= 3 * 3600,
         f'{hm(extras["longest_session"])} in one sitting', "3h+ single session"),
        ("🌙", "Night Owl", extras["night_secs"] / tot >= 0.15,
         f'{extras["night_secs"]/tot*100:.0f}% after midnight', "15%+ time 00–05h"),
        ("🐦", "Early Bird", extras["morning_secs"] / tot >= 0.12,
         f'{extras["morning_secs"]/tot*100:.0f}% at dawn', "12%+ time 05–08h"),
        ("🗓️", "Weekend Warrior", extras["weekend_secs"] / tot >= 0.25,
         f'{extras["weekend_secs"]/tot*100:.0f}% on weekends', "25%+ time on weekends"),
        ("📅", "Regular", totals["days"] >= 20,
         f'{totals["days"]} active days', "20+ active days"),
        ("⌨️", "Prolific", totals["loc"] >= 50_000,
         f'{totals["loc"]:,} lines', "50k+ lines written"),
        ("💎", "Heavy Lifter", totals["cost"] >= 1000,
         f'${totals["cost"]:,.0f} of value', "$1,000+ API-rate value"),
        ("🧠", "Token Titan", totals["tokens"] >= 1_000_000_000,
         f'{human_tokens(totals["tokens"])} tokens', "1B+ tokens"),
    ]
    badges = [{"emoji": e, "name": n, "earned": bool(ok),
               "detail": d if ok else hint} for (e, n, ok, d, hint) in defs]
    badges.sort(key=lambda b: not b["earned"])
    return badges


# ------------------------------------------------------------------- formatting
def hm(s):
    return f"{int(s // 3600)}h {int((s % 3600) // 60)}m"


def human_tokens(n):
    if n >= 1e9:
        return f"{n / 1e9:.2f} B"
    if n >= 1e6:
        return f"{n / 1e6:.2f} M"
    if n >= 1e3:
        return f"{n / 1e3:.1f} K"
    return str(n)


def pretty_model(m):
    """Turn 'claude-opus-4-7' / 'claude-haiku-4-5-20251001' into 'opus 4-7'."""
    if not m:
        return ""
    m = m.replace("claude-", "")
    for fam in ("opus", "sonnet", "haiku"):
        if m.startswith(fam + "-"):
            ver = m[len(fam) + 1:].split("-202", 1)[0]  # drop any -YYYYMMDD suffix
            return f"{fam} {ver}"
    return m


def short_models(models):
    return ", ".join(sorted({pretty_model(m) for m in (models or [])}))


def favorite_model(models):
    """({model: replies}) -> (pretty_name, replies) for the most-used model."""
    if not models:
        return None, 0
    name, n = max(models.items(), key=lambda kv: kv[1])
    return pretty_model(name), n


# ------------------------------------------------------------------- demo data
def demo_data():
    """Fully fictional data so the sample report leaks no real usage.

    These numbers are invented for illustration only — they do not correspond
    to any real person's account.
    """
    base = [
        ("2025-07", 50400, 9, 9600, 720_000, 51_000_000, 41.20, 1_900,
         ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-08", 64800, 11, 14300, 980_000, 73_000_000, 58.90, 2_600,
         ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-09", 90000, 14, 21800, 1_510_000, 142_000_000, 121.40, 4_100,
         ["claude-opus-4-6", "claude-sonnet-4-6"]),
        ("2025-10", 79200, 12, 18400, 1_240_000, 96_500_000, 78.40, 3_300,
         ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-11", 111600, 17, 41200, 3_820_000, 412_000_000, 305.10, 7_400,
         ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-12", 172800, 21, 67800, 6_150_000, 718_000_000, 612.75, 11_200,
         ["claude-opus-4-7", "claude-haiku-4-5-20251001"]),
    ]
    cc, loc, secs, days, msgs = {}, {}, {}, {}, {}
    for period, sec, dy, lines, out, tok, cost, ms, models in base:
        cc[period] = {"period": period, "totalTokens": tok, "outputTokens": out,
                      "cacheReadTokens": int(tok * 0.985), "totalCost": cost,
                      "modelsUsed": models}
        loc[period], secs[period], days[period], msgs[period] = lines, sec, dy, ms
    total = sum(secs.values()) or 1
    extras = {
        "total_secs": total, "night_secs": total * 0.18, "morning_secs": total * 0.05,
        "weekend_secs": total * 0.30, "longest_session": 4.2 * 3600,
        "longest_streak": 9,
    }
    models = {"claude-opus-4-7": 18_400, "claude-sonnet-4-6": 9_200,
              "claude-haiku-4-5-20251001": 2_700, "claude-opus-4-6": 1_200}
    return cc, loc, secs, days, extras, msgs, models


# ----------------------------------------------------------------- HTML helpers
def _render_badges(badges):
    earned = sum(1 for b in badges if b["earned"])
    chips = []
    for b in badges:
        cls = "badge" if b["earned"] else "badge locked"
        chips.append(
            f'<div class="{cls}"><div class="ico">{b["emoji"]}</div>'
            f'<div class="bmeta"><div class="bname">{b["name"]}</div>'
            f'<div class="bdesc">{b["detail"]}</div></div></div>')
    return earned, len(badges), "".join(chips)


def build_html(rows, badges, default_filter, idle_minutes, gen, fav_name, fav_n):
    """rows: list of per-month dicts sorted ascending by month."""
    earned, total_badges, badges_html = _render_badges(badges)
    data_json = json.dumps(rows, separators=(",", ":"))
    if fav_name:
        fav_html = (f'🏆 <strong>Favorite model</strong> — {fav_name} '
                    f'<span class="favn">{fav_n:,} replies · all-time</span>')
    else:
        fav_html = '🏆 <strong>Favorite model</strong> — not enough data yet'
    repl = {
        "%%DATA%%": data_json,
        "%%BADGES%%": badges_html,
        "%%BADGE_COUNT%%": f"{earned} of {total_badges} unlocked",
        "%%DEFAULT%%": default_filter,
        "%%IDLE%%": str(idle_minutes),
        "%%GEN%%": gen,
        "%%FAV%%": fav_html,
        "%%REPO%%": REPO,
    }
    html = _TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


def build_wrapped(span, totals, badges):
    """A square, shareable 'Claude Code Wrapped' card."""
    top = [b for b in badges if b["earned"]][:3]
    chips = "".join(
        f'<div class="wb"><span>{b["emoji"]}</span>{b["name"]}</div>' for b in top
    ) or '<div class="wb">🌱 Just getting started</div>'
    fav = f'★ Favorite model · {totals["fav_model"]}' if totals.get("fav_model") else ""
    return (_WRAPPED_TEMPLATE
            .replace("%%SPAN%%", span)
            .replace("%%FAV%%", fav)
            .replace("%%TIME%%", hm(totals["secs"]))
            .replace("%%LOC%%", f'{totals["loc"]:,}')
            .replace("%%TOK%%", human_tokens(totals["tokens"]))
            .replace("%%COST%%", f'${totals["cost"]:,.0f}')
            .replace("%%MSGS%%", f'{totals["msgs"]:,}')
            .replace("%%DAYS%%", str(totals["days"]))
            .replace("%%CHIPS%%", chips)
            .replace("%%REPO%%", REPO))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code — Usage Report</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --card2:#1f232c; --line:#2a2f3a; --txt:#e7e9ee; --muted:#9aa3b2; --accent:#d97757; --accent2:#6ea8fe; --loc:#c08cf0; --gold:#e6b450; }
  * { box-sizing:border-box; }
  body { margin:0; padding:40px 20px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:radial-gradient(1200px 600px at 50% -200px,#1a1f2b,var(--bg)); color:var(--txt); line-height:1.5; }
  .wrap { max-width:980px; margin:0 auto; }
  h1 { font-size:28px; margin:0 0 4px; letter-spacing:-.5px; }
  .sub { color:var(--muted); font-size:14px; margin-bottom:24px; }
  .filters { display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap; }
  .chip { cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--muted); padding:7px 16px; border-radius:999px; font-size:13px; font-weight:600; user-select:none; }
  .chip:hover { border-color:#3a4150; color:var(--txt); }
  .chip.active { background:var(--accent); border-color:var(--accent); color:#fff; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:18px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }
  .card .label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.6px; }
  .card .val { font-size:22px; font-weight:650; margin-top:6px; letter-spacing:-.5px; }
  .card .val.cost { color:var(--accent); } .card .val.time { color:var(--accent2); } .card .val.loc { color:var(--loc); } .card .val.msgs { color:#7fd1b9; }
  .card .hint { color:var(--muted); font-size:12px; margin-top:4px; }
  .fav { background:linear-gradient(180deg,#241f12,var(--card)); border:1px solid #3a3320; border-radius:12px; padding:12px 16px; margin-bottom:28px; font-size:14px; color:var(--gold); }
  .fav .favn { color:var(--muted); font-weight:400; margin-left:6px; }
  .section-title { font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.8px; margin:8px 0 12px; display:flex; justify-content:space-between; }
  .section-title .count { color:var(--gold); }
  .badges { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; margin-bottom:28px; }
  .badge { display:flex; align-items:center; gap:11px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:11px 13px; }
  .badge .ico { font-size:24px; line-height:1; }
  .badge .bname { font-weight:650; font-size:14px; }
  .badge .bdesc { color:var(--muted); font-size:11.5px; }
  .badge:not(.locked) { border-color:#3a3320; background:linear-gradient(180deg,#241f12,var(--card)); }
  .badge:not(.locked) .bname { color:var(--gold); }
  .badge.locked { opacity:.45; filter:grayscale(.7); }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }
  th,td { padding:12px 14px; text-align:right; font-variant-numeric:tabular-nums; }
  th { background:var(--card2); color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.5px; font-weight:600; }
  th:first-child,td:first-child { text-align:left; }
  tbody tr { border-top:1px solid var(--line); } tbody tr:hover { background:#20242e; }
  td.cost { color:var(--accent); font-weight:600; } td.time { color:var(--accent2); font-weight:600; } td.loc { color:var(--loc); font-weight:600; }
  tfoot td { border-top:2px solid var(--line); font-weight:700; background:var(--card2); }
  .models { color:var(--muted); font-size:11px; }
  .panels { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:28px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; }
  .bar-row { display:grid; grid-template-columns:48px 1fr 86px; align-items:center; gap:10px; margin:9px 0; }
  .bar-track { background:#11141a; border-radius:8px; height:20px; overflow:hidden; }
  .bar-fill { height:100%; border-radius:8px; transition:width .3s ease; }
  .bar-fill.cost { background:linear-gradient(90deg,var(--accent),#e8a07f); }
  .bar-fill.time { background:linear-gradient(90deg,var(--accent2),#a7c6ff); }
  .bar-fill.loc { background:linear-gradient(90deg,var(--loc),#dcbcf7); }
  .bar-val { text-align:right; font-weight:600; font-size:13px; font-variant-numeric:tabular-nums; }
  .bar-val.cost { color:var(--accent); } .bar-val.time { color:var(--accent2); } .bar-val.loc { color:var(--loc); }
  .bar-month { color:var(--muted); font-size:13px; }
  .note { color:var(--muted); font-size:12px; margin-top:18px; }
  .footer { color:var(--muted); font-size:12px; margin-top:18px; text-align:center; }
  .footer a { color:var(--accent2); }
  @media (max-width:760px){ .cards{grid-template-columns:repeat(2,1fr);} .panels{grid-template-columns:1fr;} }
</style></head><body><div class="wrap">
  <h1>Claude Code — Usage Report</h1>
  <div class="sub"><span id="span"></span> · generated %%GEN%% · all figures derived locally · dollar amounts are public API-rate estimates</div>

  <div class="filters" id="filters">
    <div class="chip" data-f="3">3M</div>
    <div class="chip" data-f="6">6M</div>
    <div class="chip" data-f="12">12M</div>
    <div class="chip" data-f="all">All</div>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Time together</div><div class="val time" id="c_time"></div><div class="hint">hands-on</div></div>
    <div class="card"><div class="label">Lines written</div><div class="val loc" id="c_loc"></div><div class="hint">code we wrote</div></div>
    <div class="card"><div class="label">Est. value</div><div class="val cost" id="c_cost"></div><div class="hint">at API rates</div></div>
    <div class="card"><div class="label">Total tokens</div><div class="val" id="c_tok"></div><div class="hint" id="c_tok_full"></div></div>
    <div class="card"><div class="label">Messages</div><div class="val msgs" id="c_msgs"></div><div class="hint">you + Claude</div></div>
    <div class="card"><div class="label">Active days</div><div class="val" id="c_days"></div><div class="hint">days with activity</div></div>
  </div>

  <div class="fav">%%FAV%%</div>

  <div class="section-title"><span>Achievements (all-time)</span><span class="count">%%BADGE_COUNT%%</span></div>
  <div class="badges">%%BADGES%%</div>

  <div class="section-title"><span>Monthly breakdown</span></div>
  <table><thead><tr><th>Month</th><th>Time</th><th>Days</th><th>Msgs</th><th>Lines</th><th>Output</th><th>Total tokens</th><th>Est. value</th></tr></thead>
  <tbody id="tbody"></tbody>
  <tfoot id="tfoot"></tfoot></table>

  <div class="panels">
    <div class="panel"><div class="section-title" style="margin-top:0"><span>Time (hrs)</span></div><div id="bars_time"></div></div>
    <div class="panel"><div class="section-title" style="margin-top:0"><span>Lines written</span></div><div id="bars_loc"></div></div>
    <div class="panel"><div class="section-title" style="margin-top:0"><span>Est. value (USD)</span></div><div id="bars_cost"></div></div>
  </div>

  <div class="note"><strong>Time together</strong> = sum of gaps ≤ %%IDLE%% min between consecutive log events (longer gaps are treated as time away); a fair lower bound on engaged time. <strong>Lines written</strong> counts content emitted via Write/Edit tools across all projects — a proxy, not a net git diff. <strong>Messages</strong> = your prompts plus Claude's replies (tool-result turns excluded); <strong>Favorite model</strong> is the model behind the most replies, all-time. <strong>"All"</strong> is limited by Claude Code's log retention, so older months may be missing. On a Pro/Max subscription the dollar figure is API-equivalent value, not money billed.</div>
  <div class="footer">Generated by <a href="https://%%REPO%%">claude-code-usage</a> · tokens &amp; cost via <code>ccusage</code> · time &amp; lines from <code>~/.claude/projects</code></div>
</div>
<script>
const DATA = %%DATA%%;            // [{m,secs,days,msgs,loc,out,tok,cost,models}] ascending
let FILTER = "%%DEFAULT%%";
const $ = id => document.getElementById(id);

const hm = s => { s=Math.round(s); return Math.floor(s/3600)+"h "+Math.floor((s%3600)/60)+"m"; };
const ht = n => n>=1e9?(n/1e9).toFixed(2)+" B":n>=1e6?(n/1e6).toFixed(2)+" M":n>=1e3?(n/1e3).toFixed(1)+" K":""+n;
const ci = n => n.toLocaleString("en-US");
const m0 = n => "$"+Math.round(n).toLocaleString("en-US");
const m2 = n => "$"+n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});

function calWindow(latest, n) {
  let [y,mo] = latest.split("-").map(Number), s = new Set();
  for (let i=0;i<n;i++){ s.add(y+"-"+String(mo).padStart(2,"0")); if(--mo===0){mo=12;y--;} }
  return s;
}
function subset() {
  if (FILTER==="all" || !DATA.length) return DATA;
  const win = calWindow(DATA[DATA.length-1].m, parseInt(FILTER,10));
  return DATA.filter(d => win.has(d.m));
}
function bars(host, rows, key, fmt, cls) {
  const max = Math.max(1, ...rows.map(r => r[key]));
  host.innerHTML = rows.map(r =>
    `<div class="bar-row"><div class="bar-month">${r.m.slice(5)}</div>`+
    `<div class="bar-track"><div class="bar-fill ${cls}" style="width:${(r[key]/max*100).toFixed(1)}%"></div></div>`+
    `<div class="bar-val ${cls}">${fmt(r[key])}</div></div>`).join("");
}
function render() {
  const rows = subset();
  const t = rows.reduce((a,r)=>({secs:a.secs+r.secs,loc:a.loc+r.loc,days:a.days+r.days,
    msgs:a.msgs+(r.msgs||0),tok:a.tok+r.tok,out:a.out+r.out,cost:a.cost+r.cost}),
    {secs:0,loc:0,days:0,msgs:0,tok:0,out:0,cost:0});
  $("span").textContent = rows.length ? (rows.length>1 ? rows[0].m+" – "+rows[rows.length-1].m : rows[0].m) : "no data";
  $("c_time").textContent = hm(t.secs);
  $("c_loc").textContent = ci(t.loc);
  $("c_cost").textContent = m0(t.cost);
  $("c_tok").textContent = ht(t.tok);
  $("c_tok_full").textContent = ci(t.tok);
  $("c_msgs").textContent = ci(t.msgs);
  $("c_days").textContent = t.days;
  $("tbody").innerHTML = rows.map(r =>
    `<tr><td>${r.m}<div class="models">${r.models||""}</div></td>`+
    `<td class="time">${hm(r.secs)}</td><td>${r.days}</td><td>${ci(r.msgs||0)}</td>`+
    `<td class="loc">${ci(r.loc)}</td><td>${ci(r.out)}</td>`+
    `<td>${ci(r.tok)}</td><td class="cost">${m2(r.cost)}</td></tr>`).join("");
  $("tfoot").innerHTML =
    `<tr><td>Total</td><td class="time">${hm(t.secs)}</td><td>${t.days}</td><td>${ci(t.msgs)}</td>`+
    `<td class="loc">${ci(t.loc)}</td><td>${ci(t.out)}</td><td>${ci(t.tok)}</td>`+
    `<td class="cost">${m2(t.cost)}</td></tr>`;
  bars($("bars_time"), rows, "secs", hm, "time");
  bars($("bars_loc"),  rows, "loc",  ci, "loc");
  bars($("bars_cost"), rows, "cost", m0, "cost");
}
function setFilter(f) {
  FILTER = f;
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c.dataset.f===f));
  render();
}
document.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => setFilter(c.dataset.f)));
// Fall back to "all" if the default filter would show nothing.
if (FILTER!=="all" && !subset().length) FILTER="all";
setFilter(FILTER);
</script>
</body></html>"""


_WRAPPED_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code Wrapped</title>
<style>
  * { box-sizing:border-box; margin:0; }
  body { display:flex; align-items:center; justify-content:center; min-height:100vh; padding:24px;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:#0b0d12; }
  .card { width:540px; height:540px; border-radius:28px; padding:38px 40px; color:#fff;
    background:radial-gradient(120% 120% at 0% 0%, #d97757 0%, #b5485f 38%, #6a3d8f 72%, #2c2f6b 100%);
    box-shadow:0 30px 80px rgba(0,0,0,.5); display:flex; flex-direction:column; position:relative; overflow:hidden; }
  .card::after { content:""; position:absolute; inset:0; background:radial-gradient(60% 50% at 90% 10%, rgba(255,255,255,.18), transparent 60%); pointer-events:none; }
  .kicker { font-size:13px; letter-spacing:3px; text-transform:uppercase; opacity:.85; }
  .title { font-size:40px; font-weight:800; letter-spacing:-1px; margin-top:4px; line-height:1.05; }
  .span { font-size:15px; opacity:.85; margin-top:6px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px 22px; margin-top:28px; }
  .stat .n { font-size:34px; font-weight:800; letter-spacing:-1px; }
  .stat .l { font-size:12.5px; letter-spacing:1px; text-transform:uppercase; opacity:.8; margin-top:2px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:auto; }
  .wb { display:flex; align-items:center; gap:6px; background:rgba(255,255,255,.16);
    border:1px solid rgba(255,255,255,.25); padding:7px 12px; border-radius:999px; font-size:13px; font-weight:600; }
  .wb span { font-size:15px; }
  .foot { margin-top:18px; font-size:12px; opacity:.8; display:flex; justify-content:space-between; }
</style></head><body>
  <div class="card">
    <div class="kicker">Claude Code · Wrapped</div>
    <div class="title">My Claude Code<br>recap</div>
    <div class="span">%%SPAN%% · %%FAV%%</div>
    <div class="grid">
      <div class="stat"><div class="n">%%TIME%%</div><div class="l">Time together</div></div>
      <div class="stat"><div class="n">%%MSGS%%</div><div class="l">Messages</div></div>
      <div class="stat"><div class="n">%%LOC%%</div><div class="l">Lines written</div></div>
      <div class="stat"><div class="n">%%TOK%%</div><div class="l">Tokens</div></div>
      <div class="stat"><div class="n">%%COST%%</div><div class="l">Value @ API rates</div></div>
      <div class="stat"><div class="n">%%DAYS%%</div><div class="l">Active days</div></div>
    </div>
    <div class="chips">%%CHIPS%%</div>
    <div class="foot"><span>%%DAYS%% active days</span><span>%%REPO%%</span></div>
  </div>
</body></html>"""


# -------------------------------------------------------------------------- CLI
def main(argv=None):
    p = argparse.ArgumentParser(
        description="Generate a local HTML usage report for Claude Code.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--out-dir", default=DEFAULT_OUTDIR,
                   help="directory to write the report into")
    p.add_argument("--projects-dir", default=DEFAULT_PROJECTS,
                   help="Claude Code projects/logs directory")
    p.add_argument("--idle-cutoff", type=int, default=30,
                   help="minutes; gaps longer than this don't count as engaged time")
    p.add_argument("--default-filter", default="all", choices=["3", "6", "12", "all", "3m", "6m", "12m"],
                   help="which range is selected when the report opens")
    p.add_argument("--open", action="store_true", help="open the report in your browser")
    p.add_argument("--wrapped", action="store_true",
                   help="also emit a shareable 'Claude Code Wrapped' card")
    p.add_argument("--demo", action="store_true",
                   help="use built-in synthetic data (no logs needed) for a sample")
    args = p.parse_args(argv)

    default_filter = args.default_filter.rstrip("m")

    if args.demo:
        cc, loc, secs, days, extras, msgs, models = demo_data()
        months = sorted(cc)
    else:
        cc = ccusage_monthly()
        events, loc, _newfiles, msgs, models = parse_logs(args.projects_dir)
        present = {dt.strftime("%Y-%m") for dt in events} | set(cc) | set(loc)
        if not present:
            print(f"No usage data found in {args.projects_dir}. "
                  f"Try --demo to preview with sample data.", file=sys.stderr)
            return 1
        months = sorted(present)
        st = compute_stats(events, months, args.idle_cutoff * 60)
        secs, days, extras = st["secs_by_month"], st["days_by_month"], st["extras"]

    rows = [{
        "m": m,
        "secs": round(secs.get(m, 0)),
        "days": days.get(m, 0),
        "msgs": msgs.get(m, 0),
        "loc": loc.get(m, 0),
        "out": cc.get(m, {}).get("outputTokens", 0),
        "tok": cc.get(m, {}).get("totalTokens", 0),
        "cost": round(cc.get(m, {}).get("totalCost", 0.0), 2),
        "models": short_models(cc.get(m, {}).get("modelsUsed")),
    } for m in months]

    fav_name, fav_n = favorite_model(models)
    totals = {
        "secs": sum(r["secs"] for r in rows),
        "loc": sum(r["loc"] for r in rows),
        "days": sum(r["days"] for r in rows),
        "msgs": sum(r["msgs"] for r in rows),
        "tokens": sum(r["tok"] for r in rows),
        "cost": sum(r["cost"] for r in rows),
        "fav_model": fav_name, "fav_model_n": fav_n,
    }
    badges = compute_badges(extras, totals)
    gen = datetime.now().strftime("%d %b %Y %H:%M")

    os.makedirs(args.out_dir, exist_ok=True)
    suffix = "-demo" if args.demo else ""
    outputs = []

    html = build_html(rows, badges, default_filter, args.idle_cutoff, gen,
                      fav_name, fav_n)
    out = os.path.join(args.out_dir, f"usage-{months[-1]}{suffix}.html")
    with open(out, "w") as fh:
        fh.write(html)
    outputs.append(out)

    if args.wrapped:
        span = f"{months[0]} – {months[-1]}" if len(months) > 1 else months[0]
        card = build_wrapped(span, totals, badges)
        wout = os.path.join(args.out_dir, f"wrapped-{months[-1]}{suffix}.html")
        with open(wout, "w") as fh:
            fh.write(card)
        outputs.append(wout)

    for o in outputs:
        print(o)
    if args.open:
        for o in outputs:
            webbrowser.open(f"file://{os.path.abspath(o)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
