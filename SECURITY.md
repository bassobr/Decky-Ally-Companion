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
firmware defaults. The charge limit, MCU power saving and the boot sound stay as they were set. The
rings keep their last colour until the next sleep; from SteamOS 3.9.2 on (Linux 7.2) they are dark
after that, because the kernel's LED class can no longer hold the colour (the plugin sets the
colour through the controller and leaves the driver's copy black).

## Root and the user's files

Decky gives the plugin settings and data directories that belong to the Decky user, and the
modules work in the user's home (Steam's config, `~/.config`, `~/.local`, `~/Documents`). Any
process running as that user could plant symlinks, FIFOs or hard links there or swap files, so
the root backend:

- writes, creates and removes nothing below the home itself, with one exception; a child process
  running as the user does it (`py_modules/allycompanion/userfs.py`), so a redirected write lands
  only where the user could write anyway. That includes deleting the data directory on uninstall;
- reads below the home only what the user could read: `py_modules/allycompanion/safefs.py` opens
  every path component without following symlinks and accepts only regular files the user has
  read access to; anything else is read by the user's child process instead. So no planted link
  makes root copy a root-only file (`/etc/shadow`, another plugin's settings) into a file or an
  answer the user can see;
- writes its own `settings.json` (the exception) through a directory opened the same way, with
  `O_EXCL|O_NOFOLLOW` for the temporary file and an atomic rename inside that directory;
- stages the uninstall cleanup code in `/run/ally-companion-cleanup` (root, 0700), never in the
  user-owned data directory, because it runs as root a minute later;
- verifies update signatures in memory and asks GitHub afresh before an update, accepting only a
  newer version whose assets come from this repository's releases, and checks the zip itself
  before Decky's installer gets it (see below);
- treats every value read from `settings.json`, a backup or a predecessor's settings as untrusted:
  each value takes the type of its default, and each module checks its section (ranges, enums,
  curves, game profiles, news entries, BIOS entries) before anything reaches hardware, a path or a
  URL.

### Calls from other processes

Decky hands the token for its socket to any local process (`http://127.0.0.1:1337/auth/token`), so
not only the plugin's own UI can call the backend's methods: any process on the device can, a game
under Proton or a Flatpak with network access included. Every argument is therefore checked like a
value from `settings.json`, and the limits below hold whoever asks:

- **Fans**: from 85 °C on, no curve (custom, per game, restored, from a file) gives less than the
  factory curve of the active thermal profile, which the backend reads from the EC itself; below
  that a curve may be as quiet as wanted. A curve must start at 85 °C or below.
- **Headphone EQ**: only profiles listed in AutoEQ's index are fetched, by their path inside
  AutoEQ's results. Filter values are bounded and the preamp is lowered until the summed response
  of all filters stays at or below 0 dB, so a profile can attenuate but never boost.
- **Charge limit**: never below steamos-manager's suggested minimum (50 % when it has none).

What a process running as the user can still do is change the settings this plugin applies,
within these limits (vibration strength, lighting, fan curves, profiles). That needs no privilege
it does not already have for its own games and Steam configuration.

### Limits of the boundary

On SteamOS `~/homebrew` belongs to the Decky user; only `~/homebrew/plugins` belongs to root.
Decky starts a plugin whose `plugin.json` has the `root` flag as root without checking who owns its
files, so a process running as the user could put its own plugin in place of that directory and get
root at the next start of Decky. That is a property of Decky, not of this plugin, and nothing a
plugin can close: the measures above keep this plugin from adding a second way, but they do not
make the device safe against a hostile process running as the user.

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
  before trusting any checksum, downloads the zip into `/run/ally-companion-update` (root, 0700),
  checks it against the signed SHA-256 and hands Decky Loader that local file and the hash. Decky
  removes the installed version before it checks a zip, so a zip that would fail its check never
  gets that far. Unsigned releases are refused.
- `install.sh` verifies checksum and signature before installing, with the public key pinned in
  the script and the verifier fetched from this repository, not from the zip it checks.
- Manual check: `minisign -Vm SHA256SUMS -p minisign.pub`.
- Limits: the signing seed lives in a GitHub Actions secret, so a full account takeover could still
  produce valid signatures. minisign has no revocation; a compromised key requires an out-of-band
  key rotation and a reinstall.

## Downloaded third-party content

- Audio setup downloads ASUS' public "Dolby Atmos driver" package over HTTPS and checks it against
  the SHA-256 from the ASUS support API (or the pinned fallback hash) before extracting anything.
  A package the API lists without a SHA-256 is not downloaded; the pinned one is used instead.
- The converter's numpy/scipy come from PyPI into a private venv as wheels only, each checked
  against the hashes in `defaults/converter-requirements.txt` (`pip --require-hashes`). There is
  no unpinned fallback: a Python version without a pinned wheel needs a plugin update.
- The BIOS download checks the file against the SHA-256 the ASUS support API publishes; without a
  published SHA-256 nothing is downloaded.
- Headphone EQ profiles are text files from the AutoEQ repository on GitHub, parsed into filter
  parameters; nothing from them is executed.
- The prebuilt binaries in `bin/` (Steam client shim, BPF object) come from Ally Fix and are built
  from the sources in `shim/` and `bpf/` in containers pinned by image digest and Debian snapshot
  date. CI rebuilds the shim and fails when it differs from the committed one; the BPF object
  depends on the build host's kernel BTF and is rebuilt by hand. The LSP LV2 bundle is fetched
  from the SteamOS package mirror and checked against a pinned SHA-256 at build time.
