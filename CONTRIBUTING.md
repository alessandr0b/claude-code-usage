# Contributing

Thanks for your interest! This is a small, dependency-free project and aims to stay that way.

## Ground rules

- **Standard library only** for `claude_usage_report.py`. No pip dependencies — it should run with a bare `python3` (3.8+). `ccusage` is invoked as an external CLI, not imported.
- **Local-only.** The tool must never make network calls or transmit usage data anywhere. The only subprocess is `npx ccusage` (also local).
- **The output stays a single self-contained HTML file** — inline CSS, no JS, no external assets — so it can be opened or emailed anywhere.

## Dev loop

```bash
# Fast iteration with synthetic data — no logs required:
python3 claude_usage_report.py --demo --wrapped --open

# Against your own logs:
python3 claude_usage_report.py --wrapped --open
```

There are no build steps. If you change the HTML template, regenerate the committed samples:

```bash
python3 claude_usage_report.py --demo --wrapped --default-filter all --out-dir examples
mv examples/usage-*-demo.html    examples/sample-report.html
mv examples/wrapped-*-demo.html  examples/sample-wrapped.html
```

The samples must always come from `--demo` (synthetic data) — never commit real usage.

## Ideas / good first issues

- Per-project breakdown (group by the `projects/<dir>` segment)
- Weekly or daily granularity (`--granularity`)
- CSV / JSON export alongside the HTML
- Light theme toggle
- More achievements / a "most active day" stat

## Submitting

1. Fork and branch.
2. Keep PRs focused; describe the change and include a screenshot if it touches the report.
3. Confirm both `--demo` and a real run still produce a valid report.
