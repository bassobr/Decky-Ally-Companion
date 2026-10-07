# Ally Companion

Decky Loader plugin for the **ROG Xbox Ally X** (RC73XA) and **ROG Ally X** (RC72LA) on SteamOS:
one place for the hardware features that Armoury Crate covers on Windows and Handheld Daemon on
other distributions. It builds on what SteamOS already ships (InputPlumber, steamos-manager, the
ASUS kernel drivers) instead of replacing it, and it replaces two earlier plugins:
[Ally DSP](https://github.com/bassobr/decky-ally-dsp) and [Ally Fix](https://github.com/lonsdaleite/Ally-Fix).

Tested on both devices; see [Tested devices](#tested-devices) for the few differences.

| Page | What it does |
|---|---|
| Overview | Device, system interfaces, live sensor values, CPU boost state |
| Audio | Dolby speaker tuning from ASUS' own driver package as a PipeWire filter chain (profiles, voicings, per-game presets, leveler, dialog enhancer, pre-gain, pause on headphones); microphone noise suppression (RNNoise); headphone EQ with AutoEQ profiles |
| Controller | Grip vibration strength, Enhanced Vibration, rumble on the impulse triggers, gyro axis fix for Steam Input, Steam Input layout without trackpads and phantom rear buttons, reconnect after a hang |
| Lighting | Joystick rings: static colour, breathing, colour cycle, rainbow, battery level display |
| Power & battery | CPU boost off (on the Xbox Ally X with the frequency cap kept after charger events), fan curve pinning against fans stuck at full speed after sleep (up to SteamOS 3.9.1; 3.9.2 fixes this itself) and custom curves per profile (from 85 °C never below the factory curve), charge limit and "charge to 100 % once", battery health with daily history, controller power saving in sleep, boot sound |
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

## Tested devices

| Device | Board | APU | Tested with |
|---|---|---|---|
| ROG Xbox Ally X | RC73XA | Ryzen AI Z2 Extreme | BIOS 317, SteamOS 3.8.28 and 3.9.2 beta, Decky Loader 3.2.10-pre1 |
| ROG Ally X | RC72LA | Ryzen Z1 Extreme | BIOS 312, SteamOS 3.8.28, Decky Loader 3.2.9 |

All pages work on both. Differences:

- **Rumble on the impulse triggers** is Xbox Ally X only; the Ally X has no trigger motors.
  Enhanced Vibration works on both.
- **CPU boost**: on the Xbox Ally X the firmware drops the frequency cap on every charger plug and
  the plugin re-sends it. On the Ally X the cap holds (measured), so only "keep boost off" is
  offered there.
- **Gyro fix** on the Ally X: InputPlumber presents it with the same controller id and sensor
  orientation as the Xbox Ally X, and the fix applies and reverts the same way. The axes in Steam
  have not been checked by hand there yet.

Other models (the original ROG Ally, the ROG Xbox Ally) are not targeted. Open checks are listed in
[docs/roadmap.md](docs/roadmap.md).

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
python3 -m pytest tests -q                 # backend (CI: Python 3.11, 3.13, 3.14)
scripts/assemble-converter.sh              # copy the converter from the submodule
scripts/fetch-lsp.sh                       # bundle the LSP LV2 plugins
DECK_SUDO_PASS=... scripts/dev-deploy.sh deck@<ip>   # copy to the handheld, restart Decky
shim/build.sh                              # Steam client shim in a pinned container (podman;
                                           # CONTAINER_ENGINE=docker works too), reproducible
```

Architecture and the interfaces found on the device: [docs/architecture.md](docs/architecture.md).
Plan and open points: [docs/roadmap.md](docs/roadmap.md).

Releases: tag `vX.Y.Z` matching `package.json`. GitHub Actions builds, tests, packages
`ally-companion-X.Y.Z.zip`, signs `SHA256SUMS` with the `MINISIGN_SEED` secret and publishes the
release.

## License

MIT. Third-party code and binaries: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
