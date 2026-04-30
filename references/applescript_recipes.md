# AppleScript Recipes for Messages.app

A cookbook of hard-won AppleScript patterns for automating Messages.app on macOS.

## What DOES NOT work

### ❌ `delete` AppleScript command

```applescript
tell application "Messages"
    delete chat 1
end tell
-- Error -10000: Messages encountered an error: AppleEvent handler failed
```

Messages.app's scripting dictionary exposes `chat` objects as read-only — no `delete` verb.

### ❌ Cmd+Delete

The menu item **对话 → 删除对话…** (`Conversation → Delete Conversation…`) has no keyboard shortcut. Verify:

```applescript
tell application "System Events"
    tell process "Messages"
        set delItem to menu item "删除对话…" of menu 1 of menu bar item "对话" of menu bar 1
        return value of attribute "AXMenuItemCmdChar" of delItem
        -- Returns missing value
    end tell
end tell
```

Must invoke via menu click.

### ❌ Chinese via `keystroke`

```applescript
keystroke "瑞幸咖啡"
-- Produces "a'a'a'a" or similar garbage on many systems
```

The keystroke action translates to raw keycodes; non-ASCII multibyte input fails silently.

## What DOES work

### ✅ Chinese input via clipboard

```applescript
set the clipboard to "瑞幸咖啡"
tell application "Messages" to activate
delay 0.3
tell application "System Events"
    tell process "Messages"
        -- focus the target field first, then paste
        keystroke "v" using command down
    end tell
end tell
delay 1.5  -- let search settle
```

### ✅ Locate the search field

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

The description varies: `"搜索"` (empty field) or `"搜索文本栏"` (focused). Match by `starts with "搜索"`.

### ✅ Safe delete via menu + sheet

```applescript
tell application "System Events"
    tell process "Messages"
        set delItem to menu item "删除对话…" of menu 1 of menu bar item "对话" of menu bar 1
        if not (enabled of delItem) then return "NO_CHAT_SELECTED"
        click delItem
        delay 1.0
        -- Handle the confirmation sheet
        if (count of sheets of window 1) > 0 then
            repeat with b in buttons of sheet 1 of window 1
                -- IMPORTANT: exact match, NOT "starts with"
                if (title of b as string) is "删除" then
                    click b
                    exit repeat
                end if
            end repeat
        end if
    end tell
end tell
```

**The sheet has three buttons**: `[删除, 删除并报告垃圾信息, 取消]`. Matching loosely (e.g. `starts with "删除"`) would also hit the second button, which reports the number to Apple as spam — not always desired.

### ✅ Advance to next chat

```applescript
tell application "System Events"
    tell process "Messages"
        keystroke "]" using {command down, shift down}  -- next chat
        keystroke "[" using {command down, shift down}  -- previous chat
    end tell
end tell
```

These are the documented shortcuts under **窗口 → 前往下一个/上一个对话**.

### ✅ Read current chat identifier

In standalone-window mode, the window title equals the `chat_identifier`:

```applescript
tell application "System Events"
    tell process "Messages"
        return name of window 1
        -- e.g. "10655007020080169692" or "+86 187 7391 0065"
    end tell
end tell
```

In sidebar-main-view mode, the window title is `"信息"` — not useful. The batch-delete script takes advantage of standalone mode.

### ✅ Recently Deleted access

```applescript
tell application "System Events"
    tell process "Messages"
        click menu item "最近删除" of menu 1 of menu bar item "显示" of menu bar 1
    end tell
end tell
```

Restore a deleted conversation:

```applescript
tell application "System Events"
    tell process "Messages"
        -- Select first result
        click (first button of window 1 whose description is "联系人照片")
        -- Click Restore
        click (first button of window 1 whose description is "恢复")
    end tell
end tell
```

## Window subtleties

Messages has two window scenes (see `defaults read com.apple.MobileSMS`):

- `CKMessagesSceneDelegate` — sidebar + search view (the "main" window)
- `CKChatSceneDelegate` — standalone single-chat window (via `文件 → 在新窗口中打开对话`)

Once a standalone window has been opened, subsequent Messages launches may restore directly into a standalone window, leaving no sidebar. Recovery:

```bash
# Force-quit and clear saved state
killall Messages
rm -rf ~/Library/Saved\ Application\ State/com.apple.MobileSMS.savedState
sleep 2
open -a Messages
```

Or manually: right-click Dock icon → Quit → reopen from Launchpad.

## Timing tips

- After `click searchField`, wait 0.3-0.5s before paste
- After paste, wait 1.5-2.0s for Messages to filter
- After menu click for delete, wait 1.0-1.2s for the sheet
- After clicking the Delete button, wait 1.2-1.5s for Messages to refresh and advance
