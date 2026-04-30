# apple-app-organizer: modules/__init__.py
"""Each module exposes:
  scan(whitelist)          -> list[dict]
  generate_report(...)     -> str  (path to markdown)
  clean(items, ...)        -> list[dict]  (actually-deleted IDs)
  check_permissions()      -> bool
  add_cli_args(parser)     -> None  (add module-specific args)
"""

from . import messages, notes, reminders, calendar, contacts, mail

__all__ = ["messages", "notes", "reminders", "calendar", "contacts", "mail"]
