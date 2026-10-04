"""Live sensor values for the Overview page; plain sysfs reads, polled only while the page is open."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import sysfs

POLICY_GLOB = "sys/devices/system/cpu/cpu[0-9]*/cpufreq"
ARMOURY = "sys/class/firmware-attributes/asus-armoury/attributes"


def _hwmon_value(name: str, attr: str, scale: float) -> Optional[float]:
    d = sysfs.find_hwmon(name)
    v = sysfs.read_int(os.path.join(d, attr)) if d else None
    return round(v / scale, 1) if v is not None else None


def cpu() -> Dict[str, Any]:
    cur: List[int] = []
    caps: List[int] = []
    over = 0
    hw_max = None
    for pol in sysfs.sorted_glob(POLICY_GLOB):
        c = sysfs.read_int(os.path.join(pol, "scaling_cur_freq"))
        m = sysfs.read_int(os.path.join(pol, "scaling_max_freq"))
        hw_max = hw_max or sysfs.read_int(os.path.join(pol, "cpuinfo_max_freq"))
        if c is not None:
            cur.append(c)
        if m is not None:
            caps.append(m)
        if c is not None and m is not None and c > m + 50_000:
            over += 1
    return {
        "boost": sysfs.read_str(sysfs.p("sys/devices/system/cpu/cpufreq/boost")) == "1",
        "avgMHz": round(sum(cur) / len(cur) / 1000) if cur else None,
        "maxMHz": round(max(cur) / 1000) if cur else None,
        "capMHz": round(max(caps) / 1000) if caps else None,
        "hwMaxMHz": round(hw_max / 1000) if hw_max else None,
        "cores": len(cur),
        "overCap": over,
        "tempC": _hwmon_value("k10temp", "temp1_input", 1000),
    }


def gpu() -> Dict[str, Any]:
    busy = None
    for path in sysfs.sorted_glob("sys/class/drm/card[0-9]/device/gpu_busy_percent"):
        busy = sysfs.read_int(path)
        break
    return {
        "tempC": _hwmon_value("amdgpu", "temp1_input", 1000),
        "clockMHz": _hwmon_value("amdgpu", "freq1_input", 1e6),
        "busyPct": busy,
        "apuW": _hwmon_value("amdgpu", "power1_average", 1e6),
    }


def snapshot() -> Dict[str, Any]:
    fan_dir = sysfs.find_hwmon("asus")
    bat = "sys/class/power_supply/BAT0"
    power = sysfs.read_int(sysfs.p(f"{bat}/power_now"))
    return {
        "cpu": cpu(),
        "gpu": gpu(),
        "fansRpm": [sysfs.read_int(os.path.join(fan_dir, f"fan{i}_input")) for i in (1, 2)] if fan_dir else [],
        "battery": {"capacity": sysfs.read_int(sysfs.p(f"{bat}/capacity")), "status": sysfs.read_str(sysfs.p(f"{bat}/status")),
                    "powerW": round(power / 1e6, 1) if power is not None else None},
        "platformProfile": sysfs.read_str(sysfs.p("sys/firmware/acpi/platform_profile")),
        "pptW": [sysfs.read_int(sysfs.p(f"{ARMOURY}/{a}/current_value")) for a in ("ppt_pl1_spl", "ppt_pl2_sppt", "ppt_pl3_fppt")],
    }
