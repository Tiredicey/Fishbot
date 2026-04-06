# 🎣 FishBot

Automated fishing bot for Roblox with a dark-themed GUI, real-time detection, and zero-config persistence.

---

## ✨ What it does

- **Automated Fishing:** Casts, waits, detects bites via cyan splash detection, and reels automatically.
- **Visual Calibration:** Click pixels to configure—no code editing required.
- **Live Dashboard:** Custom hotkeys, session stats, and live state display.
- **Zero-Config Persistence:** Configuration auto-saves seamlessly between sessions.

---

## 🖥️ Requirements

| Prerequisite | Details |
| :--- | :--- |
| **OS** | Windows 10 / 11 |
| **Python** | 3.9 – 3.12 recommended · *3.14 attempts with warning* |
| **Roblox** | Must be running *before* you launch FishBot |

---

## 🚀 Quick Start

1. Download or clone this repository.
2. Double-click `build.bat`.
3. Right-click `dist/FishBot.exe` → **Run as Administrator**.

> **Note:** That's it. The build system handles the virtual environment and all dependencies automatically.

---

## ⚙️ First-Time Setup (In-App)

Take it one step at a time. Each step has a status indicator so you always know your setup state:
**Green `✓`** = Ready · **Red `✗`** = Needs attention

### Calibration Panel
1. **Draw Scan Region:** Drag over water only. Avoid UI elements and land.
2. **Bobber Color:** Click *Sample*, hover over the bobber, and press `Enter`.
3. **Splash / Bite:** Wait for a bite flash, hover over the cyan glow, and press `Enter`.
4. **QTE Indicator:** *(Optional)* Only needed if your game shows Quick Time Event prompts.

---

## ⌨️ Hotkeys

| Action | Default |
| :--- | :--- |
| **Start / Stop** | `Ctrl + Shift + S` |
| **Exit** | `Ctrl + Shift + X` |

*Tip: Change any hotkey inside the app—just click the button and press your desired combo.*

---




Here is the fully fixed structure. The markdown formatting broke halfway through your document (starting at the end of the file tree where the code block wasn't closed properly), which corrupted the headers, tables, and spacing for the rest of the file. 

I have restored the proper markdown headers, tables, blockquotes, and dividers. It is ready to copy and paste.

```markdown
# 🎣 FishBot

Automated fishing bot for Roblox with a dark-themed GUI, real-time detection, and zero-config persistence.

---

## ✨ What it does

- **Automated Fishing:** Casts, waits, detects bites via cyan splash detection, and reels automatically.
- **Visual Calibration:** Click pixels to configure—no code editing required.
- **Live Dashboard:** Custom hotkeys, session stats, and live state display.
- **Zero-Config Persistence:** Configuration auto-saves seamlessly between sessions.

---

## 🖥️ Requirements

| Prerequisite | Details |
| :--- | :--- |
| **OS** | Windows 10 / 11 |
| **Python** | 3.9 – 3.12 recommended · *3.14 attempts with warning* |
| **Roblox** | Must be running *before* you launch FishBot |

---

## 🚀 Quick Start

1. Download or clone this repository.
2. Double-click `build.bat`.
3. Right-click `dist/FishBot.exe` → **Run as Administrator**.

> **Note:** That's it. The build system handles the virtual environment and all dependencies automatically.

---

## ⚙️ First-Time Setup (In-App)

Take it one step at a time. Each step has a status indicator so you always know your setup state:
**Green `✓`** = Ready · **Red `✗`** = Needs attention

### Calibration Panel
1. **Draw Scan Region:** Drag over water only. Avoid UI elements and land.
2. **Bobber Color:** Click *Sample*, hover over the bobber, and press `Enter`.
3. **Splash / Bite:** Wait for a bite flash, hover over the cyan glow, and press `Enter`.
4. **QTE Indicator:** *(Optional)* Only needed if your game shows Quick Time Event prompts.

---

## ⌨️ Hotkeys

| Action | Default |
| :--- | :--- |
| **Start / Stop** | `Ctrl + Shift + S` |
| **Exit** | `Ctrl + Shift + X` |

*Tip: Change any hotkey inside the app—just click the button and press your desired combo.*

---

## 📁 Files

```text
├── Source & Build
│   ├── fishbot.py          # Main application
│   ├── build.py            # Build orchestrator
│   ├── build.bat           # One-click build entry
│   ├── fishbot.spec        # PyInstaller config
│   └── requirements.txt    # Pinned dependencies
│
└── Generated at Runtime
    ├── bot.log             # Runtime log (created on first run)
    ├── fishbot_config.json # Your settings (auto-saved)
    └── debug_*.png         # Vision snapshots for calibration help
```

---

## 🔍 Troubleshooting

**Bot doesn't detect bites**
> Recalibrate Splash color → Increase Splash min px in Settings → Check `debug_cast1.png`

**Keyboard hook not working**
> Close the app and **Run as Administrator**.

**Build fails on Python 3.14**
> Install Python 3.11 side-by-side from [python.org](https://python.org/downloads) → re-run `build.bat`

**`system32\build.py` error**
> Right-click `build.bat` → **Run as Administrator**. Ensure all files are extracted to the same folder.

---

## 📊 Session Panel

| Stat | What it means |
| :--- | :--- |
| **Catches** | Successful reels |
| **Casts** | Total casts made |
| **Timeouts** | Casts that exceeded the timeout limit and were re-cast |
| **QTE** | Keystrokes sent during QTE sequences |
| **CPH** | Catches Per Hour |
| **Runtime** | Time elapsed since last Start |

---

## 🛠️ Settings Reference

| Setting | Default | Notes |
| :--- | :--- | :--- |
| **Cast hold** | `80 ms` | How long the mouse button is held on cast |
| **Cast timeout** | `40,000 ms` | Re-casts if no bite occurs within this window |
| **Settle wait** | `3,000 ms` | Wait time after cast before watching for the bobber |
| **Reel cooldown** | `2,500 ms` | Pause duration between a catch and the next cast |
| **Bite confirm** | `2 frames`| Consecutive frames splash must appear to confirm a bite |
| **Acquire frames**| `3 frames`| Frames bobber must appear before watching for bites |

---

## 📄 License

MIT

---

## 🧠 Design Philosophy

*For developers and contributors, here is the rationale behind FishBot's UX:*

| Choice | Rationale |
| :--- | :--- |
| **One task per section, never nested** | Reduces scanning anxiety. Users finish a section fully before moving on. |
| **`✓` / `✗` indicators called out** | No guessing whether setup is done—binary, clear state. |
| **"Take it one step at a time" framing**| Non-confrontational pacing; creates zero urgency. |
| **Troubleshooting = Causes + 1-line fixes**| Fast resolution. No walls of text when something goes wrong. |
| **No prerequisites longer than a table** | Walls of version numbers before "hello" create task avoidance. |
| **Build is literally one double-click** | Reduces activation energy to zero—nothing to figure out before the reward. |
```
