# Ally Companion

Decky Loader plugin for the **ROG Xbox Ally X** (RC73XA) and **ROG Ally X** (RC72LA) on SteamOS:
one place for the hardware features that Armoury Crate covers on Windows and Handheld Daemon on
other distributions. It builds on what SteamOS already ships (InputPlumber, steamos-manager, the
ASUS kernel drivers) instead of replacing it.

Status: **0.1.0 skeleton.** The plugin shows the device and the system interfaces it found; the
feature modules arrive one by one, see [docs/roadmap.md](docs/roadmap.md).

Planned modules:

- **Audio**: Dolby speaker tuning as a PipeWire filter chain (from
  [Ally DSP](https://github.com/bassobr/decky-ally-dsp))
- **Controller**: vibration, gyro and layout fixes (from
  [Ally Fix](https://github.com/lonsdaleite/Ally-Fix)), deadzones, response curves, remapping
- **Lighting**: joystick ring color, effects and state lighting
- **Power & battery**: CPU boost and fan fixes, fan curves, charge limit
- **News**: SteamOS releases, BIOS updates for the board, known issues
- **Game profiles**: per-game overrides of all of the above

The Quick Access panel shows only what you change during a game; everything else lives in a
fullscreen view (Quick Access → Ally Companion → All settings).

## Install

Requires Decky Loader. In Desktop Mode, open Konsole:

```bash
curl -sL https://github.com/bassobr/Decky-Ally-Companion/raw/main/install.sh -o /tmp/ally-companion-install.sh && sudo bash /tmp/ally-companion-install.sh
```

Updates are offered in the plugin (System page). The plugin runs as root (Decky flag `root`);
see [SECURITY.md](SECURITY.md).

## Command line

```bash
cd ~/homebrew/plugins/"Ally Companion"
sudo PYTHONPATH=py_modules python3 -m allycompanion.cli info
sudo PYTHONPATH=py_modules python3 -m allycompanion.cli diagnostics
```

## Development

```bash
pnpm install && pnpm build                 # frontend
python3 -m pytest tests -q                 # backend (Python 3.9+)
DECK_SUDO_PASS=... scripts/dev-deploy.sh deck@<ip>   # copy to the handheld, restart Decky
```

Architecture and the interfaces found on the device: [docs/architecture.md](docs/architecture.md).

Releases: tag `vX.Y.Z` matching `package.json`. GitHub Actions builds, tests, packages
`ally-companion-X.Y.Z.zip`, signs `SHA256SUMS` with the `MINISIGN_SEED` secret and publishes the
release.

## License

MIT. Third-party code: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
