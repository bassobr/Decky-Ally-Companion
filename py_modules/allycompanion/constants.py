"""Static configuration shared by backend, CLI and tests."""
from __future__ import annotations

PLUGIN_NAME = "Ally Companion"
GITHUB_REPO = "bassobr/Decky-Ally-Companion"
RELEASE_ZIP_TEMPLATE = "ally-companion-{version}.zip"
USER_AGENT = "ally-companion/decky (+https://github.com/bassobr/Decky-Ally-Companion)"

# DMI board name -> display name. Everything else runs with every module reporting "not supported".
BOARDS = {
    "RC73XA": "ROG Xbox Ally X",
    "RC72LA": "ROG Ally X",
}

UPDATE_CHECK_INTERVAL_S = 6 * 3600
UPDATE_RETRY_S = 30 * 60

INPUTPLUMBER_BUS = "org.shadowblip.InputPlumber"
INPUTPLUMBER_MANAGER = "/org/shadowblip/InputPlumber/Manager"
STEAMOS_MANAGER_BUS = "com.steampowered.SteamOSManager1"
STEAMOS_MANAGER_PATH = "/com/steampowered/SteamOSManager1"
