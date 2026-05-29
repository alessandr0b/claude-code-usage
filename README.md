# claude-code-usage

A tiny, local report that turns your [Claude Code](https://claude.com/claude-code) history into a clean HTML dashboard — **time spent, lines of code written, tokens, estimated API-rate value, and unlockable achievements** — month by month, with filters (3M / 6M / 12M / All).

Everything is computed on your machine from `~/.claude/projects`. **No data leaves your computer**, no account, no API key, no telemetry.

> On a **Pro/Max** subscription the dollar figure is the *equivalent* value at public API list prices — not money you were billed. It's a fun way to see how much leverage your subscription gives you.

![Sample report](assets/screenshot.png)

It also generates a shareable **"Claude Code Wrapped"** card (`--wrapped`):

<p align="center"><img src="assets/wrapped.png" width="420" alt="Claude Code Wrapped card"></p>

*(Prefer to look first? Open [`examples/sample-report.html`](examples/sample-report.html) in your browser — built from synthetic data.)*

---

## What it measures

| Metric | How it's derived | Caveat |
|---|---|---|
| **Time together** | Sum of gaps between consecutive log events, counting only gaps ≤ idle cutoff (default 30 min). | A fair *lower bound* on engaged time — there's no "user is reading" event, so anything past the cutoff is treated as time away. |
| **Lines written** | Lines of content emitted via `Write` / `Edit` / `MultiEdit` / `NotebookEdit` tool calls. | A proxy for output volume, **not** a net git diff. Rewrites and overwrites all count. |
| **Tokens & est. value** | From [`ccusage`](https://github.com/ryoppippi/ccusage), which prices your local token counts at public API rates. | Requires Node.js (`npx`). Without it, those columns are blank and the rest still works. |
| **Active days** | Distinct calendar days with any activity. | UTC-based (matches the log timestamps). |
| **Achievements** | All-time badges from your own data: 🔥 streaks, 🏃 marathon sessions, 🌙 night owl, 🐦 early bird, 🗓️ weekend warrior, ⌨️ prolific, 💎 heavy lifter, 🧠 token titan. | Computed over all available history, so they don't shrink when you filter the table. |

Use the filter chips at the top to scope every stat, the table, and the charts to the **last 3 / 6 / 12 months or All** — all client-side, instantly.

> **A note on "All":** the report only sees what's still on disk, and Claude Code prunes logs after a retention window (~30 days by default). So older months may be missing today; history accumulates going forward. Bump it with `cleanupPeriodDays` in your Claude Code settings if you want to keep more.

---

## Quick start

No install required — it's a single dependency-free Python file (3.8+).

```bash
git clone https://github.com/alessandr0b/claude-code-usage.git
cd claude-code-usage

# Preview with synthetic data (no logs needed):
python3 claude_usage_report.py --demo --wrapped --open

# Generate your real report (+ a shareable Wrapped card) and open it:
python3 claude_usage_report.py --wrapped --open
```

The report is written to `~/claude-code-usage-reports/usage-<month>.html` (and `wrapped-<month>.html` with `--wrapped`).

**Requirements**
- Python 3.8+ (standard library only)
- [Claude Code](https://claude.com/claude-code) with logs in `~/.claude/projects`
- *Optional:* Node.js, for the token & cost columns (via `npx ccusage`)

---

## Options

```
python3 claude_usage_report.py [options]

  --out-dir DIR         Output directory (default: ~/claude-code-usage-reports)
  --projects-dir DIR    Claude Code logs dir (default: ~/.claude/projects)
  --idle-cutoff MIN     Gap (minutes) above which time stops counting (default: 30)
  --default-filter F    Range selected on open: 3 | 6 | 12 | all (default: all)
  --wrapped             Also emit a shareable "Claude Code Wrapped" card
  --open                Open the report(s) in your browser when done
  --demo                Use built-in synthetic data — no logs required
```

All months are always embedded in the report; `--default-filter` only sets which chip is active when it opens. Examples:

```bash
python3 claude_usage_report.py --default-filter 3         # open on the 3-month view
python3 claude_usage_report.py --idle-cutoff 15           # stricter "engaged" time
python3 claude_usage_report.py --wrapped --out-dir ~/Desktop --open
```

### Make the Wrapped card an image

The card is HTML; to get a PNG for social, screenshot it or render headlessly:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --screenshot=wrapped.png --window-size=600,600 \
  --force-device-scale-factor=2 \
  "file://$HOME/claude-code-usage-reports/wrapped-$(date +%Y-%m).html"
```

---

## Run it automatically every month

The installer schedules a monthly regeneration — **launchd** on macOS, **cron** on Linux.

```bash
./install.sh
```

This runs the report on the **1st of each month at 09:00**, writing to `~/claude-code-usage-reports/`. You can pass a custom output directory:

```bash
./install.sh ~/Documents/usage-reports
```

To remove the schedule later:

```bash
./uninstall.sh
```

<details>
<summary>What the installer actually does</summary>

- **macOS** — renders `templates/com.claude-code-usage.monthly.plist` with your Python path, the script path, your output dir, and a `PATH` that includes your Node install (so `npx ccusage` works under launchd), then loads it into `~/Library/LaunchAgents/`.
- **Linux** — adds a single `crontab` line: `0 9 1 * * <python> <script> --wrapped --out-dir <dir>`.

Both are idempotent — re-running replaces the existing job.
</details>

---

## How it works

```
~/.claude/projects/**/*.jsonl   ──▶  parse_logs()      ──▶  time, lines, active days
npx ccusage monthly --json      ──▶  ccusage_monthly() ──▶  tokens, cost, models
                                          │
                                          ▼
                                  build_html()  ──▶  self-contained usage-<month>.html
```

The output is a single static HTML file: inline CSS, the full month-by-month dataset embedded as JSON, and a few lines of vanilla JS that power the filter chips. **No external requests, no dependencies, no network** — open it offline anywhere, email it, or commit it.

---

## Privacy

This tool is **100% local**. It reads your existing Claude Code logs, runs `ccusage` locally, and writes HTML files to disk. Nothing is uploaded anywhere. The committed samples (`examples/sample-report.html`, `examples/sample-wrapped.html`) use synthetic numbers, not anyone's real usage.

---

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Ideas: per-project breakdowns, weekly/daily granularity, CSV/JSON export, light theme, more achievements.

## Acknowledgements

Token and cost data comes from the excellent [`ccusage`](https://github.com/ryoppippi/ccusage) by [@ryoppippi](https://github.com/ryoppippi).

## License

[MIT](LICENSE)
