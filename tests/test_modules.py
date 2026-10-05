import asyncio
import os

import pytest

from allycompanion import conflicts, migrate, paths, util
from allycompanion.module import Context
from allycompanion.modules import (MODULES, battery, cpu_boost, fan, gamepad_layout, gyro, headphones, lighting, mic, news,
                                   profiles, vibration)
from allycompanion.registry import Registry

STOCK = """name: ASUS ROG Xbox Ally
source_devices:
  - group: imu
    iio:
      mount_matrix:
        x: [1, 0, 0]
        y: [0, -1, 0]
        z: [0, 0, -1]
"""


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


@pytest.fixture
def sysroot(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SYSROOT", str(tmp_path))
    return str(tmp_path)


def _module(cls, cfg=None):
    m = cls()

    async def emit(e, p):
        pass

    m.bind({**cls.defaults, **(cfg or {})}, Context(lambda: None, emit))
    return m


def test_all_modules_have_unique_ids_and_json_defaults():
    reg = Registry(MODULES)
    assert list(reg.modules) == ["audio", "mic", "headphones", "vibration", "gyro", "gamepad_layout", "cpu_boost", "fan", "battery", "lighting",
                                 "profiles", "news"]
    util.write_json  # defaults must be JSON-serialisable
    import json
    json.dumps(reg.defaults())


# ------------------------------------------------------------------ gyro

def test_gyro_modes_patch_exactly_one_thing():
    assert "y: [0, 1, 0]" in gyro.patch(STOCK, "simple")
    c = gyro.patch(STOCK, "complex")
    assert "y: [0, 0, -1]" in c and "z: [0, -1, 0]" in c
    assert "name: ASUS ROG Xbox Ally (Deck Emulation)" in gyro.patch(STOCK, "deck")
    assert "name: ASUS ROG Ally X (Deck Emulation)\n" in gyro.patch(STOCK.replace("Xbox Ally", "Ally X"), "deck")
    with pytest.raises(RuntimeError):
        gyro.patch(STOCK.replace("y: [0, -1, 0]", "y: [0, 1, 0]"), "simple")
    rendered = gyro.render(STOCK, "a" * 64, "simple")
    assert rendered.startswith("# managed-by: ally-companion\n# stock-sha256: " + "a" * 64)
    assert gyro.body(rendered) == gyro.body(gyro.patch(STOCK, "simple"))


def test_steam_dev_cfg_edit_keeps_other_lines_and_restores_foreign_value():
    text = "@nClientDownloadEnableHTTP2PlatformLinux 0\r\ngyro_force_handheld_orientation 1\r\n"
    new, prev = gyro.edit_steam_cfg(text, True, "")
    assert new == "@nClientDownloadEnableHTTP2PlatformLinux 0\r\ngyro_force_handheld_orientation 2\r\n"
    assert prev == "gyro_force_handheld_orientation 1"
    back, prev2 = gyro.edit_steam_cfg(new, False, prev)
    assert back == text and prev2 == ""
    new, prev = gyro.edit_steam_cfg(None, True, "")
    assert new == "gyro_force_handheld_orientation 2\n"
    assert gyro.edit_steam_cfg(new, False, prev)[0] is None  # only our line: file goes


def test_gyro_takes_over_ally_fix_override(tmp_path, monkeypatch):
    stock = tmp_path / "stock.yaml"
    stock.write_text(STOCK)
    override = tmp_path / "override.yaml"
    monkeypatch.setattr(gyro, "stock_path", lambda: str(stock))
    monkeypatch.setattr(gyro, "override_path", lambda: str(override))
    m = _module(gyro.Gyro, {"enabled": True})
    assert m.override_state() == "absent"
    override.write_text(gyro.render(STOCK, gyro.sha256(str(stock)), "simple").replace("ally-companion", "ally-fix"))
    assert m.override_state() == "mismatch"  # managed by the predecessor: rewritten with our marker
    override.write_text(gyro.render(STOCK, gyro.sha256(str(stock)), "simple"))
    assert m.override_state() == "current"
    override.write_text(gyro.render(STOCK, "b" * 64, "simple"))
    assert m.override_state() == "stale"
    override.write_text("name: something else\n")
    assert m.override_state() == "foreign"


def test_gyro_config_follows_the_board(sysroot):
    _write(sysroot, "sys/class/dmi/id/board_name", "RC72LA\n")
    assert gyro.override_path() == "/etc/inputplumber/devices.d/50-rog_ally_x.yaml"
    _write(sysroot, "sys/class/dmi/id/board_name", "RC73XA\n")
    assert gyro.stock_path() == "/usr/share/inputplumber/devices/50-rog_xbox_ally.yaml"
    _write(sysroot, "sys/class/dmi/id/board_name", "RC71L\n")
    assert gyro.config_file() is None and not gyro.Gyro().supported()[0]


def test_enhanced_vibration_boards(sysroot):
    from allycompanion import device
    for board, expected in (("RC73XA", True), ("RC72LA", True), ("RC71L", False)):
        _write(sysroot, "sys/class/dmi/id/board_name", board + "\n")
        assert device.has_enhanced_vibration() is expected
        assert device.has_impulse_triggers() is (board == "RC73XA")


# ------------------------------------------------------------------ gamepad layout

def test_layout_dropin_repeats_other_preloads(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    unit = b"[Service]\nEnvironment=LD_PRELOAD=/usr/lib/libfoo.so\n"
    assert gamepad_layout.preload_from(unit, []) == ["/usr/lib/libfoo.so"]
    assert gamepad_layout.preload_from(b"Environment=\n", ["/x.so"]) == []
    d = tmp_path / ".config/systemd/user/steam-launcher.service.d"
    d.mkdir(parents=True)
    (d / "10-other.conf").write_text('[Service]\nEnvironment="LD_PRELOAD=/opt/a.so /opt/b.so"\n')
    (d / "zz-ally-fix-gamepad-layout.conf").write_text("Environment=LD_PRELOAD=/home/x/.local/lib/ally-fix/$LIB/liballycaps.so\n")
    monkeypatch.setattr(gamepad_layout, "dropin_dirs", lambda: (str(d),))
    monkeypatch.setattr("allycompanion.steam.UNIT_FILE", str(tmp_path / "missing.service"))
    m = _module(gamepad_layout.GamepadLayout)
    text = m.dropin_text()
    assert f"Environment=LD_PRELOAD=/opt/a.so:/opt/b.so:{tmp_path}/.local/lib/ally-companion/$LIB/liballycaps.so" in text
    assert "ALLYCAPS_MASK=0x60afff" in text


# ------------------------------------------------------------------ vibration

def test_vibration_options_link_and_clamp():
    m = _module(vibration.Vibration)
    assert m.set_options({"left": 150})
    assert m.intensity == (100, 100)
    m.set_options({"linked": False, "right": -5})
    assert m.intensity == (100, 0)
    assert not m.set_options({"unknown": 1})


# ------------------------------------------------------------------ power

def test_cpu_policies_sorted_numerically(sysroot):
    for n in (0, 2, 10, 1):
        _write(sysroot, f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_max_freq", "2000000")
    assert [os.path.basename(os.path.dirname(p)) for p in cpu_boost.policies()] == ["cpu0", "cpu1", "cpu2", "cpu10"]


def test_fan_curve_sanitize():
    c = fan.sanitize({"temps": [30, 25, 50, 60, 70, 80, 90, 200], "pwm1": [0, 10, 5, 300, 0, 0, 0, 0],
                      "pwm2": [1, 2, 3, 4, 5, 6, 7, 8]})
    assert c["temps"] == [30, 30, 50, 60, 70, 80, 90, 110]
    assert c["pwm1"] == [0, 10, 10, 255, 255, 255, 255, 255]
    assert fan.valid(c)
    with pytest.raises(ValueError):
        fan.sanitize({"temps": [1, 2], "pwm1": [], "pwm2": []})


def test_battery_info_from_sysfs(sysroot):
    for name, v in (("capacity", "80"), ("status", "Discharging"), ("energy_full", "75328000"),
                    ("energy_full_design", "80003000"), ("cycle_count", "0"), ("power_now", "12500000")):
        _write(sysroot, f"sys/class/power_supply/BAT0/{name}", v)
    info = battery.battery_info()
    assert info["healthPct"] == 94.2 and info["cycles"] is None and info["powerW"] == 12.5


# ------------------------------------------------------------------ lighting

def test_lighting_colors():
    assert lighting.parse_color("#FF0040") == (255, 0, 64)
    assert lighting.parse_color("bogus") == (255, 255, 255)
    assert lighting.battery_color(10, False) == ((255, 0, 0), "breathing")
    assert lighting.battery_color(100, False) == ((0, 255, 0), "static")
    assert lighting.battery_color(25, True)[1] == "breathing"


def test_lighting_static_writes_sysfs(sysroot):
    _write(sysroot, "sys/class/leds/ally:rgb:joystick_rings/brightness", "0")
    _write(sysroot, "sys/class/leds/ally:rgb:joystick_rings/multi_intensity", "0 0 0 0")
    m = _module(lighting.Lighting, {"enabled": True, "mode": "static", "color": "#ff0040", "brightness": 50})
    asyncio.run(m.apply())
    base = os.path.join(sysroot, "sys/class/leds/ally:rgb:joystick_rings")
    assert open(os.path.join(base, "multi_intensity")).read() == " ".join([str(0xFF0040)] * 4)
    assert open(os.path.join(base, "brightness")).read() == "128"
    asyncio.run(m.set_override({"color": "#00ff00"}))
    assert open(os.path.join(base, "multi_intensity")).read().startswith(str(0x00FF00))


# ------------------------------------------------------------------ predecessors

def test_conflicts_and_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    plugins = tmp_path / "homebrew/plugins"
    (plugins / "Ally Fix").mkdir(parents=True)
    (plugins / "Ally Fix/plugin.json").write_text("{}")
    util.write_json(str(tmp_path / "homebrew/settings/Ally Fix/settings.json"), {
        "vibration": {"enabled": True, "left": 40, "right": 40, "enhanced": True},
        "gyro": {"enabled": True, "mode": "complex", "steam_cfg_prev": ""},
        "gamepad_layout": {"enabled": True},
        "cpu_boost": {"enabled": True, "refresh_on_charger": False},
        "fan": {"enabled": True, "curves": {"balanced": {"temps": [1] * 8}}},
    })
    assert conflicts.blocked()["gyro"] == "Ally Fix"
    reg = Registry(MODULES)
    s = {"modules": reg.defaults()}
    assert migrate.run(s, reg.defaults()) == []  # still installed: nothing imported yet
    (plugins / "Ally Fix/plugin.json").unlink()
    assert conflicts.blocked() == {}
    s["modules"]["fan"]["enabled"] = True  # changed by the user already: left alone
    assert migrate.run(s, reg.defaults()) == ["Ally Fix"]
    assert s["modules"]["vibration"] == {**vibration.Vibration.defaults, "enabled": True, "left": 40, "right": 40,
                                         "enhanced": True}
    assert s["modules"]["gyro"]["mode"] == "complex" and s["modules"]["gamepad_layout"]["enabled"]
    assert s["modules"]["cpu_boost"]["refreshOnCharger"] is False
    assert s["modules"]["fan"]["curves"] == {}
    assert migrate.run(s, reg.defaults()) == []  # once only


# ------------------------------------------------------------------ news

STEAM = {"appnews": {"newsitems": [
    {"title": "SteamOS 3.9.2 Beta", "date": 3, "url": "u3", "contents": "[list][*]Improved ROG Ally gyro[*]Other fix[/list]"},
    {"title": "SteamOS 3.8.28", "date": 2, "url": "u2", "contents": "[list][*]Fixed InputPlumber crash on resume[/list]"},
    {"title": "SteamOS 3.9.1 Preview", "date": 1, "url": "u1", "contents": ""},
    {"title": "Steam Beta Client Update", "date": 4, "url": "u4", "contents": ""},
]}}


def test_steamos_news_follow_the_channel():
    stable = news.steamos_items(STEAM, news.CHANNELS["rel"], (3, 8, 27))
    assert [i["version"] for i in stable] == ["3.8.28"] and stable[0]["newer"]
    assert stable[0]["highlights"] == ["Fixed InputPlumber crash on resume"]
    beta = news.steamos_items(STEAM, news.CHANNELS["beta"], (3, 8, 28))
    assert [i["title"] for i in beta] == ["SteamOS 3.9.2 Beta", "SteamOS 3.8.28"]
    assert beta[0]["newer"] and not beta[1]["newer"] and beta[0]["highlights"] == ["Improved ROG Ally gyro"]


def test_bios_and_issues():
    data = {"Result": {"Obj": [
        {"Name": "BIOS", "Files": [{"Version": "318", "Title": "BIOS for ASUS EZ Flash Utility", "ReleaseDate": "2026/09/01",
                                    "DownloadUrl": {"Global": "/pub/x/RC73XAAS318.zip"}, "sha256": "AB"}]},
        {"Name": "BIOS Update (Windows)", "Files": [{"Version": "318"}]},
    ]}}
    items = news.bios_items(data, "RC73XA.317")
    assert len(items) == 1 and items[0]["newer"] and items[0]["url"] == "https://dlcdnets.asus.com/pub/x/RC73XAAS318.zip"
    assert items[0]["sha256"] == "ab"
    assert not news.bios_items(data, "RC73XA.318")[0]["newer"]
    issues = {"issues": [{"id": "a", "title": "A", "steamosFrom": "3.9.0"}, {"id": "b", "title": "B", "boards": ["RC72LA"]},
                         {"id": "c", "title": "C"}]}
    assert [i["id"] for i in news.issue_items(issues, (3, 8, 28), "RC73XA")] == ["issue:c"]


def test_news_unseen_and_mark_seen():
    m = _module(news.News, {"items": [{"id": "a", "newer": True}, {"id": "b", "newer": False}]})
    assert m.unseen() == ["a"]
    asyncio.run(m.mark_seen())
    assert m.unseen() == []


# ------------------------------------------------------------------ profiles

class _Target:
    def __init__(self):
        self.values = "unset"

    def supported(self):
        return True, ""

    async def set_override(self, values):
        self.values = values


def test_profiles_push_overrides_on_app_change():
    m = _module(profiles.Profiles)
    light, vib = _Target(), _Target()
    m.ctx.modules = {"lighting": light, "vibration": vib}
    perf = []
    import allycompanion.modules.profiles as prof_mod
    prof_mod.get_perf_profile = lambda: "balanced" if not perf else perf[-1]
    prof_mod.set_perf_profile = lambda p: perf.append(p)
    asyncio.run(m.set_app(appId="42", part="lighting", values={"color": "#00ff00"}, name="Game"))
    assert light.values == "unset"  # not running yet
    asyncio.run(m.on_app_changed("42"))
    assert light.values == {"color": "#00ff00"} and vib.values is None
    asyncio.run(m.set_app(appId="42", part="vibration", values={"left": 20}))
    assert vib.values == {"left": 20}
    asyncio.run(m.on_app_changed(None))
    assert light.values is None and vib.values is None
    asyncio.run(m.set_app(appId="42", part="lighting", values=None))
    asyncio.run(m.set_app(appId="42", part="vibration", values=None))
    assert m.apps() == {}

    asyncio.run(m.set_app(appId="42", part="performance", values={"profile": "performance"}))
    asyncio.run(m.on_app_changed("42"))
    assert perf == ["performance"] and m.cfg["perfBaseline"] == "balanced"
    asyncio.run(m.on_app_changed(None))
    assert perf == ["performance", "balanced"] and m.cfg["perfBaseline"] is None


def test_cpu_boost_and_fan_overrides(sysroot, monkeypatch):
    _write(sysroot, "sys/devices/system/cpu/cpufreq/boost", "1")
    _write(sysroot, "sys/class/dmi/id/sys_vendor", "ASUSTeK COMPUTER INC.")
    m = _module(cpu_boost.CpuBoost, {"enabled": False})
    calls = []

    async def apply():
        calls.append("apply")

    async def revert():
        calls.append("revert")

    m.apply, m.revert = apply, revert
    asyncio.run(m.set_override({"boost": False}))  # keep boost off in this game
    assert m.active and calls == ["apply"]
    asyncio.run(m.set_override(None))
    assert not m.active and calls == ["apply", "revert"]
    m.cfg["enabled"] = True
    asyncio.run(m.set_override({"boost": True}))  # boost allowed in this game
    assert not m.active and calls[-1] == "revert"

    f = _module(fan.Fan, {"enabled": False})
    pinned = []
    monkeypatch.setattr(f, "_pin", lambda reason, force_write=False: pinned.append(reason) or reason)
    monkeypatch.setattr(f, "_start_watchdog", lambda: None)

    async def frevert():
        pinned.append("revert")

    f.revert = frevert
    curve = {"temps": [40, 50, 60, 65, 70, 75, 80, 90], "pwm1": [0, 20, 40, 60, 80, 100, 120, 140],
             "pwm2": [0, 20, 40, 60, 80, 100, 120, 140]}
    asyncio.run(f.set_override({"curve": curve}))
    assert f.active and pinned == ["game profile"]
    asyncio.run(f.set_override(None))
    assert not f.active and pinned[-1] == "revert"


# ------------------------------------------------------------------ microphone and headphones

def test_internal_mic_prefers_valves_loopback_source():
    srcs = [{"name": "alsa_input.pci-0000_64_00.6.analog-stereo"},
            {"name": "alsa_loopback_device.alsa_input.pci-0000_64_00.6.analog-stereo"}, {"name": "bluez_input.x"}]
    assert mic.internal_mic(srcs) == "alsa_loopback_device.alsa_input.pci-0000_64_00.6.analog-stereo"
    assert mic.internal_mic(srcs[:1]) == "alsa_input.pci-0000_64_00.6.analog-stereo"
    assert mic.internal_mic([{"name": "bluez_input.x"}]) is None
    conf = mic.config("alsa_input.x", 60)
    assert 'target.object = "alsa_input.x"' in conf and "priority.session = 2500" in conf and '"VAD %%" = 60.0' in conf and 'label = "nt-filter"' in conf


INDEX = """# Index
- [Sennheiser HD 650](./oratory1990/over-ear/Sennheiser%20HD%20650) by oratory1990
- [Sennheiser HD 600](./oratory1990/over-ear/Sennheiser%20HD%20600) by oratory1990
- [1MORE Aero (ANC On)](./HypetheSonics/GRAS%20RA0045%20in-ear/1MORE%20Aero%20(ANC%20On)) by HypetheSonics on GRAS RA0045
"""

PEQ = """Preamp: -6.1 dB
Filter 1: ON LSC Fc 105 Hz Gain 6.4 dB Q 0.70
Filter 2: ON PK Fc 8800 Hz Gain 5.1 dB Q 1.42
Filter 3: ON HSC Fc 10000 Hz Gain -2.1 dB Q 0.70
Filter 4: OFF PK Fc 100 Hz Gain 1 dB Q 1
"""


def test_autoeq_index_search_and_profile():
    idx = headphones.parse_index(INDEX)
    assert idx[0] == {"name": "Sennheiser HD 650", "path": "oratory1990/over-ear/Sennheiser HD 650", "source": "oratory1990"}
    assert idx[2]["path"] == "HypetheSonics/GRAS RA0045 in-ear/1MORE Aero (ANC On)"
    assert [e["name"] for e in headphones.search(idx, "hd 6")] == ["Sennheiser HD 600", "Sennheiser HD 650"]
    assert headphones.search(idx, "  ") == []
    eq = headphones.parse_parametric(PEQ)
    assert eq["preamp"] == -6.1 and [f["type"] for f in eq["filters"]] == ["bq_lowshelf", "bq_peaking", "bq_highshelf"]
    conf = headphones.config({**eq, "name": "HD 650", "source": "oratory1990"}, "alsa_output.x")
    assert '"Gain" = -6.10' in conf and 'output = "f2:Out" input = "f3:In"' in conf
    assert 'filter.smart.target = { node.name = "alsa_output.x" }' in conf
    with pytest.raises(ValueError):
        headphones.parse_parametric("Preamp: 0 dB")


# ------------------------------------------------------------------ review fixes and hardening

def test_userfs_helper_writes_removes_and_unzips(tmp_path):
    import zipfile
    from allycompanion import userfs
    target = tmp_path / "a" / "b" / "file.txt"
    userfs.write(str(target), b"hello", 0o600)
    assert target.read_bytes() == b"hello" and oct(target.stat().st_mode & 0o777) == "0o600"
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.cap", b"x")  # path parts are dropped
        zf.writestr("dir/RC73XA.CAP", b"y")
    assert sorted(userfs.unzip(str(z), str(tmp_path / "a"))) == ["RC73XA.CAP", "evil.cap"]
    assert (tmp_path / "a" / "evil.cap").exists() and not (tmp_path.parent / "evil.cap").exists()
    userfs.remove(str(target), str(tmp_path / "missing"))
    assert not target.exists()


def test_bios_download_refuses_tampered_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOME", str(tmp_path))
    m = _module(news.News)
    for bad in ({"version": "../../etc", "url": news.ASUS_CDN + "/x.zip"},
                {"version": "317", "url": "https://evil.example/x.zip"},
                {"version": "317", "url": news.ASUS_CDN + "/../x.zip"}):
        with pytest.raises(RuntimeError):
            m._download(bad)


def test_release_signature_is_checked_in_memory(monkeypatch):
    from allycompanion import minisign, updater
    seed, pub = minisign.generate_keypair("test")
    sums = "a" * 64 + "  ally-companion-9.9.9.zip\n"
    sig = minisign.sign_bytes(sums.encode(), seed, pub, "ally-companion v9.9.9")
    base = "https://github.com/bassobr/Decky-Ally-Companion/releases/download/v9.9.9/"
    assets = {"ally-companion-9.9.9.zip": base + "z.zip", "SHA256SUMS": base + "s", "SHA256SUMS.minisig": base + "m"}
    monkeypatch.setattr(updater, "_fetch_text", lambda url, timeout=30: sums if url.endswith("/s") else sig)
    import builtins
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda p, *a, **k: __import__("io").StringIO(pub) if p == "PUB" else real_open(p, *a, **k))
    res = updater.verify_release({"version": "9.9.9", "assets": assets}, "PUB")
    assert res["hash"] == "a" * 64
    monkeypatch.setattr(updater, "_fetch_text", lambda url, timeout=30: sums.replace("a", "b") if url.endswith("/s") else sig)
    with pytest.raises(RuntimeError):
        updater.verify_release({"version": "9.9.9", "assets": assets}, "PUB")
    foreign = dict(assets, **{"ally-companion-9.9.9.zip": "https://evil.example/z.zip"})
    with pytest.raises(RuntimeError):
        updater.verify_release({"version": "9.9.9", "assets": foreign}, "PUB")


def test_toggles_follow_game_profile_overrides(sysroot):
    _write(sysroot, "sys/devices/system/cpu/cpufreq/boost", "1")
    _write(sysroot, "sys/class/dmi/id/sys_vendor", "ASUSTeK COMPUTER INC.")
    m = _module(cpu_boost.CpuBoost, {"enabled": False})
    calls = []

    async def apply():
        calls.append("apply")

    async def revert():
        calls.append("revert")

    m.apply, m.revert = apply, revert
    asyncio.run(m.set_override({"boost": True}))  # this game wants boost
    asyncio.run(m.set_enabled(True))  # switch flipped mid-game
    assert calls[-1] == "revert"  # boost stays on until the game ends
    asyncio.run(m.set_override({"boost": False}))
    asyncio.run(m.set_enabled(False))
    assert calls[-1] == "apply"  # this game keeps boost off


def test_cpu_boost_skips_the_cap_refresh_where_the_cap_holds(sysroot):
    _write(sysroot, "sys/devices/system/cpu/cpufreq/boost", "1")
    _write(sysroot, "sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq", "3301000")
    _write(sysroot, "sys/class/dmi/id/sys_vendor", "ASUSTeK COMPUTER INC.")
    _write(sysroot, "sys/class/dmi/id/board_name", "RC72LA\n")
    m = _module(cpu_boost.CpuBoost, {"enabled": True})
    asyncio.run(m.apply())
    assert m._kicks == 0 and m.details()["capSlips"] is False
    asyncio.run(m._on_power_event({"ACTION": "change", "POWER_SUPPLY_TYPE": "Mains"}))
    assert m._watch_task is None
    with pytest.raises(RuntimeError):
        asyncio.run(m.refresh_now())
    _write(sysroot, "sys/class/dmi/id/board_name", "RC73XA\n")
    assert m.cap_slips()


def test_restore_keeps_runtime_state(monkeypatch):
    from allycompanion.registry import Registry
    reg = Registry([battery.Battery, profiles.Profiles])
    s = {"modules": reg.defaults()}

    async def emit(e, p):
        pass

    reg.bind(s, Context(lambda: None, emit))
    monkeypatch.setattr("allycompanion.conflicts.blocked", lambda: {})
    s["modules"]["battery"].update({"fullOnce": 80, "history": [{"d": "2026-10-01", "h": 94.0}]})
    s["modules"]["profiles"]["perfBaseline"] = "balanced"
    for m in reg.modules.values():
        m.supported = lambda: (False, "test")  # no hardware work
    from allycompanion import backup
    asyncio.run(reg.restore({"battery": {}, "profiles": {"apps": {"1": {"name": "x"}}}}, backup.TRANSIENT))
    assert s["modules"]["battery"]["fullOnce"] == 80 and s["modules"]["battery"]["history"][0]["h"] == 94.0
    assert s["modules"]["profiles"]["perfBaseline"] == "balanced" and s["modules"]["profiles"]["apps"] == {"1": {"name": "x"}}


def test_manual_limit_ends_full_charge(monkeypatch):
    m = _module(battery.Battery, {"fullOnce": 80})
    written = []

    async def write(level):
        written.append(level)

    monkeypatch.setattr(m, "_write_limit", write)
    asyncio.run(m.set_charge_limit(70))
    assert written == [70] and m.cfg["fullOnce"] is None
