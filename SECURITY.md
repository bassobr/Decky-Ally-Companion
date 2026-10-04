# Security Policy

Ally Companion runs **as root** inside Decky Loader (`"flags": ["root"]`), because its hardware
modules write sysfs attributes, HID feature reports and InputPlumber configuration and load a
HID-BPF program. Work that belongs to the user session (the speaker DSP worker, PipeWire,
`systemctl --user`, steamos-manager's session API) runs in child processes dropped to the Decky
user.

Paths outside the plugin directory and `~/homebrew/{settings,data,logs}/Ally Companion` that a
module may change, each reverted when the plugin is removed:

| Module | Path |
|---|---|
| gyro | `/etc/inputplumber/devices.d/50-rog_xbox_ally.yaml`, one line in `~/.local/share/Steam/steam_dev.cfg` |
| gamepad layout | `~/.local/lib/ally-companion/`, `~/.config/systemd/user/steam-launcher.service.d/zz-ally-companion-gamepad-layout.conf` (the shim log `~/.local/state/ally-companion-allycaps.log` stays) |
| audio | `~/.config/systemd/user/ally-companion-dsp.service` |
| news | `~/Downloads/BIOS-<board>-<version>/` (only when the BIOS download is used; not removed) |

On removal, CPU boost, fan control, vibration strength and Enhanced Vibration go back to the
firmware defaults. The charge limit, MCU power saving, the boot sound and the last ring colour stay
as they were set.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting:

https://github.com/bassobr/Decky-Ally-Companion/security/advisories/new

Do not open public issues for security problems. This is a solo-maintained project; reports are
handled on a best-effort basis.

## Supported versions

Only the latest release receives fixes. The in-app updater moves installations forward; older
versions can be reinstalled with `install.sh`.

## Release integrity

- Releases are built by GitHub Actions from a tag and ship `SHA256SUMS` plus a minisign-compatible
  signature `SHA256SUMS.minisig`.
- The updater verifies the signature against the public key pinned in the plugin (`minisign.pub`)
  before trusting any checksum, then hands the zip URL and its SHA-256 to Decky Loader, which
  downloads the zip and rejects it on a checksum mismatch. Unsigned releases are refused.
- `install.sh` verifies checksum and signature before installing.
- Manual check: `minisign -Vm SHA256SUMS -p minisign.pub`.
- Limits: the signing seed lives in a GitHub Actions secret, so a full account takeover could still
  produce valid signatures. minisign has no revocation; a compromised key requires an out-of-band
  key rotation and a reinstall.

## Downloaded third-party content

- Audio setup downloads ASUS' public "Dolby Atmos driver" package over HTTPS and checks it against
  the SHA-256 from the ASUS support API (or the pinned fallback hash) before extracting anything.
  The converter's numpy/scipy come from PyPI into a private venv.
- The BIOS download checks the file against the SHA-256 the ASUS support API publishes.
- The prebuilt binaries in `bin/` (Steam client shim, BPF object) come from Ally Fix and are built
  from the sources in `shim/` and `bpf/`; the LSP LV2 bundle is fetched from the SteamOS package
  mirror and checked against a pinned SHA-256 at build time.
