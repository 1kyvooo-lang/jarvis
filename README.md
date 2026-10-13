# JARVIS for Mac

Your own JARVIS: a Mac app you talk to by voice or text.

- **Hermes Agent** (Nous Research) is the brain: it plans, remembers and uses tools, on the model you choose (Nous Portal, OpenRouter, …).
- **ElevenLabs** is the voice: Scribe understands you, and replies are spoken in an ElevenLabs voice.
- **Playwright MCP** is the browser: JARVIS can read and use websites in its own Chrome window.
- **The Mac agent** opens apps, finds and reads files in folders you approve, checks system status and sends notifications.

Anything consequential waits for you to click **Approve**: buying, sending, submitting forms, uploading, opening an unapproved site, opening apps, reading files. The **Emergency stop** halts everything instantly.

## Install (once)

Easiest: open **Terminal**, paste this and press Enter:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/1kyvooo-lang/jarvis/main/scripts/get.sh)
```
Or from the zip:

1. Unzip `jarvis.zip`.
2. Double-click **`Install JARVIS.command`**.
   If macOS says it can't verify the developer, open **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. Or open Terminal and paste:
   ```bash
   bash ~/Downloads/jarvis/scripts/install_mac.sh
   ```
3. Follow the prompts. The installer asks before installing anything:
   - Homebrew, Python, Node and `uv`, only if they're missing.
   - **Hermes Agent**, via its official installer, plus the two Hermes features JARVIS uses (its API server and MCP support).
   - **Hermes's model picker.** Choose Nous Portal or OpenRouter and sign in.
   - JARVIS itself, which goes to `~/Library/Application Support/JARVIS`, so you can delete the download afterwards.
   - **JARVIS.app**, in your Applications folder.
   - Optionally, starting JARVIS at login (recommended).
4. JARVIS opens with a short setup checklist. Paste your **ElevenLabs API key** (from elevenlabs.io → API keys) and allow the microphone when asked.

After that, open **JARVIS** from Applications, the Dock or Spotlight like any other app.

## Using it

- **Talk:** on the Assistant page, tap the mic, speak, and tap again. You can also hold the mic while you speak and let go. Questions you ask by voice get spoken answers.
- **Type:** Enter sends.
- **Approve:** requests appear in an amber bar at the top of every page. The action runs the moment you click Approve. If nobody answers within 4 minutes, it doesn't run.
- **Stop:** the stop button ends the current reply. **Emergency stop**, in the left rail, halts all actions and automations until you resume.
- **Quit:** Settings → Startup and quitting → Quit JARVIS.

## Command Center

The home screen. The holographic core reacts live: it swells with your voice while listening, pulses with his while speaking, and spins up while thinking or acting. Around it you get live system status, an activity feed, your task timeline, CPU/RAM/disk, memory stats and quick commands. **Talk to JARVIS** at the bottom starts a hands-free conversation. Collapse the left sidebar with the arrow next to the logo.

## “Hey JARVIS”

Leave the JARVIS window open (it can sit in the background, and it opens itself at login). Say **“Hey JARVIS”**: he answers “Yes? What do you need?” and you talk hands-free. Wake-word detection runs locally on your Mac (openWakeWord). No audio is recorded or sent anywhere until he's awake. Turn it off or tune its sensitivity in Settings → “Hey JARVIS”.

## Call mode (talk like a phone call, in the app)

On the Assistant page click **Call**. Just talk: JARVIS hears when you stop, answers out loud, and listens again.
Talk over him to interrupt. Say "goodbye" or click **End call** to stop. The conversation also appears as text.

## Phone line (Twilio): call or text JARVIS from your phone

1. In the Twilio Console, copy your **Account SID** and **Auth Token**, and note your Twilio phone number.
2. In JARVIS go to **Settings → Phone (Twilio)**, fill in those plus **your mobile number**, tick **Phone line on**, and click **Save**.
3. JARVIS opens a secure Cloudflare tunnel and points your Twilio number at this Mac automatically. When it says **Online**,
   try **Call me now** and **Send test text**.

- Call or text your Twilio number and JARVIS answers. He can also call or text you ("call me when it's done").
- Only your own mobile number gets through. Everyone else hears "not available", and their texts are ignored.
- If an action needs approval during a call, he asks and you answer "yes" or "no".
- It works while your Mac is on and awake. A sleeping or offline Mac means no answer.
- Costs are Twilio's (number rental plus per-minute and per-SMS), plus ElevenLabs characters for his voice.
- Every request from Twilio is checked against your Auth Token signature. Only the `/twilio` routes are reachable from the internet,
  and they run on a separate port. The dashboard, Hermes and the Mac agent stay local only.

## Email, calendar and appointments (Google)

Settings → **Google**: follow the 5 steps to create your own Google OAuth client, then click **Connect Google**.

- “What's in my inbox?”, “Archive all the newsletters”, “Reply to Anna and say Tuesday works”: he reads, labels, archives and drafts. **Sending always waits for your OK.** He can't delete mail.
- “What's on tomorrow?”, “Book a dentist slot Friday at 3”: he reads your calendar and books. Inviting other people asks first.
- **Inbox assistant** (Settings → Receptionist & inbox assistant): every few minutes it sorts new mail into `JARVIS/…` labels and drafts replies to real people. The drafts wait for you.

## Receptionist: he answers other people

When anyone else calls or texts your Twilio number, a separate, locked-down assistant answers. It's a second Hermes profile with no memory, no web, and no access to your email, files or chats; its only tools are *check availability*, *book appointment*, and *take message*.

- On calls it books appointments into free slots inside your working hours and texts you each booking and message.
- Replies to texts from other people are drafted for you, and only go out once you approve.
- **Approve from your phone:** JARVIS texts you “needs your OK (#12)”. Reply **YES 12** or **NO 12**.

Tell it what it may share (services, prices, hours) in Settings → Receptionist.

## Mac, music and notes

- “Open Spotify”, “Pause the music”, “Next song”, “What's playing?”, “Play Daft Punk on Spotify”, “Find lo-fi on YouTube”, “Open Mail”, “Volume 30”. Apps on your approved list now open without asking.
- **Obsidian:** set your vault folder in Settings → Obsidian. Then “Search my notes for Helixa”, “Add this to my Ideas note”, “Make a note called Launch plan”. He never deletes notes. Replacing a whole note asks first and keeps a backup.

## Opening JARVIS

Click **JARVIS** in the Dock, use the **menu bar icon** (top right; it also has Emergency stop, Restart and Quit), or press Cmd+Space and type JARVIS. Closing the window doesn't stop him: calls, texts, reminders and the inbox keep working. If anything shows red on the Command Center, click **Restart Hermes & Mac agent**.

## Reminders and morning briefing

- “Remind me at 3 to call Marco”: at 3 he texts you. Say “call me” for a phone call or “notify me” for a Mac notification. Upcoming reminders appear in the Mission Timeline.
- **Morning briefing** (Settings): every morning at your chosen time you get today's calendar, important new email, open tasks, reminders and approvals, by text or phone call.

## JARVIS on your phone

Settings → **JARVIS on your phone**: install Tailscale (free) on the Mac and iPhone with the same account, set a passcode, and click **Turn on phone access**. JARVIS texts you the link. Open it in Safari, then Share → **Add to Home Screen**. It's private to your devices and never on the public internet. The passcode is required, and 5 wrong tries lock it for 15 minutes.

## Backups

JARVIS backs up his memory, chats, tasks, reminders and settings every day and keeps 14 days, with a copy in iCloud Drive → JARVIS Backups when iCloud Drive is on. Restore from Settings → Backups. Keys stay in your Keychain and are never in a backup.

## Model router and privacy guard

- Settings → **Model router**: add a *fast*, *think*, *vision* and/or *local* (Ollama) model. Start a message with `fast:` or `think:`, or let JARVIS pick: short questions go to fast, analysis goes to think. It uses Hermes's own `model_routes`, so tools and memory work the same on every model.
- **Privacy guard** (always on): API keys, tokens, passwords, card numbers and one-time codes are replaced with `[REDACTED …]` before anything reaches a cloud model, including email contents. Each redaction is logged in Activity.

## What JARVIS can do (and what asks first)

| Area | Without asking | Asks you first |
|---|---|---|
| Browser (Playwright MCP) | Open approved sites, read pages, screenshots, ordinary clicks and typing | Unapproved sites; clicks on buttons like buy, pay, send, submit, delete, confirm; filling forms; uploads; running page scripts; accepting dialogs; typing into password or card fields |
| Mac | Time, system status and info, search file names in approved folders, notifications, open approved websites and apps, music, YouTube, volume | Read a file (approved folders only) |
| Email & calendar | Search, read, label, archive, list events, find free slots, book your own events | Send email, invite other people |
| Messages | Text or call you | Text anyone else |
| Obsidian | Search, read, create notes, append to notes | Replace a note |
| Tasks and memory | To-dos, save and search your notes, propose automations | Proposed automations only run after you approve them on the Tasks page |

You can change all of this in **Settings**: approved apps, sites and folders, which Mac tools ask first, which browser actions always ask, and the click words that trigger a check.

Some things are always blocked: no shell, terminal or code-execution tools are given to Hermes through JARVIS. Files like `.env`, keys, `.ssh` and Keychains can't be read even inside approved folders. `file://`, `javascript:` and similar URLs are refused.

## How it fits together

```
JARVIS.app ─ opens ─▶ Dashboard (127.0.0.1:8000) ◀── voice ──▶ ElevenLabs (Scribe + TTS)
                         │  JARVIS backend: chat, approvals, memory, tasks, activity log
                         │  starts & supervises ▼
                         ├── Hermes gateway (API server on 127.0.0.1:8642) ── your model (Nous / OpenRouter)
                         │        │ MCP
                         │        ▼
                         │    jarvis MCP server ── every call goes through JARVIS's approval gate
                         │        ├── Mac agent (127.0.0.1:8765): apps, files, system, notifications
                         │        └── Playwright MCP: Chrome window with its own profile
                         └── Mac agent (kept alive)
```

- Hermes only gets these tools through its **API server** surface: `web`, `todo`, `memory`, `session_search`, `skills` and the `jarvis` MCP server. Your normal `hermes` command-line setup isn't changed.
- JARVIS adds two entries to `~/.hermes/config.yaml`: `mcp_servers.jarvis` and `platform_toolsets.api_server`. Your original config is backed up first as `config.yaml.before-jarvis`, and comments and other settings are kept.
- Hermes's API server is protected by a key JARVIS generates. Everything listens on 127.0.0.1 only.
- Keys are stored in your **macOS Keychain**. The browser never sees them.

## Troubleshooting

| What you see | What to do |
|---|---|
| macOS blocks the installer | System Settings → Privacy & Security → **Open Anyway** (or run the Terminal command above) |
| "Hermes isn't running" | Settings → Hermes → **Restart Hermes**. If it keeps failing, the message shows Hermes's last log lines |
| "rejected JARVIS's key" | Another Hermes gateway is already running. Stop it with `hermes gateway stop`, or paste its `API_SERVER_KEY` in Settings → Hermes → Advanced |
| Hermes errors about the model or provider | Settings → Hermes → **Choose AI model**. This opens Hermes's own picker in Terminal |
| Browser actions say Playwright isn't installed | Run the installer again (it repairs) |
| No voice / "Add your ElevenLabs key" | Settings → Voice → paste your key |
| Mic doesn't work | Allow the mic when the JARVIS window asks, and in System Settings → Privacy & Security → Microphone |
| Opening apps or notifications fail | macOS may ask to let JARVIS (Python) control apps or send notifications. Allow it in System Settings |
| Something else | Logs are in `~/Library/Application Support/JARVIS/data/logs/` (`backend.log`, `hermes.out`, `mcp.log`, `agent.log`) |

**Update:** Settings → Updates → **Update now**. JARVIS checks GitHub for new versions every few hours and shows a dot on Settings when one is ready. The update installs and restarts JARVIS by itself, and keeps your settings, history, memory and keys. Details are in `data/logs/update.log`.

**Repair:** run the Terminal command above (or `Install JARVIS.command`) again. It keeps your settings, history and memory.

**Uninstall:** double-click `Uninstall JARVIS.command`. It removes the app, the login item, JARVIS's data and its Hermes config entries. Hermes itself is left installed.

## Not built yet

- Shell/terminal commands are deliberately off.
- Smart home and market data have reserved interfaces only. Hermes can also connect messaging apps itself (`hermes gateway setup`).

## For developers

```bash
./scripts/setup.sh         # venv, packages, Playwright MCP, dashboard build, Hermes extras, tests
./scripts/dev.sh           # backend (+ Hermes + agent) and hot-reloading dashboard on :5173
./scripts/dev.sh --built   # same, dashboard served on :8000
./scripts/stop.sh
.venv/bin/python -m pytest -q
```

```
agent/        Mac agent: tool registry, allowlists, path safety, auth, idempotency, kill switch
backend/      main.py (API), chat.py (Hermes turns), hermes.py (config, client, events),
              actions.py (approval gate), browser_policy.py, voice.py (ElevenLabs),
              services.py (supervises Hermes + agent), memory.py, scheduler.py, db.py,
              google.py (Gmail/Calendar), public.py (receptionist), wake.py, router.py, redact.py, updater.py
jarvis_mcp/   MCP server Hermes connects to (Mac tools + gated Playwright MCP proxy)
frontend/     React + TypeScript + Tailwind dashboard (GSAP, Lenis, React Bits components)
mcp-runtime/  pinned @playwright/mcp
macos/        app icon
scripts/      install_mac.sh · build_app.sh · launchagent.sh · hermes_extras.sh · dev/setup/stop
```

To add a Mac tool, add a decorated function in `agent/tools.py`. It shows up in Hermes, the dashboard and Settings automatically. Set `sensitive=True` to make it always ask first.

React Bits components in frontend/src/components/reactbits are © David Haz, MIT + Commons Clause (see LICENSE.md there).
