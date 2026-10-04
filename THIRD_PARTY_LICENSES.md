# Third-party components

Ally Companion itself is licensed under the MIT License (see `LICENSE`). The source tree and the
release zip contain or fetch the following third-party work.

| Component | Use | License | Source |
|---|---|---|---|
| Ally Fix | Vibration, gyro, gamepad layout, CPU boost and fan modules, `uevent.py`, `steam.py`, `hidbpf.py`, `resume.py`, the module interface, `src/layoutPatch.ts`, `src/controllerArt.ts`; ported and adapted (marked in each file) | MIT, Copyright (c) 2026 lonsdaleite (text below) | https://github.com/lonsdaleite/Ally-Fix |
| Steam client shim (`shim/allycaps.c`, `bin/liballycaps*.so`) | Patches Steam's controller capability constant in memory | MIT, from Ally Fix | as above |
| Rumble packet filter (`bpf/ally_ff.bpf.c`, `bin/ally_ff.bpf.o`) | HID-BPF program loaded into the kernel | GPL-2.0-or-later (it calls a GPL-only kfunc), from Ally Fix | as above |
| Ally DSP | `py_modules/allydsp` (speaker DSP runtime), updater, minisign/Ed25519 verification, `deckyfix.py`, build and release scripts | MIT, same author | https://github.com/bassobr/decky-ally-dsp |
| LSP Plugins (`bin/lv2/lsp-plugins.lv2`, five plugin descriptions) | LV2 DSP stages run by PipeWire | LGPL-3.0-or-later, see `third_party/licenses/LGPL-3.0.txt` | https://lsp-plug.in; binary taken unmodified from the Arch Linux package `lsp-plugins-lv2` 1.2.22 as mirrored by SteamOS; source at https://github.com/lsp-plugins/lsp-plugins |
| speaker-tuning-to-easyeffects | Converts the Dolby DAX3 tuning XML into a PipeWire filter chain (runs on the device in a private venv) | MIT, Copyright (c) 2026 Antoine Cellerier | https://github.com/antoinecellerier/speaker-tuning-to-easyeffects (git submodule) |
| numpy, scipy | Dependencies of the converter, installed by pip into the private venv on the device | BSD-3-Clause | https://numpy.org, https://scipy.org |
| Decky plugin template | Build configuration, type stubs | BSD-3-Clause, Steam Deck Homebrew | https://github.com/SteamDeckHomebrew/decky-plugin-template |

The MCU packet layout for the lighting effects (`5A B3/B4/B5/BA`) follows what Handheld Daemon
documents for the ROG Ally (https://github.com/hhd-dev/hhd); no code was copied from it.

**Not included on purpose:** the Dolby/ASUS speaker tuning (`DEV_*_SUBSYS_*.xml`) is proprietary.
The plugin downloads ASUS' public driver package onto the user's own device during setup and
extracts the file there; it is never redistributed with this project.

## Ally Fix license

```
MIT License

Copyright (c) 2026 lonsdaleite

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
