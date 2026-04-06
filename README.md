## `README.md`

```markdown
# 🎣 FishBot

Automated fishing bot for Roblox with a dark-themed GUI, real-time detection, and zero-config persistence.

---

## ✨ What it does

- Casts, waits, detects bites via cyan splash detection, reels automatically
- Visual calibration — click pixels, no code editing
- Hotkeys, session stats, live state display
- Config auto-saves between sessions

---

## 🖥️ Requirements

| | |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.9 – 3.12 recommended · 3.14 attempts with warning |
| Roblox | Running before you launch FishBot |

---

## 🚀 Quick start

```
1. Download or clone this repo
2. Double-click  build.bat
3. Right-click   dist/FishBot.exe  →  Run as Administrator
```

That's it. The build system handles the virtual environment and all dependencies automatically.

---

## ⚙️ First-time setup inside the app

Take it one step at a time — each step has a ✓ indicator so you always know where you are.

```
[ Calibration panel ]

1.  Draw Scan Region   →  drag over water only, avoid UI and land
2.  Bobber color       →  click Sample, hover the bobber, press Enter
3.  Splash / Bite      →  wait for a bite flash, hover the cyan glow, press Enter
4.  QTE Indicator      →  optional, only needed if your game shows QTE prompts
```

Green ✓ = ready · Red ✗ = needs attention

---

## ⌨️ Hotkeys

| Action | Default |
|---|---|
| Start / Stop | `Ctrl+Shift+S` |
| Exit | `Ctrl+Shift+X` |

Change any hotkey inside the app — click the button and press your combo.

---

## 📁 Files

```
fishbot.py          main application
build.py            build orchestrator
build.bat           one-click build entry
fishbot.spec        PyInstaller config
requirements.txt    pinned dependencies

bot.log             runtime log (created on first run)
fishbot_config.json your settings (auto-saved)
debug_*.png         vision snapshots for calibration help
```

---

## 🔍 Troubleshooting

**Bot doesn't detect bites**
→ Recalibrate Splash color · increase Splash min px in Settings · check `debug_cast1.png`

**Keyboard hook not working**
→ Run as Administrator

**Build fails on Python 3.14**
→ Install Python 3.11 side-by-side from [python.org](https://python.org/downloads) · re-run `build.bat`

**`system32\build.py` error**
→ Right-click `build.bat` → Run as Administrator · all files must be in the same folder

---

## 📊 Session panel

| Stat | What it means |
|---|---|
| Catches | Successful reels |
| Casts | Total casts |
| Timeouts | Casts that exceeded the timeout and were re-cast |
| QTE | Keystrokes sent during QTE sequences |
| CPH | Catches per hour |
| Runtime | Time since last Start |

---

## 🛠️ Settings reference

| Setting | Default | Notes |
|---|---|---|
| Cast hold | 80 ms | How long the mouse button is held on cast |
| Cast timeout | 40 000 ms | Re-casts if no bite within this window |
| Settle wait | 3 000 ms | Wait after cast before watching for bobber |
| Reel cooldown | 2 500 ms | Pause between catch and next cast |
| Bite confirm frames | 2 | Consecutive frames splash must appear to confirm bite |
| Acquire frames | 3 | Frames bobber must appear before watching for bites |

---

## 📄 License

MIT
```

---

### Design decisions

| Choice | Why |
|---|---|
| One task per section, never nested | Reduces scanning anxiety — you finish a section fully before moving on |
| ✓ / ✗ indicators called out explicitly | No guessing whether setup is done — binary clear state |
| "Take it one step at a time" framing | Non-confrontational pacing, no urgency |
| Troubleshooting is causes + one-line fixes, not paragraphs | Fast resolution, no reading walls when something goes wrong |
| No prerequisites list longer than a table | Walls of version numbers before "hello" create avoidance |
| Build is literally one double-click | Reduces activation energy to zero — nothing to figure out before the reward |
