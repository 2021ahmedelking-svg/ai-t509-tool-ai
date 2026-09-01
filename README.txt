╔══════════════════════════════════════════════════════════════╗
║           SM-T509 Flash Tool  —  Source Package              ║
║           By: Ahmed Abdelrazek                  ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FOLDER STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SM-T509-FlashTool/
  │
  ├── main.py                ← Entry point (do not rename)
  ├── build_exe.py           ← Build script
  ├── build_exe.bat          ← Double-click to build
  │
  ├── core/                  ← Internal logic (do not modify)
  │   ├── __init__.py
  │   ├── config.py          ← Version, paths, theme, steps
  │   ├── security.py        ← Anti-debug protection
  │   ├── fastboot.py        ← Fastboot runner
  │   └── updater.py        ← Auto-update system
  │
  ├── ui/                    ← User interface
  │   ├── __init__.py
  │   ├── widgets.py         ← Buttons, cards, step row
  │   └── app.py             ← Main window
  │
  ├── [YOU ADD THESE ↓]
  │
  ├── fastboot.exe           ← Required
  ├── AdbWinApi.dll          ← Required
  ├── AdbWinUsbApi.dll       ← Required
  ├── libwinpthread-1.dll    ← Required
  ├── product.img            ← Required
  ├── system_ext.img         ← Required
  ├── icon.ico               ← Required (app icon)
  ├── logo.ico               ← Optional
  │
  └── [IMAGES — put here]
      new.png  /  old.png  /  manual.png
      start.png  /  stop.png  /  refresh.png
      browse.png  /  gsi.png  /  telegram.png

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HOW TO BUILD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Add all required files listed above to this folder
  2. Double-click  build_exe.bat
  3. Wait 1–2 minutes
  4. Find your EXE in:  dist\SM-T509-Flash-Tool.exe

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HOW TO RELEASE A NEW VERSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Edit  core/config.py  → change  APP_VERSION = "1.1"
  2. Edit  version.txt  on GitHub → update to:
         1.1
         https://github.com/ahmed-884-s/SM-T509-FlashTool/...
  3. Build the EXE → upload to GitHub Releases
  4. Share the link on Telegram

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
