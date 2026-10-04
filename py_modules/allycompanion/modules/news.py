"""News: SteamOS releases for the installed channel, BIOS updates for the board, known issues.

Sources, fetched at most every six hours (or on demand):
- SteamOS release notes from the Steam news feed of the Steam Deck app (1675200), filtered to the
  channel `steamos-select-branch -c` reports, with the bullet points that mention the Ally.
- ASUS' support API for the board: BIOS for EZ Flash and firmware packages. The EZ Flash file can
  be downloaded (SHA-256 checked) to ~/Downloads.
- known-issues.json in this repository: problems between SteamOS versions and this plugin.

Items newer than what is installed count as unseen until the News page marks them seen.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from .. import device, paths, steam
from ..constants import USER_AGENT
from ..log import logger
from ..module import Module
from ..util import run

STEAM_NEWS = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=1675200&count=60&maxlength=0"
              "&feeds=steam_community_announcements")
ASUS_BIOS = "https://www.asus.com/support/webapi/ProductV2/GetPDBIOS?website=global&model={board}&cpu={board}"
ASUS_CDN = "https://dlcdnets.asus.com"
KNOWN_ISSUES = "https://raw.githubusercontent.com/bassobr/Decky-Ally-Companion/main/news/known-issues.json"
REFRESH_S = 6 * 3600
RETRY_S = 30 * 60
KEYWORDS = re.compile(r"\b(rog|ally|asus|inputplumber|xbox)\b", re.I)
# steamos-select-branch -c -> which release kinds that channel receives
CHANNELS = {"rel": ("stable",), "rc": ("stable",), "beta": ("stable", "beta"), "bc": ("stable", "beta"),
            "preview": ("stable", "beta", "preview"), "pc": ("stable", "beta", "preview"),
            "main": ("stable", "beta", "preview")}
_VERSION = re.compile(r"SteamOS\s+(\d+)\.(\d+)(?:\.(\d+))?\s*(Beta|Preview)?", re.I)


def parse_steamos_title(title: str) -> Optional[Tuple[Tuple[int, int, int], str]]:
    m = _VERSION.search(title)
    if not m:
        return None
    ver = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return ver, (m.group(4) or "stable").lower()


def version_tuple(text: str) -> Tuple[int, int, int]:
    parts = [int(x) for x in re.findall(r"\d+", text or "")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))  # type: ignore[return-value]


def strip_bbcode(text: str) -> str:
    text = re.sub(r"\[/?[a-zA-Z0-9*=_ \"':/.#-]*\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def highlights(contents: str, limit: int = 6) -> List[str]:
    """Bullet points of a release note that concern the Ally."""
    items = re.split(r"\[\*\]|\n\s*[-•]\s+", contents)
    out = []
    for it in items:
        line = strip_bbcode(it.split("[/list]")[0])
        if line and KEYWORDS.search(line) and len(line) < 400:
            out.append(line)
        if len(out) >= limit:
            break
    return out


def steamos_items(data: Dict[str, Any], kinds: Tuple[str, ...], installed: Tuple[int, int, int]) -> List[Dict[str, Any]]:
    out = []
    for it in (data.get("appnews") or {}).get("newsitems") or []:
        parsed = parse_steamos_title(str(it.get("title", "")))
        if not parsed or parsed[1] not in kinds:
            continue
        ver, kind = parsed
        out.append({"id": f"steamos:{it.get('title')}", "kind": "steamos", "title": it.get("title"), "channel": kind,
                    "version": ".".join(map(str, ver)), "date": int(it.get("date") or 0), "url": it.get("url"),
                    "newer": ver > installed, "highlights": highlights(str(it.get("contents", "")))})
    return out[:4]


def bios_items(data: Dict[str, Any], installed: str) -> List[Dict[str, Any]]:
    out = []
    for group in ((data.get("Result") or {}).get("Obj") or []):
        name = group.get("Name")
        files = group.get("Files") or []
        if name not in ("BIOS", "Firmware") or not files:
            continue
        f = files[0]
        ver = str(f.get("Version", ""))
        path = (f.get("DownloadUrl") or {}).get("Global") or ""
        newer = name == "BIOS" and version_tuple(ver) > version_tuple(installed.split(".")[-1])
        out.append({"id": f"asus:{name}:{ver}", "kind": "bios" if name == "BIOS" else "firmware", "title": f.get("Title"),
                    "version": ver, "date": f.get("ReleaseDate"), "size": f.get("FileSize"),
                    "url": ASUS_CDN + path if path else None, "sha256": str(f.get("sha256") or "").lower(),
                    "newer": newer})
    return out


def issue_items(data: Any, os_version: Tuple[int, int, int], board: str) -> List[Dict[str, Any]]:
    out = []
    for it in (data.get("issues") if isinstance(data, dict) else None) or []:
        lo, hi = it.get("steamosFrom"), it.get("steamosTo")
        if lo and os_version < version_tuple(lo) or hi and os_version > version_tuple(hi):
            continue
        if it.get("boards") and board not in it["boards"]:
            continue
        out.append({"id": f"issue:{it.get('id')}", "kind": "issue", "title": it.get("title"), "body": it.get("body"),
                    "date": it.get("date"), "url": it.get("url"), "newer": True})
    return out


def fetch_json(url: str) -> Any:
    r = run(["curl", "-fsSL", "--max-time", "20", "-A", USER_AGENT, url], timeout=30)
    if not r.ok:
        raise RuntimeError(f"{url.split('/')[2]}: curl rc={r.rc} {r.err.strip()[:120]}")
    return json.loads(r.out)


def steamos_channel() -> str:
    r = run(["steamos-select-branch", "-c"], timeout=10)
    return r.out.strip() if r.ok and r.out.strip() else "rel"


class News(Module):
    id = "news"
    title = "News"
    defaults = {"items": [], "fetchedAt": 0, "lastAttempt": 0, "error": None, "seen": [], "channel": None}

    def __init__(self) -> None:
        super().__init__()
        self._task: Optional[asyncio.Task] = None

    def actions(self):
        return {"refresh": self.refresh, "mark_seen": self.mark_seen, "download_bios": self.download_bios}

    def unseen(self) -> List[str]:
        seen = set(self.cfg.get("seen") or [])
        return [it["id"] for it in self.cfg.get("items") or [] if it.get("newer") and it["id"] not in seen]

    def details(self) -> Dict[str, Any]:
        info = device.info()
        return {"items": self.cfg.get("items") or [], "unseen": self.unseen(), "fetchedAt": self.cfg.get("fetchedAt"),
                "error": self.cfg.get("error"), "channel": self.cfg.get("channel"),
                "installed": {"steamos": info["osVersion"], "bios": info["bios"]}}

    async def start(self) -> None:
        now = time.time()
        if now - (self.cfg.get("fetchedAt") or 0) >= REFRESH_S and now - (self.cfg.get("lastAttempt") or 0) >= RETRY_S:
            self._task = asyncio.get_event_loop().create_task(self.refresh())

    async def on_resume(self, slept_s: float) -> None:
        await self.start()

    async def refresh(self) -> Dict[str, Any]:
        self.update_cfg({"lastAttempt": int(time.time())})
        items, errors = await asyncio.to_thread(self._collect)
        self.update_cfg({"items": items, "fetchedAt": int(time.time()), "error": "; ".join(errors) or None})
        if errors:
            logger.warning("[news] %s", "; ".join(errors))
        await self.notify()
        return {"unseen": len(self.unseen())}

    def _collect(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        info = device.info()
        installed = version_tuple(info["osVersion"])
        channel = steamos_channel()
        self.cfg["channel"] = channel
        items: List[Dict[str, Any]] = []
        errors = []
        try:
            items += issue_items(fetch_json(KNOWN_ISSUES), installed, info["board"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"known issues: {e}")
        try:
            items += steamos_items(fetch_json(STEAM_NEWS), CHANNELS.get(channel, ("stable",)), installed)
        except Exception as e:  # noqa: BLE001
            errors.append(f"SteamOS news: {e}")
        if info["board"]:
            try:
                items += bios_items(fetch_json(ASUS_BIOS.format(board=info["board"])), info["bios"])
            except Exception as e:  # noqa: BLE001
                errors.append(f"ASUS: {e}")
        return items, errors

    async def mark_seen(self) -> None:
        self.update_cfg({"seen": sorted(set(self.cfg.get("seen") or []) | {it["id"] for it in self.cfg.get("items") or []})})

    async def download_bios(self) -> Dict[str, Any]:
        """The EZ Flash file into ~/Downloads, checked against ASUS' SHA-256 and unpacked."""
        item = next((it for it in self.cfg.get("items") or [] if it["kind"] == "bios"), None)
        if not item or not item.get("url"):
            raise RuntimeError("no BIOS file known; refresh the news first")
        return await asyncio.to_thread(self._download, item)

    def _download(self, item: Dict[str, Any]) -> Dict[str, Any]:
        dest_dir = os.path.join(paths.HOME, "Downloads", f"BIOS-{device.board()}-{item['version']}")
        steam.mkdir_user(dest_dir)
        archive = os.path.join(dest_dir, os.path.basename(item["url"]))
        r = run(["curl", "-fsSL", "--max-time", "600", "-A", USER_AGENT, "-o", archive, item["url"]], timeout=620,
                as_user=True)
        if not r.ok:
            raise RuntimeError(f"download failed (rc={r.rc}): {r.err.strip()[:160]}")
        h = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if item.get("sha256") and h.hexdigest() != item["sha256"]:
            os.remove(archive)
            raise RuntimeError("checksum mismatch; the file was deleted")
        files = []
        if archive.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if name.endswith("/") or ".." in name:
                        continue
                    target = os.path.join(dest_dir, os.path.basename(name))
                    with z.open(name) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    steam.chown_user(target)
                    files.append(os.path.basename(name))
        logger.info("[news] BIOS %s downloaded to %s", item["version"], dest_dir)
        return {"dir": dest_dir, "files": files}
