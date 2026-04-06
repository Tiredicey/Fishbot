## 🎣 FishBot

Automated fishing bot for Roblox with a dark-themed GUI, real-time detection, and zero-config persistence.

---

## ✨ Features

- **Automated Fishing:** Casts, waits, detects bites via cyan splash detection, and reels automatically.  
- **Visual Calibration:** Click pixels to configure—no code editing required.  
- **Live Dashboard:** Custom hotkeys, session stats, and live state display.  
- **Zero-Config Persistence:** Configuration auto-saves between sessions.

---

## 🖥️ Requirements

| Prerequisite | Details |
| :--- | :--- |
| **OS** | Windows 10 / 11 |
| **Python** | 3.9 – 3.12 recommended (3.14 may run with warnings) |
| **Roblox** | Running before launching FishBot |

---

## 🚀 Quick Start

1. Clone or download the repository.
2. Double-click `build.bat`.
3. Right-click `dist/FishBot.exe` → **Run as Administrator**.

Note: The build script creates a venv and installs required packages automatically.

---

## ⚙️ First-Time Setup (In-App)

Status indicators: **Green ✓** = Ready · **Red ✗** = Needs attention

### Calibration Panel
1. **Draw Scan Region:** Drag over water only; avoid UI and land.  
2. **Bobber Color:** Click *Sample*, hover over bobber, press Enter.  
3. **Splash / Bite:** Wait for bite flash, hover over cyan glow, press Enter.  
4. **QTE Indicator (Optional):** Only if the game shows Quick Time Event prompts.

---

## ⌨️ Hotkeys

| Action | Default |
| :--- | :--- |
| **Start / Stop** | Ctrl + Shift + S |
| **Exit** | Ctrl + Shift + X |

Change hotkeys inside the app by clicking the button and pressing a new combo.

---

## 📁 Project Layout

Source & Build
- fishbot.py          — Main application
- build.py            — Build orchestrator
- build.bat           — One-click build entry
- fishbot.spec        — PyInstaller config
- requirements.txt    — Pinned dependencies

Generated at runtime
- bot.log             — Runtime log (created on first run)
- fishbot_config.json — Saved settings
- debug_*.png         — Vision snapshots for calibration

---

## 📊 Session Panel (Stats)

- Catches — Successful reels  
- Casts — Total casts made  
- Timeouts — Casts that exceeded timeout and were re-cast  
- QTE — Keystrokes sent during QTEs  
- CPH — Catches Per Hour  
- Runtime — Time elapsed since last Start

---

## 🛠️ Settings Reference

| Setting | Default | Notes |
| :--- | :---: | :--- |
| Cast hold | 80 ms | Mouse hold duration for cast |
| Cast timeout | 40,000 ms | Re-cast if no bite within this window |
| Settle wait | 3,000 ms | Wait after cast before detecting |
| Reel cooldown | 2,500 ms | Pause between a catch and next cast |
| Bite confirm | 2 frames | Consecutive frames splash must appear |
| Acquire frames | 3 frames | Frames bobber must appear before watching |

---

## 🔍 Troubleshooting

- Bot doesn't detect bites: recalibrate Splash color → increase "Splash min px" in Settings → check debug_*.png.  
- Keyboard hook not working: close app and Run as Administrator.  
- Build fails on Python 3.14: install Python 3.11 and re-run build.bat.  
- system32\build.py error: Run build.bat as Administrator and ensure all files are in the same folder.

---

## 🧾 License

MIT

---

## 🧠 Design Philosophy

- One task per section to reduce friction.  
- Binary ✓ / ✗ setup indicators for clarity.  
- Stepwise onboarding: “Take it one step at a time.”  
- Troubleshooting: causes + one-line fixes.  
- Minimal prerequisites and one-click build to lower activation energy.

---

