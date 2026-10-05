# Ally Companion

Decky Loader plugin for the **ROG Xbox Ally X** (RC73XA) and **ROG Ally X** (RC72LA) on SteamOS:
one place for the hardware features that Armoury Crate covers on Windows and Handheld Daemon on
other distributions. It builds on what SteamOS already ships (InputPlumber, steamos-manager, the
ASUS kernel drivers) instead of replacing it, and it replaces two earlier plugins:
[Ally DSP](https://github.com/bassobr/decky-ally-dsp) and [Ally Fix](https://github.com/lonsdaleite/Ally-Fix).

Verified on the ROG Xbox Ally X and the ROG Ally X (SteamOS 3.8.28). Enhanced Vibration and the
rumble on the impulse triggers are Xbox Ally X only.

| Page | What it does |
|---|---|
| Overview | Device, system interfaces, live sensor values, CPU boost state |
| Audio | Dolby speaker tuning from ASUS' own driver package as a PipeWire filter chain (profiles, voicings, per-game presets, leveler, dialog enhancer, pre-gain, pause on headphones); microphone noise suppression (RNNoise); headphone EQ with AutoEQ profiles |
| Controller | Grip vibration strength, Enhanced Vibration, rumble on the impulse triggers, gyro axis fix for Steam Input, Steam Input layout without trackpads and phantom rear buttons, reconnect after a hang |
| Lighting | Joystick rings: static colour, breathing, colour cycle, rainbow, battery level display |
| Power & battery | CPU boost off with the frequency cap kept after charger events, fan curve pinning and custom curves per profile, charge limit and "charge to 100 % once", battery health with daily history, controller power saving in sleep, boot sound |
| Game profiles | Per-game lighting, vibration strength, performance profile, CPU boost and fan curve (per-game sound lives on the Audio page) |
| News | SteamOS releases of the installed channel with the Ally-related changes, BIOS for the board (EZ Flash download), known issues; new items as a toast |
| System | Plugin updates, settings backup and restore, diagnostics |

The Quick Access panel only holds what changes during a game: a status line, the sound preset for
the running game, the light brightness and a Steam restart button when a change needs one.
Everything else is in the fullscreen view (Quick Access → Ally Companion → All settings, or
Steam's Settings → Ally Companion).

Coming from Ally Fix or Ally DSP: install Ally Companion, then uninstall the old plugin in Decky.
Until then the matching pages stay passive. Settings, the Dolby tuning and the converter
environment are taken over; nothing has to be set up again.

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
git submodule update --init                # converter (speaker-tuning-to-easyeffects)
pnpm install && pnpm build                 # frontend
python3 -m pytest tests -q                 # backend (Python 3.9+)
scripts/assemble-converter.sh              # copy the converter from the submodule
scripts/fetch-lsp.sh                       # bundle the LSP LV2 plugins
DECK_SUDO_PASS=... scripts/dev-deploy.sh deck@<ip>   # copy to the handheld, restart Decky
```

Architecture and the interfaces found on the device: [docs/architecture.md](docs/architecture.md).
Plan and open points: [docs/roadmap.md](docs/roadmap.md).

Releases: tag `vX.Y.Z` matching `package.json`. GitHub Actions builds, tests, packages
`ally-companion-X.Y.Z.zip`, signs `SHA256SUMS` with the `MINISIGN_SEED` secret and publishes the
release.

## License

MIT. Third-party code and binaries: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
