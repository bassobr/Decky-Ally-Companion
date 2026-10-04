import asyncio
import os

import pytest

from allycompanion import dbus, device, paths, settings, updater, util
from allycompanion.module import Module
from allycompanion.registry import Registry
from allycompanion.resume import ResumeDetector


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


@pytest.fixture
def sysroot(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SYSROOT", str(tmp_path))
    return str(tmp_path)


# ------------------------------------------------------------------ root/user boundary

def test_user_env_points_at_the_home_owners_session(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    monkeypatch.setattr(paths, "USER", "deck")
    uid = os.stat(str(tmp_path)).st_uid
    env = util.user_env({"X": "1"})
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{uid}"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path=/run/user/{uid}/bus"
    assert env["USER"] == "deck" and env["X"] == "1"
    assert "LD_LIBRARY_PATH" not in env


def test_drop_only_as_root_and_only_to_a_non_root_user(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert util._drop_kwargs() == {}
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(util, "user_ids", lambda: (1000, 1000))
    monkeypatch.setattr(os, "getgrouplist", lambda user, gid: [1000, 998])
    assert util._drop_kwargs() == {"user": 1000, "group": 1000, "extra_groups": [1000, 998]}
    monkeypatch.setattr(util, "user_ids", lambda: (0, 0))
    assert util._drop_kwargs() == {}


def test_root_commands_do_not_inherit_the_backend_environment(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)

        class P:
            returncode, stdout, stderr = 0, "", ""
        return P()

    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI1234")
    monkeypatch.setattr(util.subprocess, "run", fake_run)
    assert util.run(["true"]).ok
    assert "LD_LIBRARY_PATH" not in seen["env"] and "user" not in seen


# ------------------------------------------------------------------ D-Bus

def test_unwrap_nested_busctl_values():
    assert dbus.unwrap({"type": "s", "data": "0.78.0"}) == "0.78.0"
    assert dbus.unwrap({"type": "(ss)", "data": ["rog_xbox_ally_x", "RC73XA"]}) == ["rog_xbox_ally_x", "RC73XA"]
    assert dbus.unwrap({"type": "v", "data": {"type": "u", "data": 3}}) == 3


def test_property_reads_use_the_right_bus(monkeypatch):
    calls = []

    def fake_run(cmd, timeout=60, as_user=False, **kw):
        calls.append((cmd, as_user))
        return util.Result(0, '{"type":"s","data":"balanced"}', "")

    monkeypatch.setattr(dbus, "run", fake_run)
    assert dbus.get_property("a.b", "/a/b", "a.b.I", "P", user_bus=True) == "balanced"
    assert calls[-1][0][:3] == ["busctl", "--user", "--json=short"] and calls[-1][1] is True
    dbus.get_property("a.b", "/a/b", "a.b.I", "P")
    assert calls[-1][0][1] == "--system" and calls[-1][1] is False


def test_call_returns_single_values_and_failures_raise(monkeypatch):
    monkeypatch.setattr(dbus, "run", lambda cmd, **kw: util.Result(0, '{"type":"s","data":["/x/1"]}', ""))
    assert dbus.call("a.b", "/a", "a.b.I", "M", "sb", "x", True) == "/x/1"
    monkeypatch.setattr(dbus, "run", lambda cmd, **kw: util.Result(1, "", "Unknown object"))
    with pytest.raises(dbus.DBusError):
        dbus.get_property("a.b", "/a", "a.b.I", "P")
    assert dbus.try_get_property("a.b", "/a", "a.b.I", "P") is None


# ------------------------------------------------------------------ device

def test_device_info_from_sysfs(sysroot, monkeypatch):
    _write(sysroot, "sys/class/dmi/id/board_name", "RC73XA\n")
    _write(sysroot, "sys/class/dmi/id/bios_version", "RC73XA.317\n")
    _write(sysroot, "sys/module/hid_asus_ally/drivers/hid:asus_rog_ally/0003:0B05:1B4C.0003/mcu_version", "0\n")
    _write(sysroot, "etc/os-release", 'NAME="SteamOS"\nPRETTY_NAME="SteamOS"\nID=steamos\nVERSION_ID=3.8.28\nBUILD_ID=20260922.1\n')
    _write(sysroot, "proc/sys/kernel/osrelease", "6.18.50-valve2\n")
    i = device.info()
    assert i["model"] == "ROG Xbox Ally X" and i["supported"]
    assert (i["bios"], i["mcu"], i["osVersion"], i["kernel"]) == ("RC73XA.317", None, "3.8.28", "6.18.50-valve2")


def test_unknown_board_is_unsupported(sysroot):
    _write(sysroot, "sys/class/dmi/id/board_name", "RC71L\n")
    assert not device.supported() and device.model_name() is None
    assert device.info()["mcu"] is None


# ------------------------------------------------------------------ settings and modules

class FakeModule(Module):
    id = "fake"
    title = "Fake"
    defaults = {"enabled": False, "level": 50}

    def __init__(self):
        super().__init__()
        self.events = []

    def state(self):
        return {"level": self.cfg["level"]}

    async def start(self):
        self.events.append("start")

    async def on_resume(self, slept_s):
        self.events.append(("resume", slept_s))
        raise RuntimeError("boom")


class Unsupported(Module):
    id = "nope"

    def supported(self):
        return False, "no hardware"

    async def start(self):
        raise AssertionError("must not start")


def test_settings_merge_keeps_unknown_keys_and_fills_defaults():
    merged = settings.merge({"a": 1, "b": {"c": 2, "d": 3}}, {"b": {"c": 5}, "x": 9})
    assert merged == {"a": 1, "b": {"c": 5, "d": 3}, "x": 9}


def test_settings_load_adds_module_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SETTINGS_FILE", str(tmp_path / "s.json"))
    util.write_json(paths.SETTINGS_FILE, {"modules": {"fake": {"level": 70}}})
    s = settings.load({"fake": FakeModule.defaults})
    assert s["modules"]["fake"] == {"enabled": False, "level": 70}
    assert s["update"]["autoCheck"] is True


def test_registry_lifecycle_isolates_failures():
    reg = Registry([FakeModule, Unsupported])
    s = {"modules": reg.defaults()}
    saved = []

    async def emit(event, payload):
        pass

    reg.bind(s, lambda: saved.append(1), emit)
    asyncio.run(reg.start())
    asyncio.run(reg.on_resume(12.0))
    fake = reg.get("fake")
    assert fake.events == ["start", ("resume", 12.0)]
    st = reg.status()
    assert st["fake"]["error"] == "on_resume failed: boom" and st["fake"]["state"] == {"level": 50}
    assert st["nope"] == {"id": "nope", "title": "", "supported": False, "reason": "no hardware",
                          "error": None, "state": {}}


def test_registry_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        Registry([FakeModule, FakeModule])


# ------------------------------------------------------------------ resume and updates

def test_resume_detector_fires_on_clock_gap(monkeypatch):
    deltas = iter([0.0, 0.0, 30.0])
    seen = []
    monkeypatch.setattr("allycompanion.resume.POLL_S", 0)

    async def on_resume(slept):
        seen.append(slept)

    async def main():
        det = ResumeDetector(on_resume, delta=lambda: next(deltas, 30.0))
        det.start()
        for _ in range(10):
            await asyncio.sleep(0)
        det.stop()

    asyncio.run(main())
    assert seen == [30.0]


def test_version_compare_and_sums():
    assert updater.is_newer("0.2.0", "0.1.9") and not updater.is_newer("v0.1.0", "0.1.0")
    sums = updater.parse_sums("a" * 64 + "  ally-companion-0.1.0.zip\n" + "b" * 64 + " *SHA256SUMS\n")
    assert sums["ally-companion-0.1.0.zip"] == "a" * 64 and sums["SHA256SUMS"] == "b" * 64


def test_update_check_reads_only_the_cache_and_waits_after_failure(monkeypatch):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(updater, "fetch_latest", boom)
    state = {"lastCheck": 0, "lastAttempt": 0, "latest": None}
    assert updater.check(state, "0.1.0", fetch=False)["error"] is None and state["lastAttempt"] == 0
    assert updater.check(state, "0.1.0")["error"] == "offline"
    assert not updater.check_due(state)


def test_repository_without_releases_is_not_an_error(monkeypatch):
    monkeypatch.setattr(updater, "run", lambda cmd, **kw: util.Result(22, "", "curl: (22) The requested URL returned error: 404"))
    state = {"lastCheck": 0, "lastAttempt": 0, "latest": None}
    res = updater.check(state, "0.1.0")
    assert res["error"] is None and not res["updateAvailable"] and state["lastCheck"] > 0
    monkeypatch.setattr(updater, "run", lambda cmd, **kw: util.Result(22, "", "curl: (22) The requested URL returned error: 403"))
    with pytest.raises(RuntimeError):
        updater.fetch_latest()
