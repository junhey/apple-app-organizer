# Granting macOS permissions

apple-app-organizer needs three permission families.

## 1. Full Disk Access (FDA)

Required to read `chat.db`, `NoteStore.sqlite`, and other sandboxed system databases.

**Grant**:
1. System Settings → Privacy & Security → Full Disk Access
2. Click `+` and add:
   - `/System/Applications/Utilities/Terminal.app`
   - Your agent runtime (Cursor.app, WorkBuddy.app, Claude Code, Warp.app, …)
3. **Completely quit and relaunch** the runtime

**Verify**:
```bash
sqlite3 -readonly ~/Library/Messages/chat.db "SELECT COUNT(*) FROM chat;"
# success: a number; failure: "authorization denied"
```

## 2. Accessibility

Required for UI automation of Messages (menu clicks for "删除对话…").

**Grant**: System Settings → Privacy & Security → Accessibility → add runtime.

**Verify**:
```bash
osascript -e 'tell application "System Events" to get UI elements enabled'
# must return: true
```

## 3. Automation (per-app)

The first time the skill talks to Messages/Notes/Reminders/Calendar/Contacts/Mail,
macOS shows a dialog: *"Terminal wants to control Notes.app"*. Click **OK**.

**View/revoke**: System Settings → Privacy & Security → Automation.

If you accidentally clicked "Don't Allow", you can reset all prompts:
```bash
tccutil reset AppleEvents
# then restart your runtime and re-run the skill to re-prompt
```

## Common failures

| Symptom | Fix |
|---------|-----|
| `authorization denied` when opening chat.db | FDA missing, or runtime not restarted after grant |
| `Accessibility UI elements not enabled` | Grant Accessibility, restart runtime |
| `Not authorised to send Apple events` | Automation permission not granted, or `tccutil reset` it |
| Empty window, no sidebar in Messages | Messages is in "standalone chat window" mode. Fully quit Messages.app and relaunch from Launchpad. |

## Keeping FDA safe

FDA is powerful. Do NOT grant it to random apps. Only grant to:
- Trusted development tools you actively use
- The specific runtime running this skill

Revoke when done:
System Settings → Privacy & Security → Full Disk Access → remove entries.
