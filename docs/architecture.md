# Architecture

Ally Companion is a Decky Loader plugin with a Python backend (`py_modules/allycompanion`) and a
React frontend (`src/`). It does for SteamOS what Handheld Daemon does elsewhere, but it does not
emulate a controller: InputPlumber does that on SteamOS (and on Bazzite since Bazzite 44), and
steamos-manager does power management. The plugin builds on those two services and on the ASUS
kernel drivers.

```
Decky Loader ── backend "Ally Companion" (root, flag "root")
                 ├─ registry     modules: settings section, supported(), start/stop, on_resume, uninstall
                 ├─ resume       suspend detection (CLOCK_BOOTTIME − CLOCK_MONOTONIC)
                 ├─ dbus         busctl --json: InputPlumber (system bus), steamos-manager (session bus)
                 ├─ util.run     root by default; as_user=True drops to the Decky user's session
                 ├─ device       board, BIOS, MCU, OS, interface probe
                 ├─ updater      GitHub Releases + minisign, installation through Decky
                 └─ diagnostics  report for the System page and the CLI
Frontend ── Quick Access panel: status line, quick controls of the modules, "All settings"
         ── route /ally-companion/<page>: SidebarNavigation (Overview, Audio, Controller, Lighting,
            Power & battery, Game profiles, News, System)
```

## UI rule

The Quick Access panel holds only what changes during a game and depends on the running game
(for example the audio preset or light brightness). Everything that is set once lives in the
fullscreen view. `openPage(id)` opens the view on a page; `SidebarNavigation` keeps the page in the
path (`/ally-companion/<id>`), so the route is registered without `exact`.

## Root and user

The backend runs as root because the fixes write sysfs, `/etc/inputplumber` and HID feature
reports. Everything that belongs to the user session goes through `util.run(..., as_user=True)`:
the child gets the uid/gid of the home directory's owner, the user's supplementary groups and
`XDG_RUNTIME_DIR` / `DBUS_SESSION_BUS_ADDRESS` of that session. Root children never inherit the
backend environment (Decky's PyInstaller runtime sets `LD_LIBRARY_PATH` to its own libraries).
Verified on the device: euid 0 backend, `id -un` in a dropped child prints `deck`, and
`systemctl --user is-system-running` answers `running`.

steamos-manager runs twice: a root daemon on the system bus and a user daemon on the session bus.
The public API (what `steamosctl` uses) is the session one, so reads and writes go through
`dbus.get_property(..., user_bus=True)`.

## Decky Python

Decky runs backends in its bundled Python 3.11 (PyInstaller). It lacks `xml.etree`, which the
pure-Python D-Bus libraries need, hence `busctl`. `glob` works (used by device.py, verified on
the device). Check new stdlib imports on the device before relying on them.

## Interfaces found on the ROG Xbox Ally X

RC73XA, BIOS 317, SteamOS 3.8.28 (20260922.1), kernel 6.18.50-valve2, InputPlumber 0.78.0,
steamos-manager 26.4.1, Decky v3.2.10-pre1 (2026-10-04). The ROG Ally X (RC72LA) still needs the
same survey.

| Area | Interface | Notes |
|---|---|---|
| steamos-manager (session bus) | `CpuBoost1`, `BatteryChargeLimit1`, `FanControl1`, `PerformanceProfile1` (low-power, balanced, performance), `GpuPerformanceLevel1`, `CpuScaling1`, `CpuScheduler1`, `Manager2.DeviceModel` = (`rog_xbox_ally_x`, `RC73XA`) | no `TdpLimit1` on this device; `MaxChargeLevel` reads -1 |
| InputPlumber (system bus) | `org.shadowblip.InputManager` (Version, CreateCompositeDevice, HookSleep/HookWake, ...), `CompositeDevice0` (`LoadProfileFromYaml`, `SetTargetDevices`, intercept mode, ...) | manages the LED ring as source device `ally_rgb_joystick_rings` |
| hid_asus_ally (config interface `0003:0B05:1B4C.*`) | `btn_*/{remap,macro_remap}`, `axis_xy_{left,right}/{deadzone,anti_deadzone,curve_*}`, `axis_z_*/deadzone`, `gamepad_mode`, `vibration_intensity`, `mcu_version`, `apply_all`, `reset_btn_mapping` | `mcu_version` reads 0 |
| LED | `/sys/class/leds/ally:rgb:joystick_rings/`: `brightness` (0–255), `multi_index` = 4 × rgb, `multi_intensity`, `sleep_animation`, kernel triggers (`BAT0-charging`, ...) | InputPlumber and Steam may write it too |
| asus-armoury | `ppt_pl1_spl` (7–35), `ppt_pl2_sppt`, `ppt_pl3_fppt`, `mcu_powersave`, `charge_mode`, `boot_sound`, `pending_reboot` | `charge_mode` reads 10 although `possible_values` is 0;1;2 |
| Fans | hwmon `asus_custom_fan_curve`: `pwm{1,2}_auto_point{1..8}_{pwm,temp}`, `pwm*_enable` | Ally Fix pins these curves |
| Platform | `/sys/firmware/acpi/platform_profile` (low-power, balanced, performance) | Steam switches it |

Other plugins on the test device that touch the same hardware: Ally Fix (vibration, CPU boost,
fans, gyro, layout), Ally DSP (audio), HueSync (LED). Disable the old one before testing the module
that replaces it.

## Files on the device

| Path | Content |
|---|---|
| `~/homebrew/plugins/Ally Companion/` | plugin code (root-owned) |
| `~/homebrew/settings/Ally Companion/settings.json` | `update` section and one section per module under `modules` |
| `~/homebrew/data/Ally Companion/tmp/` | update signature downloads |
| `~/homebrew/logs/Ally Companion/` | backend log, `diagnostics.txt` |

## Updates and uninstall

Same pipeline as Ally DSP: `updater.check` reads `releases/latest` (cached six hours, retried after
30 minutes on failure; a repository without releases is not an error), `verify_release` checks
`SHA256SUMS.minisig` against the pinned `minisign.pub`, and the frontend hands the zip URL and hash
to Decky's `utilities/install_plugin`. Decky calls `_uninstall` also while it replaces the plugin
during an update, so a module that reverts system changes on uninstall must defer that until the
plugin directory is really gone (Ally DSP's `systemd-run --on-active=60` pattern).
