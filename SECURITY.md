# Security Policy

Ally Companion runs **as root** inside Decky Loader (`"flags": ["root"]`), because its hardware
modules write sysfs attributes, HID feature reports and InputPlumber configuration. Work that
belongs to the user session (PipeWire, `systemctl --user`, steamos-manager's session API) runs in
child processes dropped to the Decky user. The plugin writes to the plugin directory and
`~/homebrew/{settings,data,logs}/Ally Companion`; each module documents any other path it changes
and reverts it on uninstall.

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
