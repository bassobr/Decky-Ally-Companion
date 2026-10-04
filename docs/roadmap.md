# Roadmap

Targets: ROG Xbox Ally X (RC73XA) and ROG Ally X (RC72LA) on SteamOS. Bazzite (same InputPlumber
stack since Bazzite 44) comes along where it costs nothing.

## Done (0.2.0, verified on the RC73XA)

1. **Skeleton**: root backend with user boundary, module registry, resume detection, D-Bus via
   busctl, device probe, Quick Access panel and fullscreen view, signed updates, CI.
2. **Controller** from Ally Fix: vibration strength, Enhanced Vibration, rumble cap and trigger
   mirror (HID-BPF), gyro fix, gamepad layout fix (Steam client shim and UI patch).
3. **Power & battery** from Ally Fix: CPU boost cap, fan curve pinning; new: custom fan curves,
   charge limit through steamos-manager, battery health, MCU power saving, boot sound.
4. **Audio** from Ally DSP: setup, presets, per-game presets, headphone pause, extras.
5. **Lighting**: static colours, MCU effects, battery level display.
6. **News**: SteamOS releases per channel, ASUS BIOS and firmware, known-issues feed.
7. **Game profiles**: per-game lighting and vibration strength.

Takeover from the predecessors is tested: Ally Fix and Ally DSP were uninstalled on the test device,
their settings and data imported, their overrides and drop-ins taken over.

Lifecycle tested on the RC73XA with the signed releases: uninstall in Decky reverts every module a
minute later (0.2.1; 0.2.0 skipped the layout and the DSP unit), `install.sh` installs and
verifies the latest release, Decky's installer installs 0.2.0, the in-app update moves it to 0.2.1
without reverting anything (the old version's cleanup timer is cancelled by the new backend), and
audio setup from scratch (ASUS download, venv, 15 presets) finishes in about 30 seconds.

## Done (0.3.0, verified on the RC73XA)

8. Entry in Steam's settings menu, live values with CPU boost details, settings backup and
   restore, controller reconnect, charge to 100 % once, daily battery health history, news toasts.
9. Game profiles with performance profile, CPU boost and fan curve.
10. Microphone noise suppression and headphone EQ (AutoEQ). The EQ chain was checked on a test
    target; with real headphones it is still untested.

## Open

- **ROG Ally X (RC72LA)**: run the interface survey (docs/architecture.md), then enable the modules
  that are limited to the Xbox Ally boards where the hardware allows it. Enhanced Vibration and the
  gyro override are Xbox Ally only for now; the InputPlumber config of the Ally X is
  `50-rog_ally_x.yaml`.
- **Lighting effects**: breathing, colour cycle and rainbow send the MCU commands without errors,
  but nobody has looked at the rings yet. Static colours and brightness are verified through sysfs.

## Decided against

- **Stick and trigger tuning through hid_asus_ally**: the driver's response curve code sends a
  broken packet (no command byte, both sticks get the left curve), its deadzone store accepts 0..64
  while its own defaults are 100, and Steam Input already offers deadzones, outer rings, response
  curves and trigger ranges per game. Button remapping at MCU level would also confuse InputPlumber.
- **TDP**: Steam shows it for the Ally through steamos-manager (performance profile only).
