# Architecture

Ally Companion is a Decky Loader plugin with a Python backend (`py_modules/allycompanion`, plus the
speaker DSP in `py_modules/allydsp`) and a React frontend (`src/`). It does for SteamOS what
Handheld Daemon does elsewhere, but it does not emulate a controller: InputPlumber does that on
SteamOS (and on Bazzite since Bazzite 44), and steamos-manager does power management. The plugin
builds on those two services and on the ASUS kernel drivers.

```
Decky Loader ── backend "Ally Companion" (root, flag "root")
                 ├─ registry     modules, conflicts with other plugins, lifecycle fan-out
                 ├─ modules      audio, vibration, gyro, gamepad_layout, cpu_boost, fan, battery,
                 │               lighting, profiles, news
                 ├─ resume       suspend detection (CLOCK_BOOTTIME − CLOCK_MONOTONIC)
                 ├─ uevent       netlink kobject uevents (charger, hid re-enumeration)
                 ├─ dbus         busctl --json: InputPlumber (system bus), steamos-manager (session bus)
                 ├─ util.run     root by default; as_user=True drops to the Decky user's session
                 ├─ userfs       file operations below the home, done by a child as the user
                 ├─ ally_hid     MCU feature reports on the controller's config interface
                 ├─ hidbpf       rumble packet filter (HID-BPF struct_ops via libbpf)
                 ├─ steam        steam-launcher.service, client process, drop-in helpers
                 ├─ migrate      one-time import of Ally Fix settings
                 ├─ cleanup      deferred uninstall (transient systemd timer)
                 └─ updater      GitHub Releases + minisign, installation through Decky
 allydsp.worker (as the user) ── setup, conversion, presets, systemd user unit of the DSP
Frontend ── Quick Access panel: status, sound preset for the running game, light brightness
         ── route /ally-companion/<page>: SidebarNavigation (Overview, Audio, Controller, Lighting,
            Power & battery, Game profiles, News, System)
         ── layoutPatch.ts / controllerArt.ts: the Steam-side half of the gamepad layout module
         ── appWatcher.ts: reports the running game (per-game presets and profiles)
         ── settingsEntry.tsx: an entry in Steam's own settings menu (route patch on /settings)
```

## UI rule

The Quick Access panel holds only what changes during a game and depends on the running game.
Everything that is set once lives in the fullscreen view. `SidebarNavigation` keeps the page in the
path (`/ally-companion/<id>`), so the route is registered without `exact`; deep links open a page.

## Modules

`module.Module` (adapted from Ally Fix's `Fix`): one settings section under `modules.<id>`,
`supported()`, and for toggle modules `apply()` / `revert()` / `is_applied()`. Status states:
applied, not_applied, error, stale, restart_pending, not_supported, info, blocked. Hooks:
`prepare(blocked_by)` (also while blocked), `start`, `stop`, `on_resume`, `on_app_changed`,
`uninstall`, and named `actions()` the UI calls through `module_action`. The frontend talks to all
modules through four calls: `get_state`, `set_module_enabled`, `set_module_options`,
`module_action`; the backend pushes `module_status`, `modules` and `audio_progress` events.

| Module | Source | Touches |
|---|---|---|
| audio | Ally DSP | `~/homebrew/data/Ally Companion/audio`, `~/.config/systemd/user/ally-companion-dsp.service` |
| mic | new | `audio/mic.conf`, `ally-companion-mic.service`: RNNoise (NoiseTorch's `nt-filter` LADSPA build that SteamOS ships) in its own PipeWire process; the cleaned source has session priority 2500, above Valve's loopback source (2010), so it becomes the default |
| headphones | new | `audio/hp.conf`, `ally-companion-hp.service`: AutoEQ ParametricEQ as built-in biquads, smart filter on the headphone sink; runs only while the headphone route (wired) or the chosen sink (Bluetooth, USB) is in use |
| vibration | Ally Fix | MCU `5A D1 06` / `5A D1 1F`, `vibration_intensity`, HID-BPF on the gamepad interface |
| gyro | Ally Fix | `/etc/inputplumber/devices.d/50-rog_xbox_ally.yaml`, Steam's `steam_dev.cfg` (complex mode) |
| gamepad_layout | Ally Fix | `~/.local/lib/ally-companion/`, drop-in `zz-ally-companion-gamepad-layout.conf` of steam-launcher.service |
| cpu_boost | Ally Fix | `cpufreq/boost`, `scaling_max_freq` of every policy |
| fan | Ally Fix + new | `asus_custom_fan_curve` hwmon (`pwm*_enable`, auto points) |
| battery | new | steamos-manager `BatteryChargeLimit1`, asus-armoury `mcu_powersave`, `boot_sound` |
| lighting | new | `ally:rgb:joystick_rings` LED class, MCU `5A B3/B4/B5/BA` effects |
| profiles | new | overrides of lighting, vibration, CPU boost and fan while a game runs; the performance profile through steamos-manager (Steam keeps one global platform profile; the one at game start is restored) |
| news | new | Steam news API, ASUS support API, `news/known-issues.json` of this repository |

## Smart filters and Valve's loopback source

WirePlumber smart filters work for the speaker DSP and the headphone EQ (sinks), but not in front
of the internal microphone: Valve's WirePlumber puts a loopback source (`alsa_loopback_device.*`,
itself a filter with its own link group) in front of it, and for a target that is a filter
WirePlumber only looks for smart filters of that link group. The microphone module therefore
publishes its output as a higher-priority source instead.

## Predecessors

`conflicts.py` blocks the modules another plugin covers while it is installed and not disabled in
Decky (Ally Fix, Ally DSP, HueSync, Ally Center). Once Ally Fix is gone, `migrate.py` imports its
settings into module sections that still have their defaults; the gyro module takes over overrides
marked `managed-by: ally-fix`, the layout module removes Ally Fix's drop-in and shim copy. The audio
module takes Ally DSP's settings, tuning XML and converter venv already while Ally DSP is installed
(`prepare`), because Ally DSP deletes its data a minute after it is uninstalled; setup then only
converts the presets again. Decky v3.2.9/3.2.10-pre1 often skip the uninstall hook of plugins
without the socket workaround (Ally Fix), so their changes are still in place when the takeover runs.

## Root and user

The backend runs as root because the modules write sysfs, `/etc/inputplumber`, HID feature reports
and load BPF programs. Everything that belongs to the user session goes through
`util.run(..., as_user=True)`: the child gets the uid/gid of the home directory's owner, the user's
supplementary groups and `XDG_RUNTIME_DIR` / `DBUS_SESSION_BUS_ADDRESS` of that session. Root
children never inherit the backend environment (Decky's PyInstaller runtime sets `LD_LIBRARY_PATH`
to its own libraries). Files root writes below the home directory are handed to the user.

The speaker DSP is the exception to "root writes": everything it writes (download, venv,
conversion, presets, unit) runs in `allydsp.worker` with the system Python as the user, which keeps
the ownership Ally DSP had. The backend reads its state, starts and stops the unit through
`systemctl --user` (headphones) and writes only `audio/settings.json`.

steamos-manager runs twice: a root daemon on the system bus and a user daemon on the session bus.
The public API (what `steamosctl` uses) is the session one.

## Decky Python

Decky runs backends in its bundled Python 3.11 (PyInstaller). It lacks `xml.etree`, which the
pure-Python D-Bus libraries need, hence `busctl`. `glob`, `ctypes`, `fcntl`, `zipfile` work
(verified on the device). Check new stdlib imports on the device before relying on them.

## Interfaces found on the ROG Xbox Ally X

RC73XA, BIOS 317, SteamOS 3.8.28 (20260922.1), kernel 6.18.50-valve2, InputPlumber 0.78.0,
steamos-manager 26.4.1, Decky v3.2.10-pre1 (2026-10-04). The ROG Ally X differs only where the
next section says.

| Area | Interface | Notes |
|---|---|---|
| steamos-manager (session bus) | `CpuBoost1`, `BatteryChargeLimit1`, `FanControl1`, `PerformanceProfile1` (low-power, balanced, performance), `GpuPerformanceLevel1`, `CpuScaling1`, `CpuScheduler1`, `Manager2.DeviceModel` = (`rog_xbox_ally_x`, `RC73XA`) | TDP only in the performance profile (`rog-ally-series.toml`); charge limit through `acpi_sb` |
| InputPlumber (system bus) | `org.shadowblip.InputManager`, `CompositeDevice0` (`LoadProfileFromYaml`, `SetTargetDevices`, `TargetDevices`, ...) | manages the LED ring as source device `ally_rgb_joystick_rings` |
| hid_asus_ally (config interface `0003:0B05:1B4C.*`) | `btn_*/{remap,macro_remap,turbo}`, `axis_xy_*/{deadzone,anti_deadzone,curve_*}`, `axis_z_*/deadzone`, `gamepad_mode`, `vibration_intensity`, `mcu_version`, `apply_all`, `reset_btn_mapping` | `mcu_version` reads 0; deadzone store accepts 0..64; response curve apply is broken in the driver |
| LED | `/sys/class/leds/ally:rgb:joystick_rings/`: `brightness` (0–255), `multi_index` = 4 × rgb, `multi_intensity` (packed 0xRRGGBB), `sleep_animation` | the driver restores colours after resume |
| asus-armoury | `ppt_pl1_spl` (7–35), `ppt_pl2_sppt`, `ppt_pl3_fppt`, `mcu_powersave`, `charge_mode`, `boot_sound`, `pending_reboot` | `charge_mode` reads 10 although `possible_values` is 0;1;2 |
| Fans | hwmon `asus_custom_fan_curve`: `pwm{1,2}_auto_point{1..8}_{pwm,temp}`, `pwm*_enable` | the profile comes from `throttle_thermal_policy` |
| Platform | `/sys/firmware/acpi/platform_profile` | Steam switches it |
| SteamOS channel | `steamos-select-branch -c` (`rel`, `beta`, `preview`, `bc`, `pc`, `main`) | |

## Differences on the ROG Ally X

RC72LA, BIOS 312, same SteamOS, kernel, InputPlumber and steamos-manager, Decky v3.2.9
(2026-10-05). Everything in the table above is there as well, except:

| Area | ROG Ally X |
|---|---|
| steamos-manager | `Manager2.DeviceModel` = (`rog_ally_x`, `RC72LA`) |
| InputPlumber | config `50-rog_ally_x.yaml`: same IMU mount matrix as the Xbox Ally, capability map `aly1`; the `deck-uhid` target has the same product id 0x12FD ("ROG Ally X Controller"), so Steam tilts the gyro and builds the capability mask the same way; the gyro fix's deck mode gives 0x12F0 |
| Audio | Realtek ALC294, subsystem 0x10431eb3 (in the DSP device registry) |
| Controller | no impulse triggers. The MCU echoes `5A D1 1F` (Enhanced Vibration), but it echoes unknown commands just the same, so the echo proves nothing; the toggle stays Xbox Ally only |

## Files on the device

| Path | Content |
|---|---|
| `~/homebrew/plugins/Ally Companion/` | plugin code, `bin/` (shim, BPF object, LV2 bundle), `defaults/` (converter, unit template) |
| `~/homebrew/settings/Ally Companion/settings.json` | `update`, `migrated` and one section per module under `modules` |
| `~/homebrew/data/Ally Companion/audio/` | DSP settings, tuning XML, venv, presets, active preset (user-owned) |
| `~/homebrew/logs/Ally Companion/` | backend log, `diagnostics.txt` |

## Updates and uninstall

`updater.check` reads `releases/latest` (cached six hours, retried after 30 minutes on failure; a
repository without releases is not an error), `verify_release` checks `SHA256SUMS.minisig` against
the pinned `minisign.pub`, and the frontend hands the zip URL and hash to Decky's
`utilities/install_plugin`.

Decky calls `_uninstall` also while it replaces the plugin during an update. So `_uninstall` copies
both Python packages to the data directory and starts the transient timer
`ally-companion-cleanup` (60 s); `cli cleanup` then reverts every module, but only if `plugin.json`
is still gone, and deletes the data directory. A starting backend stops the timer.
