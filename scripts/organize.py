#!/usr/bin/env python3
"""Apple App Organizer — Unified CLI for cleaning up macOS built-in apps.

Safety principles:
  1. Dry-run by default. Pass --execute to mutate anything.
  2. Whitelist protection. Protected items are never touched.
  3. Trash, not delete. Mail → Trash; Messages → Recently Deleted (30 days);
     Notes → Archive; Reminders/Calendar → deleted only after explicit confirm.
  4. Report first. Every module can emit a Markdown report before writing.
  5. Loop detection. UI-automation loops halt after 5 identical window titles.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root so 'scripts.modules' package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.modules import messages, notes, reminders, calendar, contacts, mail

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

    class _FakeConsole:
        def print(self, *args, **kwargs):
            for a in args: print(a)
        def input(self, prompt=""):
            return input(prompt)

    class _FakeTable:
        def __init__(self, *a, **k): pass
        def add_column(self, *a, **k): pass
        def add_row(self, *a, **k): pass
        def __str__(self): return "<Table>"

    class _FakePanel:
        def __init__(self, *a, **k): pass
        def __str__(self): return "<Panel>"

    Console = _FakeConsole
    Table = _FakeTable
    Panel = _FakePanel

console = Console()

SUBMODULES = {
    "messages": messages,
    "notes": notes,
    "reminders": reminders,
    "calendar": calendar,
    "contacts": contacts,
    "mail": mail,
}

DEFAULT_WHITELIST_FILE = Path(__file__).parent.parent / "whitelist.json"
DEFAULT_OUTPUT_DIR = Path("/tmp/apple-app-organizer")
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_whitelist(path: Path) -> dict:
    if not path.exists():
        return {"contacts": [], "phone_numbers": [], "email_addresses": [], "calendar_ids": []}
    with open(path) as f:
        return json.load(f)


def print_summary(title: str, rows: list[dict], console: Console):
    if not rows:
        console.print(f"{title}: nothing found")
        return
    if RICH_AVAILABLE:
        table = Table(title=title, show_header=True, header_style="bold cyan")
        for col in rows[0].keys():
            table.add_column(col.replace("_", " ").title(), style="white")
        for row in rows:
            table.add_row(*[str(v) for v in row.values()])
        console.print(table)
    else:
        console.print(f"\n=== {title} ===")
        headers = list(rows[0].keys())
        console.print("  ".join(h.replace("_", " ").title() for h in headers))
        console.print("-" * 80)
        for row in rows:
            console.print("  ".join(str(v)[:20] for v in row.values()))


# ── Shared argument parser factory ────────────────────────────────────────────

def add_shared_flags(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Show planned actions without executing (default: true)",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually perform mutations (overrides --dry-run)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Directory for report files",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip per-item confirmation prompts",
    )
    parser.add_argument(
        "--whitelist-file", type=Path, default=DEFAULT_WHITELIST_FILE,
        help="JSON file listing protected identifiers",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="organize.py",
        description="Apple App Organizer — safe cleanup for macOS built-in apps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="module", required=True, help="App module to operate on")

    for name, mod in SUBMODULES.items():
        cmd = sub.add_parser(name, help=getattr(mod, "__doc__", name))
        add_shared_flags(cmd)

        # Default action
        cmd.add_argument(
            "action", nargs="?", default="scan",
            choices=["scan", "report", "clean"],
            help="Action to perform (default: scan)",
        )

        # Module-specific flags
        mod.add_cli_args(cmd)

    return parser


def resolve_dry_run(args: argparse.Namespace) -> bool:
    """Return True if we should only simulate (dry run)."""
    if args.execute:
        return False
    return args.dry_run  # default True


# ── Action dispatchers ─────────────────────────────────────────────────────────

def action_scan(mod, args, whitelist: dict, dry_run: bool):
    msg = f"Scanning {args.module}"
    if RICH_AVAILABLE:
        console.print(Panel(f"[bold cyan]{msg}[/bold cyan]", expand=False))
    else:
        console.print(f"--- {msg} ---")
    items = mod.scan(whitelist=whitelist)
    console.print(f"\nFound {len(items)} item(s)")
    if items:
        print_summary(f"{args.module.title()} scan results", items[:50], console)
    return items


def action_report(mod, args, whitelist: dict, dry_run: bool):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{args.module}_report.md"
    msg = f"Generating report → {out_path}"
    if RICH_AVAILABLE:
        console.print(Panel(f"[bold cyan]{msg}[/bold cyan]", expand=False))
    else:
        console.print(f"--- {msg} ---")
    report = mod.generate_report(whitelist=whitelist, output_dir=args.output_dir)
    console.print(f"Report written to {out_path}")
    return report


def action_clean(mod, args, whitelist: dict, dry_run: bool):
    if dry_run:
        if RICH_AVAILABLE:
            console.print(Panel("[bold yellow]DRY RUN — no changes will be made[/bold yellow]", expand=False))
        else:
            console.print("--- DRY RUN — no changes will be made ---")
    else:
        if RICH_AVAILABLE:
            console.print(Panel("[bold red]EXECUTING — changes WILL be made[/bold red]", expand=False))
        else:
            console.print("!!! EXECUTING — changes WILL be made !!!")

    items = mod.scan(whitelist=whitelist)
    if not items:
        console.print("Nothing to clean.")
        return []

    # Show what would be done
    print_summary(f"{args.module.title()} items flagged for cleanup", items[:50], console)

    if not args.yes and not dry_run:
        confirmed = console.input(
            f"\nDelete {len(items)} item(s) in {args.module}? (y/N): "
        )
        if confirmed.lower() != "y":
            console.print("Aborted.")
            return []

    deleted = mod.clean(items, dry_run=dry_run, whitelist=whitelist)
    verb = "Would delete" if dry_run else "Deleted"
    console.print(f"{verb} {len(deleted)} item(s)")
    return deleted


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.module not in SUBMODULES:
        parser.print_help()
        sys.exit(1)

    mod = SUBMODULES[args.module]
    whitelist = load_whitelist(args.whitelist_file)
    dry_run = resolve_dry_run(args)

    # Validate permissions first
    try:
        perm_ok = mod.check_permissions()
        if not perm_ok:
            msg = (
                f"Permission denied for {args.module}. "
                "Ensure Full Disk Access and Automation permissions are granted in System Settings."
            )
            if RICH_AVAILABLE:
                console.print(f"[bold red]{msg}[/bold red]")
            else:
                console.print(f"ERROR: {msg}")
            sys.exit(1)
    except Exception as e:
        console.print(f"Permission check warning: {e}")

    # Dispatch by action
    if args.action == "scan":
        action_scan(mod, args, whitelist, dry_run)
    elif args.action == "report":
        action_report(mod, args, whitelist, dry_run)
    elif args.action == "clean":
        action_clean(mod, args, whitelist, dry_run)

    console.print("\nDone.")


if __name__ == "__main__":
    main()
