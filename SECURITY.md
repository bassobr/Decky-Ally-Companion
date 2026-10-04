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
| microphone, headphone EQ | `~/.config/systemd/user/ally-companion-mic.service`, `~/.config/systemd/user/ally-companion-hp.service` |
| backups | `~/Documents/Ally Companion/` (only when a backup is made; not removed) |
| news | `~/Downloads/BIOS-<board>-<version>/` (only when the BIOS download is used; not removed) |

On removal, CPU boost, fan control, vibration strength and Enhanced Vibration go back to the
firmware defaults. The charge limit, MCU power saving, the boot sound and the last ring colour stay
as they were set.

## Root and the user's files

Decky gives the plugin settings and data directories that belong to the Decky user, and the
modules work in the user's home (Steam's config, `~/.config`, `~/.local`, `~/Documents`). Any
process running as that user could plant symlinks there or swap files, so the root backend:

- writes, creates and removes nothing below the home itself; a child process running as the user
  does it (`py_modules/allycompanion/userfs.py`), so a redirected write lands only where the user
  could write anyway;
- writes its own root-owned `settings.json` with `O_EXCL|O_NOFOLLOW` and `fchmod`;
- stages the uninstall cleanup code in `/run/ally-companion-cleanup` (root, 0700), never in the
  user-owned data directory, because it runs as root a minute later;
- verifies update signatures in memory and asks GitHub afresh before an update, accepting only a
  newer version whose assets come from this repository's releases;
- treats values read from `settings.json` as untrusted: fan curves are range-checked before they
  reach sysfs, BIOS download entries are checked before they become paths or URLs.

What a process running as the user can still do is change the settings this plugin applies,
within the checked ranges (vibration strength, lighting, fan curves, profiles). That needs no
privilege it does not already have for its own games and Steam configuration.

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
- `install.sh` verifies checksum and signature before installing, with the public key pinned in
  the script and the verifier fetched from this repository, not from the zip it checks.
- Manual check: `minisign -Vm SHA256SUMS -p minisign.pub`.
- Limits: the signing seed lives in a GitHub Actions secret, so a full account takeover could still
  produce valid signatures. minisign has no revocation; a compromised key requires an out-of-band
  key rotation and a reinstall.

## Downloaded third-party content

- Audio setup downloads ASUS' public "Dolby Atmos driver" package over HTTPS and checks it against
  the SHA-256 from the ASUS support API (or the pinned fallback hash) before extracting anything.
  The converter's numpy/scipy come from PyPI into a private venv.
- The BIOS download checks the file against the SHA-256 the ASUS support API publishes.
- Headphone EQ profiles are text files from the AutoEQ repository on GitHub, parsed into filter
  parameters; nothing from them is executed.
- The prebuilt binaries in `bin/` (Steam client shim, BPF object) come from Ally Fix and are built
  from the sources in `shim/` and `bpf/`; the LSP LV2 bundle is fetched from the SteamOS package
  mirror and checked against a pinned SHA-256 at build time.
