# AppleScript Recipes for macOS Apps

Tested patterns used across apple-app-organizer modules.

## Messages.app

### Locate search field

```applescript
tell application "System Events"
    tell process "Messages"
        set searchField to missing value
        repeat with elem in entire contents of window 1
            try
                if class of elem is text field and description of elem starts with "搜索" then
                    set searchField to elem
                    exit repeat
                end if
            end try
        end repeat
        click searchField
    end tell
end tell
```

### Chinese input via clipboard

```applescript
set the clipboard to "瑞幸咖啡"
tell application "Messages" to activate
delay 0.3
tell application "System Events" to tell process "Messages" to keystroke "v" using command down
```

### Safe delete via menu + strict sheet match

```applescript
tell application "System Events"
    tell process "Messages"
        set delItem to menu item "删除对话…" of menu 1 of menu bar item "对话" of menu bar 1
        if enabled of delItem then
            click delItem
            delay 1.0
            if (count of sheets of window 1) > 0 then
                repeat with b in buttons of sheet 1 of window 1
                    -- IMPORTANT: is "删除", not starts with "删除"
                    if (title of b as string) is "删除" then
                        click b
                        exit repeat
                    end if
                end repeat
            end if
        end if
    end tell
end tell
```

### Advance between chats

```applescript
tell application "System Events" to tell process "Messages"
    keystroke "]" using {command down, shift down}  -- next
    keystroke "[" using {command down, shift down}  -- previous
end tell
```

## Notes.app

### Enumerate notes

```applescript
tell application "Notes"
    set output to ""
    repeat with n in notes
        set output to output & (id of n as string) & tab & (name of n as string) & linefeed
    end repeat
    return output
end tell
```

### Move note to folder

```applescript
tell application "Notes"
    set target to first note whose id is "x-coredata://.../NOTE/p123"
    set archiveFolder to first folder whose name is "Archive"
    move target to archiveFolder
end tell
```

### Create Archive folder if missing

```applescript
tell application "Notes"
    if not (exists folder "Archive") then
        make new folder with properties {name:"Archive"}
    end if
end tell
```

## Reminders.app

### Enumerate completed items

```applescript
tell application "Reminders"
    set output to ""
    repeat with lst in lists
        repeat with r in (reminders of lst whose completed is true)
            set output to output & (id of r) & tab & (name of r) & tab & ¬
                (completion date of r as string) & tab & (name of lst) & linefeed
        end repeat
    end repeat
    return output
end tell
```

### Delete reminder by id

```applescript
tell application "Reminders"
    delete (first reminder whose id is "X-ID")
end tell
```

## Calendar.app

### Enumerate events older than N months

```applescript
tell application "Calendar"
    set cutoff to (current date) - (6 * 30 * days)
    set output to ""
    repeat with cal in calendars
        repeat with e in (events of cal whose start date < cutoff)
            set output to output & (uid of e) & tab & (summary of e) & tab & ¬
                (start date of e as string) & tab & (name of cal) & linefeed
        end repeat
    end repeat
    return output
end tell
```

### Delete event

```applescript
tell application "Calendar"
    delete (first event of calendar "Home" whose uid is "X")
end tell
```

## Contacts.app

### Enumerate contacts with phones

```applescript
tell application "Contacts"
    set output to ""
    repeat with p in people
        set phoneList to ""
        repeat with ph in phones of p
            set phoneList to phoneList & (value of ph) & ","
        end repeat
        set output to output & (id of p) & tab & (name of p) & tab & phoneList & linefeed
    end repeat
    return output
end tell
```

Contacts.app has **no scriptable merge verb** — duplicate merges must be done
manually via the UI ("Card → Look for Duplicates"), or via undocumented
AddressBook C APIs. This skill emits a Markdown report and leaves the merge to
the user.

## Mail.app

### Enumerate messages in a mailbox

```applescript
tell application "Mail"
    set mb to mailbox "INBOX" of account "MyAccount"
    set output to ""
    repeat with m in messages of mb
        set output to output & (id of m) & tab & (subject of m) & tab & ¬
            (sender of m) & tab & (date received of m as string) & linefeed
    end repeat
    return output
end tell
```

### Move to Trash (reversible)

```applescript
tell application "Mail"
    set msg to first message of mailbox "INBOX" of account "MyAccount" whose id is X
    move msg to mailbox "Deleted Messages" of account "MyAccount"
end tell
```

Prefer this over `delete msg` — Trash is recoverable for ~30 days depending on the provider.

## Common patterns

### Timeout protection

Always wrap UI automation subprocess calls with a timeout:

```python
subprocess.run(["osascript", "-e", script], timeout=15, capture_output=True, text=True)
```

### Clear pending sheet before new action

Before starting any menu click, check for a lingering confirmation sheet and cancel it:

```applescript
if (count of sheets of window 1) > 0 then
    repeat with b in buttons of sheet 1 of window 1
        if (title of b as string) is "取消" then click b
    end repeat
end if
```

### Loop detection

When walking through items (e.g., advancing Messages conversations), keep a
tail of the last 5 seen identifiers. If all five are equal, halt — something
is stuck.
