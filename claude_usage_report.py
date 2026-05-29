#!/usr/bin/env python3
"""
claude-code-usage — a local, self-contained usage report for Claude Code.

Generates a single standalone HTML file summarising your Claude Code activity
over a rolling window of months:

  • Time together   — engaged time, from gaps between log events (<= idle cutoff)
  • Lines written   — code emitted via Write / Edit / MultiEdit / NotebookEdit
  • Estimated value — token cost at public API list prices (via `ccusage`)
  • Tokens & active days

Everything runs locally against ~/.claude/projects. No data ever leaves your
machine. On a subscription plan (Pro/Max) the dollar figure is the *equivalent*
API value, not money billed.

Usage:
    python3 claude_usage_report.py [options]

Examples:
    python3 claude_usage_report.py --open
    python3 claude_usage_report.py --months 6 --out-dir ~/reports
    python3 claude_usage_report.py --demo --open      # synthetic sample data

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


def parse_logs(projects_dir, idle_cutoff):
    """Walk *.jsonl transcripts, returning per-month time / lines / active days."""
    files = glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True)
    events = []           # (timestamp_str, month_key)
    loc = {}              # month -> lines written
    newfiles = {}         # month -> Write count

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
                    key = ts[:7]
                    events.append((ts, key))
                    content = (d.get("message") or {}).get("content")
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

    # Time + active days from globally-sorted timestamps (dedupes overlapping sessions).
    events.sort()
    secs, days = {}, {}
    prev = None
    for ts, key in events:
        dt = _parse_dt(ts)
        if dt is None:
            continue
        days.setdefault(key, set()).add(ts[:10])
        if prev is not None:
            gap = (dt - prev).total_seconds()
            if 0 < gap <= idle_cutoff:
                secs[key] = secs.get(key, 0) + gap
        prev = dt
    return loc, newfiles, secs, {k: len(v) for k, v in days.items()}


def _parse_dt(ts):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


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


def short_models(models):
    out = []
    for m in models or []:
        m = (m.replace("claude-", "")
              .replace("-20251001", "").replace("-20250929", "").replace("-20251101", "")
              .replace("opus-", "opus ").replace("sonnet-", "sonnet ").replace("haiku-", "haiku "))
        out.append(m)
    return ", ".join(sorted(set(out)))


# ------------------------------------------------------------------- demo data
def demo_data(months_wanted):
    """Fully fictional data so the sample report leaks no real usage.

    These numbers are invented for illustration only — they do not correspond
    to any real person's account.
    """
    base = [
        ("2025-10", 79200, 12, 18400, 1_240_000, 96_500_000, 78.40,
         ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-11", 111600, 17, 41200, 3_820_000, 412_000_000, 305.10,
         ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        ("2025-12", 172800, 21, 67800, 6_150_000, 718_000_000, 612.75,
         ["claude-opus-4-7", "claude-haiku-4-5-20251001"]),
    ]
    cc, loc, secs, days = {}, {}, {}, {}
    for period, sec, dy, lines, out, tok, cost, models in base[-months_wanted:]:
        cc[period] = {"period": period, "totalTokens": tok, "outputTokens": out,
                      "cacheReadTokens": int(tok * 0.985), "totalCost": cost,
                      "modelsUsed": models}
        loc[period] = lines
        secs[period] = sec
        days[period] = dy
    return cc, loc, {}, secs, days


# ----------------------------------------------------------------- HTML builder
def build_html(months, cc, loc, secs, days, idle_minutes):
    rows = []
    t_secs = t_loc = t_days = t_tok = t_out = t_cost = 0
    max_secs = max((secs.get(m, 0) for m in months), default=1) or 1
    max_cost = max((cc.get(m, {}).get("totalCost", 0) for m in months), default=1) or 1
    max_loc = max((loc.get(m, 0) for m in months), default=1) or 1
    time_bars, cost_bars, loc_bars = [], [], []

    for m in months:
        c = cc.get(m, {})
        s, l, dy = secs.get(m, 0), loc.get(m, 0), days.get(m, 0)
        tok, out = c.get("totalTokens", 0), c.get("outputTokens", 0)
        cost = c.get("totalCost", 0.0)
        t_secs += s; t_loc += l; t_days += dy; t_tok += tok; t_out += out; t_cost += cost
        rows.append(
            f'<tr><td>{m}<div class="models">{short_models(c.get("modelsUsed"))}</div></td>'
            f'<td class="time">{hm(s)}</td><td>{dy}</td>'
            f'<td class="loc">{l:,}</td><td>{out:,}</td>'
            f'<td>{tok:,}</td><td class="cost">${cost:,.2f}</td></tr>')
        lab = m[5:]
        time_bars.append(_bar(lab, s / max_secs * 100, hm(s), "time"))
        cost_bars.append(_bar(lab, cost / max_cost * 100, f"${cost:,.0f}", "cost"))
        loc_bars.append(_bar(lab, l / max_loc * 100, f"{l:,}", "loc"))

    gen = datetime.now().strftime("%d %b %Y %H:%M")
    span = f"{months[0]} – {months[-1]}" if len(months) > 1 else months[0]
    return _TEMPLATE.format(
        span=span, gen=gen, idle=idle_minutes,
        c_time=hm(t_secs), c_loc=f"{t_loc:,}", c_cost=f"${t_cost:,.0f}",
        c_tok=human_tokens(t_tok), c_tok_full=f"{t_tok:,}", c_days=t_days,
        rows="".join(rows),
        f_time=hm(t_secs), f_days=t_days, f_loc=f"{t_loc:,}",
        f_out=f"{t_out:,}", f_tok=f"{t_tok:,}", f_cost=f"${t_cost:,.2f}",
        time_bars="".join(time_bars), loc_bars="".join(loc_bars), cost_bars="".join(cost_bars),
    )


def _bar(label, pct, val, kind):
    return (f'<div class="bar-row"><div class="bar-month">{label}</div>'
            f'<div class="bar-track"><div class="bar-fill {kind}" style="width:{pct:.1f}%"></div></div>'
            f'<div class="bar-val {kind}">{val}</div></div>')


_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code — Usage Report</title>
<style>
  :root {{ --bg:#0f1115; --card:#181b22; --card2:#1f232c; --line:#2a2f3a; --txt:#e7e9ee; --muted:#9aa3b2; --accent:#d97757; --accent2:#6ea8fe; --loc:#c08cf0; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:40px 20px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:radial-gradient(1200px 600px at 50% -200px,#1a1f2b,var(--bg)); color:var(--txt); line-height:1.5; }}
  .wrap {{ max-width:980px; margin:0 auto; }}
  h1 {{ font-size:28px; margin:0 0 4px; letter-spacing:-.5px; }}
  .sub {{ color:var(--muted); font-size:14px; margin-bottom:28px; }}
  .cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:28px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }}
  .card .label {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.6px; }}
  .card .val {{ font-size:22px; font-weight:650; margin-top:6px; letter-spacing:-.5px; }}
  .card .val.cost {{ color:var(--accent); }} .card .val.time {{ color:var(--accent2); }} .card .val.loc {{ color:var(--loc); }}
  .card .hint {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .section-title {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.8px; margin:8px 0 12px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
  th,td {{ padding:12px 14px; text-align:right; font-variant-numeric:tabular-nums; }}
  th {{ background:var(--card2); color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.5px; font-weight:600; }}
  th:first-child,td:first-child {{ text-align:left; }}
  tbody tr {{ border-top:1px solid var(--line); }} tbody tr:hover {{ background:#20242e; }}
  td.cost {{ color:var(--accent); font-weight:600; }} td.time {{ color:var(--accent2); font-weight:600; }} td.loc {{ color:var(--loc); font-weight:600; }}
  tfoot td {{ border-top:2px solid var(--line); font-weight:700; background:var(--card2); }}
  .models {{ color:var(--muted); font-size:11px; }}
  .panels {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:28px; }}
  .panel {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; }}
  .bar-row {{ display:grid; grid-template-columns:42px 1fr 86px; align-items:center; gap:10px; margin:9px 0; }}
  .bar-track {{ background:#11141a; border-radius:8px; height:20px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:8px; }}
  .bar-fill.cost {{ background:linear-gradient(90deg,var(--accent),#e8a07f); }}
  .bar-fill.time {{ background:linear-gradient(90deg,var(--accent2),#a7c6ff); }}
  .bar-fill.loc {{ background:linear-gradient(90deg,var(--loc),#dcbcf7); }}
  .bar-val {{ text-align:right; font-weight:600; font-size:13px; font-variant-numeric:tabular-nums; }}
  .bar-val.cost {{ color:var(--accent); }} .bar-val.time {{ color:var(--accent2); }} .bar-val.loc {{ color:var(--loc); }}
  .bar-month {{ color:var(--muted); font-size:13px; }}
  .note {{ color:var(--muted); font-size:12px; margin-top:18px; }}
  .footer {{ color:var(--muted); font-size:12px; margin-top:18px; text-align:center; }}
  @media (max-width:760px){{ .cards{{grid-template-columns:repeat(2,1fr);}} .panels{{grid-template-columns:1fr;}} }}
</style></head><body><div class="wrap">
  <h1>Claude Code — Usage Report</h1>
  <div class="sub">{span} · generated {gen} · all figures derived locally · dollar amounts are public API-rate estimates</div>
  <div class="cards">
    <div class="card"><div class="label">Time together</div><div class="val time">{c_time}</div><div class="hint">hands-on</div></div>
    <div class="card"><div class="label">Lines written</div><div class="val loc">{c_loc}</div><div class="hint">code we wrote</div></div>
    <div class="card"><div class="label">Est. value</div><div class="val cost">{c_cost}</div><div class="hint">at API rates</div></div>
    <div class="card"><div class="label">Total tokens</div><div class="val">{c_tok}</div><div class="hint">{c_tok_full}</div></div>
    <div class="card"><div class="label">Active days</div><div class="val">{c_days}</div><div class="hint">days with activity</div></div>
  </div>
  <div class="section-title">Monthly breakdown</div>
  <table><thead><tr><th>Month</th><th>Time</th><th>Days</th><th>Lines</th><th>Output</th><th>Total tokens</th><th>Est. value</th></tr></thead>
  <tbody>{rows}</tbody>
  <tfoot><tr><td>Total</td><td class="time">{f_time}</td><td>{f_days}</td><td class="loc">{f_loc}</td><td>{f_out}</td><td>{f_tok}</td><td class="cost">{f_cost}</td></tr></tfoot></table>
  <div class="panels">
    <div class="panel"><div class="section-title" style="margin-top:0">Time (hrs)</div>{time_bars}</div>
    <div class="panel"><div class="section-title" style="margin-top:0">Lines written</div>{loc_bars}</div>
    <div class="panel"><div class="section-title" style="margin-top:0">Est. value (USD)</div>{cost_bars}</div>
  </div>
  <div class="note"><strong>Time together</strong> = sum of gaps ≤ {idle} min between consecutive log events (longer gaps are treated as time away); a fair lower bound on engaged time. <strong>Lines written</strong> counts content emitted via Write/Edit tools across all projects — a proxy, not a net git diff. On a Pro/Max subscription the dollar figure is API-equivalent value, not money billed.</div>
  <div class="footer">Generated by <a href="https://github.com/alessandr0b/claude-code-usage" style="color:var(--accent2)">claude-code-usage</a> · tokens &amp; cost via <code>ccusage</code> · time &amp; lines from <code>~/.claude/projects</code></div>
</div></body></html>"""


# -------------------------------------------------------------------------- CLI
def main(argv=None):
    p = argparse.ArgumentParser(
        description="Generate a local HTML usage report for Claude Code.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--months", type=int, default=3,
                   help="number of most-recent months (with data) to include")
    p.add_argument("--out-dir", default=DEFAULT_OUTDIR,
                   help="directory to write the report into")
    p.add_argument("--projects-dir", default=DEFAULT_PROJECTS,
                   help="Claude Code projects/logs directory")
    p.add_argument("--idle-cutoff", type=int, default=30,
                   help="minutes; gaps longer than this don't count as engaged time")
    p.add_argument("--open", action="store_true", help="open the report in your browser")
    p.add_argument("--demo", action="store_true",
                   help="use built-in synthetic data (no logs needed) for a sample")
    args = p.parse_args(argv)

    months_wanted = max(1, args.months)
    if args.demo:
        cc, loc, _newfiles, secs, days = demo_data(months_wanted)
    else:
        cc = ccusage_monthly()
        loc, _newfiles, secs, days = parse_logs(args.projects_dir, args.idle_cutoff * 60)

    all_months = sorted(set(cc) | set(loc) | set(secs))
    if not all_months:
        print(f"No usage data found in {args.projects_dir}. "
              f"Try --demo to preview with sample data.", file=sys.stderr)
        return 1
    months = all_months[-months_wanted:]

    html = build_html(months, cc, loc, secs, days, args.idle_cutoff)
    os.makedirs(args.out_dir, exist_ok=True)
    suffix = "-demo" if args.demo else ""
    out = os.path.join(args.out_dir, f"usage-{months[-1]}{suffix}.html")
    with open(out, "w") as fh:
        fh.write(html)
    print(out)
    if args.open:
        webbrowser.open(f"file://{os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
