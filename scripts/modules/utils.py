"""Shared utilities for apple-app-organizer."""

import subprocess
import re
import json
from pathlib import Path


def run_applescript(script: str, timeout: int = 30) -> str:
    """Execute AppleScript and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def run_jxa(script: str, timeout: int = 30) -> str:
    """Execute JavaScript for Automation (JXA) and return stdout."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"JXA error: {result.stderr.strip()}")
    return result.stdout.strip()


def normalize_phone(phone: str) -> str:
    """Strip country code, spaces, dashes, and non-digits for comparison."""
    digits = re.sub(r"\D", "", phone)
    # Strip leading +86 / 86
    if digits.startswith("86") and len(digits) > 10:
        digits = digits[2:]
    return digits


def normalize_email(email: str) -> str:
    """Lowercase and strip surrounding whitespace."""
    return email.lower().strip().strip('"')


def truncate(s: str, max_len: int = 80) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def write_json(data: list, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_markdown(lines: list[str], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
