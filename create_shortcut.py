"""
Generates PulseMind's custom .ico file and creates a Windows Desktop shortcut
dynamically using the active Python interpreter (`sys.executable` / `pythonw.exe`),
so it works on any user's Windows PC without hardcoded paths.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tray import create_tray_icon_image

BASE_DIR = Path(__file__).resolve().parent
ICO_PATH = BASE_DIR / "static" / "pulsemind.ico"
TRAY_SCRIPT = BASE_DIR / "tray.py"


def build_ico() -> Path:
    img = create_tray_icon_image(active=True)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(ICO_PATH), format="ICO", sizes=[(64, 64), (48, 48), (32, 32), (16, 16)])
    return ICO_PATH


def create_desktop_shortcut() -> Path:
    ico = build_ico()
    current_py = Path(sys.executable).resolve()
    pythonw_candidate = current_py.with_name("pythonw.exe")
    target_exe = pythonw_candidate if pythonw_candidate.exists() else current_py

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $DesktopPath 'PulseMind.lnk'
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = '{target_exe}'
$Shortcut.Arguments = '"{TRAY_SCRIPT}"'
$Shortcut.WorkingDirectory = '{BASE_DIR}'
$Shortcut.IconLocation = '{ico},0'
$Shortcut.Description = 'Launch PulseMind Spotify Tracker & Sonic DNA Studio'
$Shortcut.Save()
Write-Output $ShortcutPath
"""
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps_script],
        text=True,
    ).strip()
    return Path(out)


if __name__ == "__main__":
    shortcut_path = create_desktop_shortcut()
    print(f"Created Desktop shortcut at: {shortcut_path}")
