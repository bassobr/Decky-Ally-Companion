# Changelog

## 0.5.4 (2026-10-08)

- Game profiles: switching on a game's own vibration strength started at 50 % instead of the
  strength set now.
- While a game with its own lighting runs, the brightness in the Quick Access panel changes that
  game's profile. Before, it changed the default, which the game's profile overrides, so nothing
  happened. The Lighting page says that the game sets the lighting and hides its controls; the
  Controller page says that the game has its own vibration strength.
- The pages show a game profile's changes right away: lighting, vibration, CPU boost and fans
  report their state after a profile edit.
- Vibration with separate grips: setting the right grip right after the left one no longer drops
  the left value.
- Audio: "Run setup again" is greyed out while the presets are regenerated; it did nothing then.
- Unused code removed.

## 0.5.3 (2026-10-08)

- CPU boost: switching "CPU boost off" off, or a game profile with boost on, while the cap was
  being re-sent after a charger event could leave the cores capped at the boost-off maximum. The
  switch now waits for the re-send to end before it lifts the cap.
- CPU boost on the Xbox Ally X with SteamOS 3.9.2: after a sleep with boost off, switching boost
  back on (the switch, a game profile with boost on, uninstalling) left the cores at the base clock,
  2.0 instead of up to 5.1 GHz. The kernel's ACPI processor cooling limit is taken from the clock at
  the wake-up and does not follow boost; the plugin now has it recomputed when boost goes back on.
- Fans: in the first seconds after a wake-up, the resume could pin a curve again although pinning
  had just been switched off or the game with its own curve had ended.
- Speaker DSP: a preset conversion cut off by the plugin's unload (reboot, Decky restart, plugin
  update) left presets with mixed extras and the old sound in place; it now runs again on the next
  start. A conversion in which every preset failed is reported as an error instead of "Presets
  regenerated".
- Speaker DSP: if the headphone jack switch goes away, the headphone check goes back to every 3 s
  instead of once a minute.
- Unused code removed.

## 0.5.2 (2026-10-07)

- Lighting on SteamOS 3.9: when the controller came back after the plugin had started (a boot on
  the ROG Ally X, or any re-enumeration), the rings could stay at the driver's default with an
  error in the log. The driver creates the rings about 1.6 s before the interface to the
  controller's MCU, which on Linux 7.2 carries every colour; modules now wait for the driver's
  bind, which comes once both are there.
- Hardware that appears while a late start is running gets a check of its own.
- Unloading the plugin ends running speaker DSP workers; before, they could outlive it and keep
  writing presets.
- Quieter logs: no error about a pending task on every unload, and no warning for the vibration
  re-apply tries that come while the controller driver is still starting.

## 0.5.1 (2026-10-07)

- ROG Ally X: vibration strength and lighting could stay off after a boot. About 6.5 s after
  boot its controller re-enumerates (the driver removes and re-creates the LED rings and the
  gamepad attributes), and Decky can start the plugin right in that gap; the modules then counted
  as unsupported and were not started until the plugin restarted. A module whose hardware is
  missing at the start is now started as soon as it appears.
- Lighting: the rings are set again whenever the driver re-creates them.

## 0.5.0 (2026-10-07)

From a full code review.

Safety limits (they hold for the UI, game profiles, settings files, backups and any local process
calling the plugin through Decky):
- Fans: from 85 °C on, no curve goes below the factory curve of the active thermal profile; below
  that a curve may still be as quiet as wanted. The curve editor says so.
- Headphone EQ: only profiles from AutoEQ's index are fetched; filter values are bounded and the
  preamp is lowered so that a profile can attenuate but never boost (no more than 0 dB anywhere).
- Charge limit: never below steamos-manager's suggested minimum.

Security:
- The root backend no longer reads files below the home that the user could not read: links,
  FIFOs and root-only files planted there are read with the user's permissions (they could copy a
  root-only file into steam_dev.cfg through the gyro fix, or into the audio settings).
- settings.json is written into the real settings directory even if a link replaces it; the data
  directory is deleted as the user on uninstall.
- Every value from settings.json, a backup or a predecessor's settings is checked before use;
  broken values fall back to their defaults instead of stopping the plugin.
- Updates: the zip is checked against the signed hash before Decky's installer gets it (Decky
  removes the installed version before its own check).
- Downloads: ASUS packages and BIOS files without a published SHA-256 are not downloaded;
  numpy/scipy for the converter are hash-pinned wheels without an unpinned fallback.
- install.sh runs its verifier isolated from the directory it was started in.

Fixes:
- Speaker DSP: restoring a backup during setup or a conversion no longer leaves the page stuck at
  "Setting up"; the setup state has its own file, so the worker and the plugin cannot overwrite
  each other's changes.
- Speaker DSP: cancelling the setup really stops it. The conversion used to carry on in the
  background (and could run next to a new setup); now the worker and its download end at once.
- News: a check that finds no network (right after waking up, for instance) is repeated after 30
  minutes instead of six hours, a source that does not answer keeps its last items, and the check
  also runs while the device stays awake.
- Fans: switching the pinning off (or a game's curve ending) also loads the factory curve back into
  the fan curve registers.
- After sleep all modules re-apply at once: the rings no longer wait for the fan to settle.
- Lighting: changes arriving together (resume, game profile, slider) no longer mix their packets.
- A slider moved right before the Quick Access panel closes keeps its value.
- Steam is only restarted when the change that needs it succeeded.
- Removing a game's settings or sound preset asks first.
- A slow ASUS download no longer stalls the setup.

Efficiency:
- The headphone jack is followed through the codec's switch events instead of reading PipeWire's
  graph every three seconds (that alone used 1.6 % of a CPU core all the time); the headphone EQ
  likewise. A status refresh starts far fewer processes.

Maintenance:
- CI runs the backend tests on Python 3.11, 3.13 and 3.14 and rebuilds the Steam client shim in a
  pinned container to check the committed binary. The shim only touches read-only data pages.
- Typed module details in the frontend; Steam's loaded modules are searched before any factory is
  run.

## 0.4.5 (2026-10-06)

SteamOS 3.9.2 (beta):
- Lighting: Linux 7.2 caps each LED value at 255, which cut the packed ring colours down to their
  blue part; after sleep the driver painted the rings blue. Static colours now go to the controller
  directly (like the effects) whenever the kernel has that cap.
- Speaker DSP: the setup no longer needs `lv2ls`, which SteamOS 3.9 dropped; it reads the LV2
  manifests itself. With that, the setup rebuilds the converter environment for Python 3.14 on its
  own, so changing the extras works again.

## 0.4.4 (2026-10-05)

- Fans: SteamOS 3.9.2 fixes the high fan speed after sleep on ASUS devices itself. From that
  version on the plugin no longer pins the fan curve, and the switch is greyed out with a note;
  the setting is kept for older versions. A game profile's own fan curve is still pinned while
  the game runs. The curve editor on the Power page goes with the pinning.

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
