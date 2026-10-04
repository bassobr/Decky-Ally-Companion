# Roadmap

Targets: ROG Xbox Ally X (RC73XA) and ROG Ally X (RC72LA) on SteamOS. Bazzite (same InputPlumber
stack since Bazzite 44) comes along where it costs nothing.

Each step ends with an on-device test on both boards. Before testing a module, disable the old
plugin it replaces on the test device.

1. **Skeleton** (0.1.0, done): root backend with user boundary, module registry, resume detection,
   D-Bus via busctl, device probe, Quick Access panel and fullscreen view, signed updates, CI.
2. **Controller** from Ally Fix: vibration intensity, Enhanced Vibration, rumble cap and trigger
   mirror (HID-BPF), gyro fix, gamepad layout fix (Steam client shim). Then deadzones, response
   curves and remapping through hid_asus_ally.
3. **Power & battery** from Ally Fix: CPU boost fix (check steamos-manager `CpuBoost1` first), fan
   fix; charge limit (steamos-manager or asus-armoury), MCU power saving, fan curves.
4. **Audio** from Ally DSP: setup wizard, presets, per-game presets, headphone pause; all PipeWire
   and `systemctl --user` calls through `as_user`. Migrate settings and stop/remove the old unit.
5. **Lighting**: color, brightness, effects, state lighting. First find out who else writes the
   LED (InputPlumber's LED source device, Steam's controller LED setting, HueSync).
6. **News**: SteamOS releases (Steam news API, app 1675200, filtered by channel), ASUS BIOS for the
   board (`GetPDBIOS`), a signed known-issues feed in this repository.
7. **Game profiles**: per-game overrides of every module in one list.

Open decisions:

- Ally Fix: port module by module with attribution, or vendor it via `git subtree` behind an
  adapter (its fixes import `decky` and its own settings module). Upstream changes matter most
  for the Steam client shim, which breaks with Steam updates.
- One-time migration of the settings of Ally Fix and Ally DSP on the test devices.
