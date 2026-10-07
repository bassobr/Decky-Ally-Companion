"""Filesystem layout. Everything audio lives below the plugin's data directory in `audio/`,
owned by the Decky user and written as that user: the worker writes the setup state (setup.json),
the downloads, the venv, the presets and the unit; the backend writes settings.json through a
child process running as the user."""
from __future__ import annotations

import os

from .constants import PLUGIN_NAME


def _plugin_dir_default() -> str:
    here = os.path.dirname(os.path.abspath(__file__))  # .../py_modules/allydsp
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


HOME = os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")
USER = os.environ.get("DECKY_USER") or os.environ.get("USER") or "deck"
PLUGIN_DIR = os.environ.get("ALLYCOMPANION_PLUGIN_DIR") or os.environ.get("DECKY_PLUGIN_DIR") or _plugin_dir_default()
DATA_DIR = os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or os.path.join(HOME, "homebrew", "data", PLUGIN_NAME)
LOG_DIR = os.environ.get("DECKY_PLUGIN_LOG_DIR") or os.path.join(HOME, "homebrew", "logs", PLUGIN_NAME)

RUNTIME_DIR = os.path.join(DATA_DIR, "audio")
SETTINGS_DIR = RUNTIME_DIR
SETTINGS_FILE = os.path.join(RUNTIME_DIR, "settings.json")
SETUP_FILE = os.path.join(RUNTIME_DIR, "setup.json")
DAX3_DIR = os.path.join(RUNTIME_DIR, "dax3")
VENV_DIR = os.path.join(RUNTIME_DIR, "venv")
PRESETS_DIR = os.path.join(RUNTIME_DIR, "presets")
ACTIVE_DIR = os.path.join(RUNTIME_DIR, "active")
TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
PROVENANCE_FILE = os.path.join(DAX3_DIR, "provenance.json")

DEFAULTS_DIR = os.path.join(PLUGIN_DIR, "defaults")
CONVERTER_DIR = os.path.join(DEFAULTS_DIR, "converter")
LV2_DIR = os.path.join(PLUGIN_DIR, "bin", "lv2")
UNIT_TEMPLATE = os.path.join(DEFAULTS_DIR, "ally-companion-dsp.service.tmpl")
FALLBACK_SOURCES = os.path.join(DEFAULTS_DIR, "fallback-sources.json")
CONVERTER_REQUIREMENTS = os.path.join(DEFAULTS_DIR, "converter-requirements.txt")

UNIT_NAME = "ally-companion-dsp.service"
UNIT_PATH = os.path.join(HOME, ".config", "systemd", "user", UNIT_NAME)
SYSTEM_PYTHON = "/usr/bin/python3"

# Ally DSP's data, imported once so setup does not download the tuning and the venv again.
LEGACY_RUNTIME_DIR = os.path.join(HOME, "homebrew", "data", "Ally DSP")


def ensure_dirs() -> None:
    for d in (RUNTIME_DIR, DAX3_DIR, PRESETS_DIR, ACTIVE_DIR, TMP_DIR, os.path.dirname(UNIT_PATH)):
        os.makedirs(d, exist_ok=True)
