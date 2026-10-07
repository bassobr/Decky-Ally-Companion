"""Root/user boundary, input checks and the fixes from the 0.5.0 review."""
import ast
import asyncio
import hashlib
import json
import os
import threading
import time

import pytest

from allycompanion import jacksense, migrate, paths, safefs, settings, updater, userfs, util
from allycompanion.module import Context, Module
from allycompanion.modules import MODULES, audio, battery, fan, gyro, headphones, lighting, news, profiles
from allycompanion.registry import Registry
from allydsp import asus_fetch, convert, hardware, jackwatch
from allydsp import paths as dsp_paths
from allydsp import settings as dsp_settings

AS_ROOT = os.geteuid() == 0


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f)


async def _emit(event, payload):
    pass


def _module(cls, cfg=None):
    m = cls()
    m.bind({**cls.defaults, **(cfg or {})}, Context(lambda: None, _emit))
    return m


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def sysroot(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SYSROOT", str(tmp_path))
    return str(tmp_path)


# ------------------------------------------------------------------ safefs and userfs

def test_safefs_reads_plain_files_and_refuses_links_and_fifos(home):
    (home / "data").mkdir()
    (home / "data" / "a.json").write_text('{"x": 1}')
    assert safefs.read_json(str(home / "data" / "a.json")) == {"x": 1}
    assert safefs.read_bytes(str(home / "data" / "missing")) is None
    (home / "link.json").symlink_to(home / "data" / "a.json")
    with pytest.raises(safefs.Refused):
        safefs._open(str(home / "link.json"), ["link.json"])
    (home / "dirlink").symlink_to(home / "data")
    with pytest.raises(safefs.Refused):
        safefs._open(str(home / "dirlink" / "a.json"), ["dirlink", "a.json"])
    os.mkfifo(home / "fifo")
    with pytest.raises(safefs.Refused):  # opened non-blocking and refused, never read
        safefs._open(str(home / "fifo"), ["fifo"])
    assert safefs.below_home(str(home / "data" / "a.json")) == ["data", "a.json"]
    assert safefs.below_home("/etc/os-release") is None and safefs.below_home(str(home)) is None


def test_safefs_size_limit_and_tail(home):
    (home / "log").write_bytes(b"0123456789")
    assert safefs.read_bytes(str(home / "log"), 4, tail=True) == b"6789"
    with pytest.raises(safefs.Refused):
        safefs.read_bytes(str(home / "log"), 4)


@pytest.mark.skipif(AS_ROOT, reason="permission bits do not stop root")
def test_safefs_reads_only_what_the_user_could_read(home):
    secret = home / "secret"
    secret.write_text("x")
    secret.chmod(0)
    with pytest.raises(safefs.Refused):
        safefs._open(str(secret), ["secret"])
    with pytest.raises(OSError):  # the fallback reads as the user, who cannot read it either
        safefs.read_bytes(str(secret))
    secret.chmod(0o600)


def test_safefs_write_lands_in_the_real_directory(home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "victim").write_text("keep")
    d = home / "settings"
    d.mkdir()
    (d / "settings.json").symlink_to(outside / "victim")
    safefs.write_bytes(str(d / "settings.json"), b"{}")
    assert not (d / "settings.json").is_symlink() and (d / "settings.json").read_text() == "{}"
    assert (outside / "victim").read_text() == "keep"
    (home / "swapped").symlink_to(outside, target_is_directory=True)
    with pytest.raises(safefs.Refused):
        safefs.write_bytes(str(home / "swapped" / "settings.json"), b"{}")
    assert not (outside / "settings.json").exists()


def test_userfs_reads_hashes_and_lists_as_the_user(tmp_path):
    f = tmp_path / "a.json"
    f.write_bytes(b"0123456789")
    assert userfs.read(str(f), 100) == b"0123456789"
    assert userfs.read(str(f), 4, tail=True) == b"6789"
    with pytest.raises(OSError):
        userfs.read(str(f), 4)
    assert userfs.read(str(tmp_path / "missing"), 10) is None
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(OSError):
        userfs.read(str(tmp_path / "fifo"), 10)
    assert userfs.sha256(str(f), 100) == hashlib.sha256(b"0123456789").hexdigest()
    assert ("a.json", 10) in userfs.listdir(str(tmp_path))
    assert userfs.listdir(str(tmp_path / "nothing")) == []


@pytest.mark.skipif(AS_ROOT, reason="permission bits do not stop root")
def test_gyro_never_copies_a_linked_file_into_steam_dev_cfg(home):
    secret = home / "secret"
    secret.write_text("root only\n")
    secret.chmod(0)
    cfg = home / ".local" / "share" / "Steam" / "steam_dev.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.symlink_to(secret)
    m = _module(gyro.Gyro, {"mode": "complex"})
    with pytest.raises(RuntimeError):
        m._set_convar(True)
    assert cfg.is_symlink()
    secret.chmod(0o600)
    assert secret.read_text() == "root only\n"


def test_gyro_edits_a_plain_steam_dev_cfg(home):
    cfg = home / ".local" / "share" / "Steam" / "steam_dev.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("@nClientDownloadEnableHTTP2PlatformLinux 0\n")
    m = _module(gyro.Gyro, {"mode": "complex"})
    m._set_convar(True)
    assert cfg.read_text().endswith("gyro_force_handheld_orientation 2\n")
    m.normalize(m.cfg)
    assert m.cfg["steamCfgPrev"] == ""
    m.cfg["steamCfgPrev"] = "gyro_force_handheld_orientation 1\nexec evil"
    m.normalize(m.cfg)
    assert m.cfg["steamCfgPrev"] == ""  # one line with that convar, nothing else


# ------------------------------------------------------------------ settings from files the user owns

def test_tampered_settings_fall_back_to_defaults(home, monkeypatch):
    monkeypatch.setattr(paths, "SETTINGS_FILE", str(home / "settings.json"))
    _write_json(paths.SETTINGS_FILE, {
        "migrated": "Ally Fix",
        "update": {"autoCheck": "no", "latest": {"version": 5}, "lastCheck": "x"},
        "modules": {
            "vibration": {"left": "loud", "enabled": "yes"},
            "lighting": {"mode": "disco", "brightness": 900, "color": "red"},
            "fan": {"curves": {"balanced": {"temps": [1] * 8}}},
            "profiles": {"apps": {"../x": {"cpuBoost": {"boost": True}}, "42": {"fan": {"curve": "hot"}}}},
            "headphones": {"eq": {"filters": "loud"}, "output": 7},
            "battery": {"fullOnce": 3, "history": "x"},
            "news": {"items": [{"id": "a", "kind": "issue", "url": "javascript:x"}, {"kind": "x"}]},
        },
    })
    reg = Registry(MODULES)
    s = settings.load(reg.defaults())
    assert s["migrated"] == [] and s["update"]["autoCheck"] is True
    assert s["update"]["latest"] is None and s["update"]["lastCheck"] == 0
    _write_json(str(home / "homebrew/settings/Ally Fix/settings.json"), {"vibration": "not a section", "fan": {"curves": 1}})
    assert migrate.run(s, reg.defaults()) == ["Ally Fix"]  # no crash on odd values
    reg.bind(s, Context(lambda: None, _emit))
    m = s["modules"]
    assert m["vibration"]["left"] == 50 and m["vibration"]["enabled"] is False
    assert (m["lighting"]["mode"], m["lighting"]["brightness"], m["lighting"]["color"]) == ("static", 100, "#ff0040")
    assert m["fan"]["curves"] == {} and m["profiles"]["apps"] == {}
    assert m["headphones"]["eq"] is None and m["headphones"]["output"] == "wired"
    assert m["battery"]["fullOnce"] is None and m["battery"]["history"] == []
    assert m["news"]["items"] == [{"id": "a", "kind": "issue", "newer": False, "url": None}]


def test_settings_are_saved_through_the_real_directory(home, monkeypatch, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    d = home / "homebrew" / "settings" / "Ally Companion"
    d.mkdir(parents=True)
    monkeypatch.setattr(paths, "SETTINGS_FILE", str(d / "settings.json"))
    settings.save({"schema": 1})
    assert json.loads((d / "settings.json").read_text()) == {"schema": 1}
    d.rename(home / "moved")
    (home / "homebrew" / "settings" / "Ally Companion").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        settings.save({"schema": 1})
    assert not (outside / "settings.json").exists()


# ------------------------------------------------------------------ physical limits

FACTORY = {"temps": [48, 54, 59, 62, 62, 62, 62, 62], "pwm1": [2, 22, 45, 56, 56, 56, 56, 56],
           "pwm2": [2, 22, 33, 33, 33, 33, 33, 33]}
PERF = {"temps": [48, 55, 58, 62, 66, 73, 73, 94], "pwm1": [22, 66, 99, 122, 142, 165, 165, 198],
        "pwm2": [22, 63, 63, 96, 117, 137, 170, 201]}


def test_fan_floor_keeps_the_factory_curve_from_85_degrees():
    off = {"temps": FACTORY["temps"], "pwm1": [0] * 8, "pwm2": [0] * 8}
    floored = fan.apply_floor(off, FACTORY)
    assert floored["pwm1"] == [0] * 7 + [56] and floored["pwm2"] == [0] * 7 + [33]
    quiet = fan.apply_floor({"temps": PERF["temps"], "pwm1": [0] * 8, "pwm2": [0] * 8}, PERF)
    assert fan.duty_at(quiet, "pwm1", 85) >= fan.duty_at(PERF, "pwm1", 85)
    assert fan.duty_at(quiet, "pwm1", 100) >= 198 and fan.duty_at(quiet, "pwm2", 100) >= 201
    assert fan.duty_at(quiet, "pwm1", 60) == 0  # quieter than factory below 85 degrees stays allowed
    louder = {"temps": FACTORY["temps"], "pwm1": [255] * 8, "pwm2": [255] * 8}
    assert fan.apply_floor(louder, FACTORY) == louder
    with pytest.raises(ValueError):
        fan.sanitize({"temps": [90] * 8, "pwm1": [0] * 8, "pwm2": [0] * 8})
    with pytest.raises(ValueError):
        fan.sanitize({"temps": [40] * 8, "pwm1": ["0"] * 8, "pwm2": [0] * 8})


def _fake_fan(root, curve):
    d = os.path.join(root, "sys/class/hwmon/hwmon5")
    _write(d, "name", "asus_custom_fan_curve")
    for f in ("pwm1", "pwm2"):
        _write(d, f"{f}_enable", "2")
        for i in range(8):
            _write(d, f"{f}_auto_point{i + 1}_temp", str(curve["temps"][i]))
            _write(d, f"{f}_auto_point{i + 1}_pwm", str(curve[f][i]))
    _write(root, "sys/devices/platform/asus-nb-wmi/throttle_thermal_policy", "0")
    return d


def test_fan_custom_curve_is_floored_before_it_reaches_the_ec(sysroot):
    d = _fake_fan(sysroot, FACTORY)
    m = _module(fan.Fan, {"enabled": True})
    asyncio.run(m.set_curve({"temps": FACTORY["temps"], "pwm1": [0] * 8, "pwm2": [0] * 8}))
    written = m.read_curve()
    assert written["pwm1"][-1] == 56 and written["pwm2"][-1] == 33
    assert m.snapshots()["balanced"] == written
    assert open(os.path.join(d, "pwm1_enable")).read() == "1"


def test_headphone_profiles_only_ever_attenuate():
    evil = {"preamp": 0, "filters": [{"type": "bq_peaking", "freq": 1000, "gain": 12, "q": 1}] * 20}
    assert headphones.sanitize_eq(evil) is None  # would need -240 dB of preamp: not a correction
    one = headphones.sanitize_eq({"preamp": 5, "filters": [{"type": "bq_peaking", "freq": 1000, "gain": 45, "q": 1}]})
    assert one["filters"][0]["gain"] == 12.0 and one["preamp"] <= -12.0
    assert headphones.max_boost_db(one["filters"]) + one["preamp"] <= 1e-9
    assert headphones.sanitize_eq(one)["preamp"] == one["preamp"]  # stable when checked again
    junk = {"preamp": "x", "filters": [{"type": "ladspa", "freq": 1}, {"type": "bq_lowshelf", "freq": "nan", "gain": 1}]}
    assert headphones.sanitize_eq(junk) is None
    with pytest.raises(ValueError):
        headphones.config({"filters": []}, "x")


def test_headphone_profile_paths_stay_in_the_autoeq_index(monkeypatch):
    with pytest.raises(ValueError):
        headphones.profile_url("../../../../owner/repo/main/x")
    assert headphones.profile_url("a b/c (d)").endswith("/a%20b/c%20%28d%29/c%20%28d%29%20ParametricEQ.txt")
    m = _module(headphones.Headphones)

    async def index():
        return [{"name": "HD 650", "path": "oratory1990/over-ear/HD 650", "source": "oratory1990"}]

    fetched = []
    monkeypatch.setattr(m, "_load_index", index)
    monkeypatch.setattr(headphones, "fetch", lambda url, timeout=30: fetched.append(url) or
                        "Preamp: -6 dB\nFilter 1: ON PK Fc 100 Hz Gain 40 dB Q 1\n")
    with pytest.raises(ValueError):
        asyncio.run(m.select(path="../../../../owner/repo/main/x", name="x"))
    asyncio.run(m.select(path="oratory1990/over-ear/HD 650", name="spoofed", source="spoofed"))
    assert fetched and m.cfg["eq"]["name"] == "HD 650" and m.cfg["eq"]["filters"][0]["gain"] == 12.0


def test_game_profile_parts_are_checked_like_module_settings():
    m = _module(profiles.Profiles)
    with pytest.raises(ValueError):
        asyncio.run(m.set_app(appId="42", part="fan", values={"curve": {"temps": [1]}}))
    with pytest.raises(ValueError):
        asyncio.run(m.set_app(appId="42", part="lighting", values={"mode": "disco"}))
    with pytest.raises(ValueError):
        asyncio.run(m.set_app(appId="../42", part="cpuBoost", values={"boost": True}))
    asyncio.run(m.set_app(appId="42", part="lighting", values={"mode": "breathing", "brightness": 900, "evil": 1}))
    assert m.apps()["42"]["lighting"] == {"mode": "breathing", "brightness": 100}


def test_charge_limit_stays_at_the_suggested_minimum(monkeypatch):
    m = _module(battery.Battery)
    sent = []
    monkeypatch.setattr(battery.dbus, "try_get_property", lambda *a, **k: 60)
    monkeypatch.setattr(battery.dbus, "set_property", lambda *a: sent.append(a[-2]))
    asyncio.run(m._write_limit(20))
    asyncio.run(m._write_limit(80))
    asyncio.run(m._write_limit(None))
    assert sent == [60, 80, -1]
    cfg = {"fullOnce": 5, "history": [{"d": "2026-10-01", "h": 94}, {"d": "x", "h": 1}, "junk", {"d": "2026-10-02", "h": True}]}
    m.normalize(cfg)
    assert cfg["fullOnce"] is None and cfg["history"] == [{"d": "2026-10-01", "h": 94.0, "e": None, "c": None}]


# ------------------------------------------------------------------ lifecycle fixes

def test_audio_is_not_stuck_after_a_cancelled_setup_or_conversion():
    async def main():
        m = audio.Audio()
        gate = threading.Event()
        m.worker.run = lambda *a, **k: gate.wait(5)  # still running
        m.dsp = lambda: {"extras": {}, "setup": {}, "enabled": False}
        await m.run_setup()
        await asyncio.sleep(0.05)
        await m.stop()  # what a backup restore does
        assert not m.setup_running and m.setup_last["status"] == "cancelled"
        m._start_reconvert()
        await asyncio.sleep(0.05)
        await m.stop()
        assert not m.converting and m.convert_last["status"] == "cancelled" and not m.busy()
        gate.set()

    asyncio.run(main())


class _Slow(Module):
    id = "slow"
    ended = 0.0

    async def on_resume(self, slept_s):
        await asyncio.sleep(0.3)
        _Slow.ended = time.monotonic()


class _Fast(Module):
    id = "fast"
    ran = 0.0

    async def on_resume(self, slept_s):
        _Fast.ran = time.monotonic()


def test_resume_hooks_do_not_wait_for_each_other(monkeypatch):
    monkeypatch.setattr("allycompanion.conflicts.blocked", lambda: {})
    reg = Registry([_Slow, _Fast])
    reg.bind({"modules": reg.defaults()}, Context(lambda: None, _emit))
    asyncio.run(reg.on_resume(5.0))
    assert _Fast.ran < _Slow.ended


def test_lighting_packet_sequences_never_interleave(sysroot, monkeypatch):
    m = _module(lighting.Lighting, {"enabled": True, "mode": "breathing", "brightness": 50})
    active, overlaps = [], []

    def write_ec(*args):
        active.append(1)
        if len(active) > 1:
            overlaps.append(1)
        time.sleep(0.05)
        active.pop()

    monkeypatch.setattr(m, "_write_ec", write_ec)

    async def main():
        await asyncio.gather(m.apply(), m.set_override({"color": "#00ff00"}), m.apply())

    asyncio.run(main())
    assert not overlaps and m._shown.startswith("breathing #00ff00")


def test_update_zip_is_checked_before_decky_gets_it(tmp_path, monkeypatch):
    payload = b"zip-bytes"
    good = hashlib.sha256(payload).hexdigest()

    def fake_curl(cmd, timeout=60, **kw):
        with open(cmd[cmd.index("-o") + 1], "wb") as f:
            f.write(payload)
        return util.Result(0, "", "")

    monkeypatch.setattr(updater, "run", fake_curl)
    staging = str(tmp_path / "staging")
    release = {"artifact": "https://github.com/x/z.zip", "name": "Ally Companion", "version": "9.9.9", "hash": good}
    out = updater.download_verified(release, staging)
    assert out["artifact"] == "file://" + os.path.join(staging, "ally-companion-9.9.9.zip") and out["hash"] == good
    assert oct(os.stat(staging).st_mode & 0o777) == "0o700"
    with pytest.raises(RuntimeError):
        updater.download_verified(dict(release, hash="0" * 64), staging)
    assert not os.path.exists(staging)


def test_bios_download_needs_a_published_checksum(home):
    m = _module(news.News)
    with pytest.raises(RuntimeError, match="checksum"):
        m._download({"version": "318", "url": news.ASUS_CDN + "/pub/x.zip", "sha256": ""})


def test_channel_comes_from_holo_select_branch_first(monkeypatch):
    seen = []

    def fake(cmd, timeout=60, **kw):
        seen.append(cmd[0])
        return util.Result(0, "beta\n", "") if cmd[0] == "holo-select-branch" else util.Result(127, "", "")

    monkeypatch.setattr(news, "run", fake)
    assert news.steamos_channel() == "beta" and seen == ["holo-select-branch"]
    monkeypatch.setattr(news, "run", lambda cmd, timeout=60, **kw:
                        util.Result(0, "rel\n", "") if cmd[0] == "steamos-select-branch" else util.Result(127, "", ""))
    assert news.steamos_channel() == "rel"


# ------------------------------------------------------------------ jack events and polling

def test_jack_switch_events_are_parsed(sysroot):
    ev = jacksense.EVENT
    batch = ev.pack(1, 2, 0x05, 0x02, 1) + ev.pack(1, 3, 0x00, 0x00, 0) + ev.pack(1, 4, 0x05, 0x04, 1)
    assert jacksense.parse(batch) is True
    assert jacksense.parse(ev.pack(1, 5, 0x05, 0x02, 0)) is False
    assert jacksense.parse(ev.pack(1, 5, 0x01, 0x02, 1)) is None
    _write(sysroot, "sys/class/input/event12/device/name", "HD-Audio Generic Headset Mic\n")
    _write(sysroot, "sys/class/input/event12/device/capabilities/sw", "10\n")
    assert jacksense.find_device() is None
    _write(sysroot, "sys/class/input/event13/device/name", "HD-Audio Generic Headphone\n")
    _write(sysroot, "sys/class/input/event13/device/capabilities/sw", "4\n")
    assert jacksense.find_device() == "/dev/input/event13"


def test_jack_watcher_polls_rarely_with_events_and_densely_after_one():
    w = jackwatch.JackWatcher()
    assert w.next_delay() == 3.0
    w.event_driven = True
    assert w.next_delay() == jackwatch.IDLE_S
    w.kick()
    assert w.next_delay() == jackwatch.BURST_STEP_S


def test_status_rounds_share_one_pw_dump_and_python_version(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(hardware, "run", lambda cmd, timeout=60: calls.append(cmd[0]) or util.Result(0, '[{"id": 1}]', ""))
    monkeypatch.setattr(hardware, "_dump", (0.0, []))
    assert hardware.pw_dump(2.0) == [{"id": 1}] and hardware.pw_dump(2.0) == [{"id": 1}] and calls == ["pw-dump"]
    hardware.pw_dump()  # watchers ask for a fresh one
    assert calls == ["pw-dump", "pw-dump"]
    py = tmp_path / "python3"
    py.write_text("x")
    asked = []
    monkeypatch.setattr(convert.paths, "SYSTEM_PYTHON", str(py))
    monkeypatch.setattr(convert, "_py_version", (None, None))
    monkeypatch.setattr(convert, "run", lambda cmd, timeout=60: asked.append(1) or util.Result(0, "3.14.6\n", ""))
    assert convert.system_python_version() == "3.14.6" == convert.system_python_version() and asked == [1]


# ------------------------------------------------------------------ speaker DSP

def test_dsp_setup_state_has_its_own_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(dsp_paths, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(dsp_paths, "SETUP_FILE", str(tmp_path / "setup.json"))
    _write_json(str(tmp_path / "settings.json"), {"enabled": True, "setup": {"done": True, "xmlSha256": "a"},
                                                  "perApp": {"1": {"profile": "nope"}, "2": {"profile": "music", "voicing": "warm"}}})
    s = dsp_settings.load()
    assert s["setup"]["done"] and list(s["perApp"]) == ["2"]
    dsp_settings.save(s)  # not moved yet: the copy stays
    assert "setup" in json.loads((tmp_path / "settings.json").read_text())
    assert dsp_settings.migrate_setup() and json.loads((tmp_path / "setup.json").read_text())["done"] is True
    s["global"]["profile"] = "music"
    dsp_settings.save(s)
    assert "setup" not in json.loads((tmp_path / "settings.json").read_text())
    dsp_settings.update_section("setup", {"extrasSignature": "x"})
    assert json.loads((tmp_path / "settings.json").read_text())["global"]["profile"] == "music"
    assert dsp_settings.load()["setup"]["extrasSignature"] == "x"
    s["extras"]["preGainDb"] = 99
    dsp_settings.save(s)
    assert dsp_settings.load()["extras"]["preGainDb"] == 6.0


def test_packages_without_a_checksum_are_not_downloaded(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError):
        asus_fetch.download("https://x/y.exe", str(tmp_path / "y"), None)
    with pytest.raises(RuntimeError):
        asus_fetch.download("http://x/y.exe", str(tmp_path / "y"), "a" * 64)
    api = {"Result": {"Obj": [{"Files": [{"Title": "Dolby Atmos driver", "Version": "V99", "ReleaseDate": "2027/01/01",
                                          "DownloadUrl": {"Global": "/pub/new.exe"}}]}]}}
    monkeypatch.setattr(asus_fetch, "_curl_json", lambda url, timeout=30: api)
    pkg = asus_fetch.resolve_package("10431384")
    assert pkg["source"] == "fallback" and len(pkg["sha256"]) == 64


# ------------------------------------------------------------------ Decky's bundled Python

# What Decky Loader's PyInstaller Python (3.11, Decky 3.2.10) provides to the backend, verified by the
# backend starting on the device with each of these. Not everything of the stdlib is there: 0.5.0
# first imported cmath and failed to start. A new import goes here only after a check on the device.
DECKY_PYTHON = {"__future__", "asyncio", "base64", "ctypes", "errno", "fcntl", "glob", "hashlib", "json", "logging",
                "math", "os", "re", "shlex", "shutil", "socket", "stat", "struct", "subprocess", "sys", "threading",
                "time", "typing", "urllib"}
OWN = {"allycompanion", "allydsp", "decky"}
SYSTEM_PYTHON = {"py_modules/allydsp/worker.py", "py_modules/allycompanion/cli.py"}  # run by /usr/bin/python3
CLI_ONLY = {("py_modules/allycompanion/minisign.py", "argparse")}  # its main(), never called by the backend


def test_backend_imports_only_what_deckys_python_bundles():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    files = ["main.py"] + [os.path.relpath(os.path.join(d, f), root)
                           for d, _, fs in os.walk(os.path.join(root, "py_modules")) for f in fs if f.endswith(".py")]
    missing = set()
    for rel in files:
        if rel in SYSTEM_PYTHON:
            continue
        with open(os.path.join(root, rel)) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            missing.update((rel, n) for n in names if n not in DECKY_PYTHON | OWN and (rel, n) not in CLI_ONLY)
    assert not missing, f"not known to exist in Decky's Python (check on the device first): {sorted(missing)}"


# ------------------------------------------------------------------ found on the device (0.5.0)

def test_cancelling_the_worker_is_not_swallowed_by_a_preset_error_handler(tmp_path, monkeypatch):
    from allydsp import setup_flow
    xml = tmp_path / "tuning.xml"
    xml.write_text("<device_data/>")
    monkeypatch.setattr(convert.paths, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(hardware, "lv2_check", lambda: {"calf": False})
    calls = []

    def convert_one(*args, **kwargs):
        calls.append(1)
        raise setup_flow.Cancelled("SIGTERM")  # what the worker's signal handler raises

    monkeypatch.setattr(convert, "convert_one", convert_one)
    with pytest.raises(setup_flow.Cancelled):
        convert.convert_all(str(xml), "sink", {})
    assert calls == [1]  # stopped at the first preset instead of converting all fifteen


def test_stopping_the_audio_worker_ends_every_call():
    import signal
    import subprocess
    import sys
    w = audio.Worker()
    polite = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    stubborn = subprocess.Popen([sys.executable, "-c",
                                 "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(1, flush=True); time.sleep(60)"],
                                stdout=subprocess.PIPE)
    stubborn.stdout.readline()  # its handler is in place
    w._procs.update({polite, stubborn})
    started = time.monotonic()
    w.stop_all(grace=0.5)
    assert polite.poll() is not None and stubborn.poll() == -signal.SIGKILL and time.monotonic() - started < 5


def test_progress_of_a_stopped_setup_is_ignored():
    async def main():
        m = audio.Audio()
        seen = {}
        gate = threading.Event()

        def run(args, progress=None, timeout=3600):
            seen["progress"] = progress
            gate.wait(5)

        m.worker.run = run
        m.dsp = lambda: {"extras": {}, "setup": {}, "enabled": False}
        await m.run_setup()
        await asyncio.sleep(0.05)
        await m.stop()
        seen["progress"]({"step": "convert", "status": "running", "message": "late line", "percent": 70})
        assert m.setup_last["status"] == "cancelled"
        gate.set()

    asyncio.run(main())


def test_news_keep_their_items_when_a_source_does_not_answer(monkeypatch):
    m = _module(news.News, {"items": [{"id": "steamos:SteamOS 3.9.2", "kind": "steamos", "newer": True, "url": None}],
                            "fetchedAt": 100})
    monkeypatch.setattr(news.device, "info", lambda: {"osVersion": "3.9.2", "board": "RC73XA", "bios": "RC73XA.317"})
    monkeypatch.setattr(news, "steamos_channel", lambda: "beta")

    def offline(url):
        raise RuntimeError("Could not resolve host")

    monkeypatch.setattr(news, "fetch_json", offline)
    asyncio.run(m.refresh())
    assert m.cfg["fetchedAt"] == 100 and [i["id"] for i in m.cfg["items"]] == ["steamos:SteamOS 3.9.2"]
    assert "Could not resolve host" in m.cfg["error"] and m.due() is False  # retried after RETRY_S, not 6 h

    def partly(url):
        if "known-issues" in url:
            return {"issues": [{"id": "x", "title": "X"}]}
        raise RuntimeError("Could not resolve host")

    monkeypatch.setattr(news, "fetch_json", partly)
    asyncio.run(m.refresh())
    assert m.cfg["fetchedAt"] > 100 and [i["id"] for i in m.cfg["items"]] == ["issue:x", "steamos:SteamOS 3.9.2"]


def test_fan_revert_brings_back_firmware_auto_and_the_factory_curve(sysroot):
    d = _fake_fan(sysroot, FACTORY)
    m = _module(fan.Fan, {"enabled": True})
    asyncio.run(m.revert())
    assert open(os.path.join(d, "pwm1_enable")).read() == "3" and open(os.path.join(d, "pwm2_enable")).read() == "3"
