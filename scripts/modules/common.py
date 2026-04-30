"""Shared utilities for apple-app-organizer modules."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_OUTPUT_DIR = Path("/tmp/apple-app-organizer")

# --------------------------------------------------------------------------- #
# AppleScript execution
# --------------------------------------------------------------------------- #


class AppleScriptError(RuntimeError):
    """Raised when osascript returns a non-zero exit code."""


def osa(script: str, timeout: float = 15.0) -> str:
    """Execute an AppleScript string and return its stdout.

    Raises AppleScriptError on non-zero exit. Timeout defaults to 15s so UI
    automation cannot hang the whole process indefinitely.
    """
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AppleScriptError(result.stderr.strip())
    return result.stdout.strip()


# --------------------------------------------------------------------------- #
# Whitelist / protection helpers (Messages, Mail, Contacts all use these)
# --------------------------------------------------------------------------- #

# Chinese mobile displayed with spaces in the UI: "+86 187 7391 0065"
# In chat.db: "+8618773910065". Normalize before matching.
_PHONE_STRIP = re.compile(r"[\s\-\(\)]")

CN_MOBILE_RE = re.compile(r"^\+86\d{11}$")
US_CA_RE = re.compile(r"^\+1\d{10}$")
UK_RE = re.compile(r"^\+44\d{10}$")
JP_RE = re.compile(r"^\+81\d{10,11}$")

DEFAULT_PROTECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    CN_MOBILE_RE,
    US_CA_RE,
    UK_RE,
    JP_RE,
)

# Short codes commonly associated with banks / government — default protect.
DEFAULT_PROTECT_EXACT = frozenset({
    "95588",   # 工商银行 ICBC
    "95555",   # 招商银行 CMB
    "95533",   # 建设银行 CCB
    "95559",   # 交通银行 BCM
    "95566",   # 中国银行 BOC
    "95577",   # 华夏银行
    "95595",   # 光大银行
    "95522",   # 平安银行
    "121234403",  # 广东交警
})


def normalize_phone(s: str) -> str:
    """Strip whitespace, dashes, parens from phone-like strings."""
    return _PHONE_STRIP.sub("", s or "")


def is_protected(
    identifier: str,
    *,
    extra_exact: Iterable[str] = (),
    extra_patterns: Iterable[re.Pattern[str]] = (),
) -> bool:
    """Return True if the identifier should never be deleted."""
    if not identifier:
        return False
    normalized = normalize_phone(identifier)
    exact = set(DEFAULT_PROTECT_EXACT) | set(extra_exact)
    if identifier in exact or normalized in exact:
        return True
    # Built-in patterns match the normalized (digits-only) form
    for pat in DEFAULT_PROTECT_PATTERNS:
        if pat.match(normalized):
            return True
    # User-supplied patterns are matched against BOTH forms so callers can
    # decide whether their pattern expects normalized or raw input
    for pat in extra_patterns:
        if pat.match(identifier) or pat.match(normalized):
            return True
    return False


# --------------------------------------------------------------------------- #
# Spam rules (Messages / Mail share some)
# --------------------------------------------------------------------------- #

DEFAULT_SPAM_PREFIXES: tuple[str, ...] = (
    "106", "955", "10010", "10086", "10000", "10001",
    "12306", "59239", "59200", "400", "800",
)

DEFAULT_SPAM_KEYWORDS: tuple[str, ...] = (
    "【", "回T退订", "回TD退订", "退订回", "验证码", "激活码",
    "促销", "特惠", "限时", "折扣", "立减", "秒杀", "优惠券",
    "贷款", "借款", "分期", "授信", "额度",
    "中奖", "抽奖", "点击", "链接",
    "瑞幸", "美团", "饿了么", "滴滴", "携程",
    "营业厅", "套餐", "话费", "流量", "宽带",
    "火车", "航班",
    "申通", "中通", "圆通", "韵达", "京东",
)


def looks_like_spam(
    identifier: str,
    body: str | None,
    *,
    prefixes: Iterable[str] = DEFAULT_SPAM_PREFIXES,
    keywords: Iterable[str] = DEFAULT_SPAM_KEYWORDS,
) -> tuple[bool, str]:
    """Return (is_spam, reason). Does NOT check whitelist — caller should."""
    normalized = normalize_phone(identifier).replace("+86", "").replace("+", "")
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return True, f"prefix {prefix}"
    if body:
        hits = [k for k in keywords if k in body]
        if hits:
            return True, f"keywords {hits[:3]}"
    if normalized.isdigit() and len(normalized) >= 12:
        return True, f"numeric sender id ({len(normalized)} digits)"
    return False, ""


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #


def _ensure_dir(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def write_json_report(data: dict | list, out_dir: Path, prefix: str = "report") -> Path:
    """Write a timestamped JSON report and return the path."""
    out_dir = _ensure_dir(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{prefix}-{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_markdown_report(
    title: str,
    sections: list[tuple[str, list[dict], list[str]]],
    out_dir: Path,
    prefix: str = "report",
) -> Path:
    """Write a Markdown table report.

    sections: list of (section_title, rows, column_order).
    """
    out_dir = _ensure_dir(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{prefix}-{stamp}.md"
    lines = [f"# {title}", f"_Generated {stamp}_", ""]
    for section_title, rows, columns in sections:
        lines.append(f"## {section_title} ({len(rows)})")
        lines.append("")
        if not rows:
            lines.append("_No entries._")
            lines.append("")
            continue
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("|" + "|".join("---" for _ in columns) + "|")
        for row in rows[:500]:  # cap
            cells = []
            for col in columns:
                val = row.get(col, "")
                text = str(val).replace("|", "/").replace("\n", " ")[:80]
                cells.append(text)
            lines.append("| " + " | ".join(cells) + " |")
        if len(rows) > 500:
            lines.append("")
            lines.append(f"_({len(rows) - 500} more rows truncated — see JSON)_")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
