# Changelog

## 0.4.3 (2026-10-05)

- Enhanced Vibration on the ROG Ally X: its controller has it too (the difference is noticeable),
  so the toggle and the rumble cap are available there. Rumble on the impulse triggers stays Xbox
  Ally X only.

## 0.4.2 (2026-10-05)

- README: tested devices with firmware and software versions, and what differs between the ROG
  Xbox Ally X and the ROG Ally X.

## 0.4.1 (2026-10-05)

- CPU boost on the ROG Ally X: the frequency cap survives charger events there (measured with
  loaded cores across unplug and replug), so the cap refresh is greyed out and no longer runs.
  Keeping boost off still works (base clock 3.3 GHz instead of up to 5.1 GHz).

## 0.4.0 (2026-10-05)

- ROG Ally X (RC72LA): the gyro fix and the gamepad layout fix are available there too. The gyro
  fix overrides the Ally X's own InputPlumber config (`50-rog_ally_x.yaml`); deck emulation keeps
  the device's name with "(Deck Emulation)" appended. Everything else was already enabled and is
  now tested on the device.

## 0.3.2 (2026-10-04)

- Power & battery: charge, battery power, fan speed, CPU temperature and thermal profile follow the
  live values (every 2 s while the page is open) instead of the state from when the plugin
  loaded. The battery power is labelled by what it is: charging power while charging, power draw
  while on battery.
- Every page of the fullscreen view fetches the plugin state when it opens.

## 0.3.1 (2026-10-04)

Security (found in a review; a process running as the Decky user could gain root):
- The uninstall cleanup code is staged in /run (root only) instead of the user-owned data
  directory it was executed from as root.
- The root backend no longer writes into the user's directories itself (Steam client shim and
  drop-in, steam_dev.cfg, backups, diagnostics, audio configs and units, BIOS download): a child
  process running as the user does, so symlinks planted there cannot redirect root's writes.
- BIOS download entries are checked before they become paths or URLs.
- Updates: signatures are checked in memory, the release is asked for afresh before installing, and
  only a newer version from this repository's releases is accepted (no downgrade through a planted
  cache entry).
- install.sh verifies with a pinned public key and a verifier from the repository, not with key and
  code from the zip it checks.
- Fan curves from the settings file are range-checked before they reach sysfs.

Fixes:
- Restoring a backup keeps a running "charge to 100 % once", the battery history and the
  performance profile to restore after a game.
- The CPU boost and fan switches respect a running game's profile.
- A charge limit set by hand (or in Steam) ends "charge to 100 % once" instead of being
  overwritten when the battery is full; the full charge is only marked once the limit is lifted.
- The list of performance profiles is asked again when steamos-manager was not up at start.

## 0.3.0 (2026-10-04)

- Steam's settings menu has an "Ally Companion" entry that opens the fullscreen view.
- Overview: live values (CPU and GPU temperature and clocks, APU power, battery, fans, power
  profile, PPT) and a CPU boost block (state, frequency cap, cores above the cap, last re-send);
  polled only while the page is open.
- Audio: microphone noise suppression (RNNoise, the cleaned microphone becomes the default source)
  and a headphone EQ with AutoEQ profiles for wired, Bluetooth or USB headphones.
- Game profiles: performance profile, CPU boost and fan curve per game, besides lighting and
  vibration.
- Battery: charge to 100 % once (the limit comes back when full) and a daily health history.
- News: new SteamOS releases, BIOS versions and known issues show up as a toast once.
- System: back up all settings to ~/Documents/Ally Companion and restore them.
- Controller: "Reconnect the controller" restarts InputPlumber and re-sends vibration and lighting.
- Fix: values like -1 (no charge limit) reach steamos-manager; busctl took them for options.

## 0.2.2 (2026-10-04)

- Fullscreen view: the D-pad moves one menu entry per press again; the separators in the side menu
  made Steam's navigation skip every other entry and show the page behind the focus.

## 0.2.1 (2026-10-04)

- Uninstall also reverts the gamepad layout and the speaker DSP unit: the cleanup no longer skips
  modules whose support check looks for plugin files that are already gone.

## 0.2.0 (2026-10-04)

- Audio: Dolby speaker tuning from Ally DSP (setup, profiles and voicings, per-game presets,
  extras, pre-gain, pause on headphones); writes run in a worker as the Decky user.
- Controller (from Ally Fix): grip vibration strength, Enhanced Vibration, rumble cap and trigger
  rumble (HID-BPF), gyro fix for Steam Input, Steam Input layout without trackpads and the
  phantom rear buttons.
- Power & battery: CPU boost off with the cap kept after charger events, fan curve pinning (from
  Ally Fix) and custom curves, charge limit through steamos-manager, battery health, controller
  power saving in sleep, boot sound.
- Lighting: static colours, breathing, colour cycle, rainbow, battery level display.
- Game profiles: per-game lighting and vibration strength.
- News: SteamOS releases of the installed channel, BIOS and firmware for the board with an EZ Flash
  download, known issues.
- Takeover from Ally Fix and Ally DSP: their pages stay passive while they are installed; settings,
  tuning, venv, overrides and drop-ins are taken over once they are gone.
- Uninstall reverts the modules from a transient timer, so updates do not revert anything.

## 0.1.0 (unreleased)

- Skeleton: root backend with a user-session boundary, module registry, resume detection, D-Bus
  access through busctl, device and interface probe, Quick Access panel and fullscreen view, signed
  updates, diagnostics, CLI.
