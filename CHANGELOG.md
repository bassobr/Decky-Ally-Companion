# Changelog

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
