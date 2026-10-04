"""Speaker DSP of Ally Companion, vendored from Ally DSP (https://github.com/bassobr/decky-ally-dsp, MIT).

Runs in two places: read-only inside the root backend (allycompanion.modules.audio), and
as the worker CLI (allydsp.worker) in the Decky user's session for everything that writes.
"""
