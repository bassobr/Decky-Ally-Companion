"""News: SteamOS releases for the installed channel, BIOS updates for the board, known issues.

Sources, fetched every six hours (or on demand); a source that does not answer keeps its last items
and is asked again after 30 minutes, also after a wake-up without network:
- SteamOS release notes from the Steam news feed of the Steam Deck app (1675200), filtered to the
  channel `steamos-select-branch -c` reports, with the bullet points that mention the Ally.
- ASUS' support API for the board: BIOS for EZ Flash and firmware packages. The EZ Flash file can
  be downloaded to ~/Downloads; only when ASUS publishes its SHA-256, which the file must match.
- known-issues.json in this repository: problems between SteamOS versions and this plugin.

Items newer than what is installed count as unseen until the News page marks them seen.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import device, paths, safefs, userfs
from ..constants import USER_AGENT
from ..log import logger
from ..module import Module, cancel_task
from ..util import run

STEAM_NEWS = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=1675200&count=60&maxlength=0"
              "&feeds=steam_community_announcements")
ASUS_BIOS = "https://www.asus.com/support/webapi/ProductV2/GetPDBIOS?website=global&model={board}&cpu={board}"
ASUS_CDN = "https://dlcdnets.asus.com"
KNOWN_ISSUES = "https://raw.githubusercontent.com/bassobr/Decky-Ally-Companion/main/news/known-issues.json"
REFRESH_S = 6 * 3600
RETRY_S = 30 * 60
RESUME_DELAY_S = 30  # Wi-Fi is not back the moment the device wakes
KEYWORDS = re.compile(r"\b(rog|ally|asus|inputplumber|xbox)\b", re.I)
# steamos-select-branch -c -> which release kinds that channel receives
CHANNELS = {"rel": ("stable",), "rc": ("stable",), "beta": ("stable", "beta"), "bc": ("stable", "beta"),
            "preview": ("stable", "beta", "preview"), "pc": ("stable", "beta", "preview"),
            "main": ("stable", "beta", "preview")}
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]{1,32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
CHANNEL = re.compile(r"[a-z0-9_-]{1,16}")
BRANCH_TOOLS = ("holo-select-branch", "steamos-select-branch")  # SteamOS 3.9 renames steamos-* to holo-*
KINDS = ("steamos", "bios", "firmware", "issue")
SOURCES = {"issue": ("issue",), "steamos": ("steamos",), "asus": ("bios", "firmware")}  # in display order
MAX_BIOS = 256 << 20
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
    for tool in BRANCH_TOOLS:
        r = run([tool, "-c"], timeout=10)
        channel = r.out.strip()
        if r.ok and CHANNEL.fullmatch(channel):
            return channel
    return "rel"


def clean_item(it: Any) -> Optional[Dict[str, Any]]:
    """A stored news item (settings.json is the user's): known kinds, strings and plain URLs only."""
    if not isinstance(it, dict) or not isinstance(it.get("id"), str) or it.get("kind") not in KINDS:
        return None
    out: Dict[str, Any] = {"id": it["id"][:200], "kind": it["kind"], "newer": bool(it.get("newer"))}
    for k in ("title", "version", "channel", "body", "size", "sha256"):
        if isinstance(it.get(k), str):
            out[k] = it[k][:2000]
    url = it.get("url")
    out["url"] = url if isinstance(url, str) and url.startswith("https://") else None
    if isinstance(it.get("date"), (int, str)) and not isinstance(it.get("date"), bool):
        out["date"] = it["date"]
    if isinstance(it.get("highlights"), list):
        out["highlights"] = [h[:400] for h in it["highlights"] if isinstance(h, str)][:10]
    return out


def _strings(v: Any, limit: int) -> List[str]:
    return [x for x in v if isinstance(x, str)][-limit:] if isinstance(v, list) else []


class News(Module):
    id = "news"
    title = "News"
    defaults = {"items": [], "fetchedAt": 0, "lastAttempt": 0, "error": None, "seen": [], "notified": [], "channel": None}

    def __init__(self) -> None:
        super().__init__()
        self._task: Optional[asyncio.Task] = None  # a refresh
        self._timer: Optional[asyncio.Task] = None  # the periodic check

    def normalize(self, cfg: Dict[str, Any]) -> None:
        cfg["items"] = [c for c in (clean_item(it) for it in (cfg.get("items") or [])) if c]
        cfg["seen"] = _strings(cfg.get("seen"), 500)
        cfg["notified"] = _strings(cfg.get("notified"), 200)
        ch = cfg.get("channel")
        cfg["channel"] = ch if isinstance(ch, str) and CHANNEL.fullmatch(ch) else None
        if not isinstance(cfg.get("error"), str):
            cfg["error"] = None

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

    def due(self) -> bool:
        now = time.time()
        return now - (self.cfg.get("fetchedAt") or 0) >= REFRESH_S and now - (self.cfg.get("lastAttempt") or 0) >= RETRY_S

    def _refresh_soon(self, delay: float = 0.0) -> None:
        async def later() -> None:
            await asyncio.sleep(delay)
            if self.due():
                await self.refresh()

        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(later())

    async def _periodic(self) -> None:
        while True:
            await asyncio.sleep(RETRY_S)
            self._refresh_soon()

    async def start(self) -> None:
        self._refresh_soon()
        if self._timer is None or self._timer.done():
            self._timer = asyncio.get_running_loop().create_task(self._periodic())

    async def stop(self) -> None:
        await cancel_task(self._timer)
        await cancel_task(self._task)

    async def on_resume(self, slept_s: float) -> None:
        self._refresh_soon(RESUME_DELAY_S)

    async def refresh(self) -> Dict[str, Any]:
        async with self._lock:  # the start-up refresh and the button may meet
            self.update_cfg({"lastAttempt": int(time.time())})
            found, channel, errors = await asyncio.to_thread(self._collect)
            prev = self.cfg.get("items") or []
            items: List[Dict[str, Any]] = []
            for source, kinds in SOURCES.items():  # a source that failed keeps its items
                items += found[source] if source in found else [it for it in prev if it.get("kind") in kinds]
            values: Dict[str, Any] = {"items": items, "channel": channel, "error": "; ".join(errors) or None}
            if found:  # nothing answered: fetchedAt stays, so the 30-minute retry applies
                values["fetchedAt"] = int(time.time())
            self.update_cfg(values)
        if errors:
            logger.warning("[news] %s", "; ".join(errors))
        await self._announce()
        await self.notify()
        return {"unseen": len(self.unseen())}

    async def _announce(self) -> None:
        """One toast per unseen item, once."""
        notified = set(self.cfg.get("notified") or [])
        fresh = [it for it in self.cfg.get("items") or [] if it["id"] in self.unseen() and it["id"] not in notified]
        if not fresh:
            return
        self.update_cfg({"notified": sorted(notified | {it["id"] for it in fresh})[-200:]})
        if self.ctx:
            await self.ctx.emit("news_new", [{"id": it["id"], "kind": it["kind"], "title": it.get("title") or "",
                                              "version": it.get("version")} for it in fresh])

    def _collect(self) -> Tuple[Dict[str, List[Dict[str, Any]]], str, List[str]]:
        """Runs in a worker thread: items per source that answered, the channel, the errors; the
        settings are changed on the event loop."""
        info = device.info()
        installed = version_tuple(info["osVersion"])
        channel = steamos_channel()
        found: Dict[str, List[Dict[str, Any]]] = {}
        errors = []
        try:
            found["issue"] = issue_items(fetch_json(KNOWN_ISSUES), installed, info["board"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"known issues: {e}")
        try:
            found["steamos"] = steamos_items(fetch_json(STEAM_NEWS), CHANNELS.get(channel, ("stable",)), installed)
        except Exception as e:  # noqa: BLE001
            errors.append(f"SteamOS news: {e}")
        if info["board"]:
            try:
                found["asus"] = bios_items(fetch_json(ASUS_BIOS.format(board=info["board"])), info["bios"])
            except Exception as e:  # noqa: BLE001
                errors.append(f"ASUS: {e}")
        clean = {s: [c for c in (clean_item(it) for it in items) if c] for s, items in found.items()}
        return clean, channel, errors

    async def mark_seen(self) -> None:
        self.update_cfg({"seen": sorted(set(self.cfg.get("seen") or []) | {it["id"] for it in self.cfg.get("items") or []})})

    async def download_bios(self) -> Dict[str, Any]:
        """The EZ Flash file into ~/Downloads, checked against ASUS' SHA-256 and unpacked."""
        item = next((it for it in self.cfg.get("items") or [] if it["kind"] == "bios"), None)
        if not item or not item.get("url"):
            raise RuntimeError("no BIOS file known; refresh the news first")
        return await asyncio.to_thread(self._download, item)

    def _download(self, item: Dict[str, Any]) -> Dict[str, Any]:
        # The item comes from settings.json, which sits in a directory the user owns: check what
        # goes into paths and URLs, and do every file operation as the user.
        version, url = str(item.get("version", "")), str(item.get("url", ""))
        expected = str(item.get("sha256") or "").lower()
        if not SAFE_NAME.fullmatch(version) or not url.startswith(ASUS_CDN + "/") or ".." in url:
            raise RuntimeError("unexpected BIOS entry; refresh the news")
        if not SHA256.fullmatch(expected):
            raise RuntimeError("ASUS publishes no checksum for this file; download it from the ASUS website instead")
        dest_dir = os.path.join(paths.HOME, "Downloads", f"BIOS-{device.board()}-{version}")
        archive = os.path.join(dest_dir, os.path.basename(url))
        userfs.mkdir(dest_dir)
        r = run(["curl", "-fsSL", "--max-time", "600", "--max-filesize", str(MAX_BIOS), "-A", USER_AGENT, "-o", archive,
                 url], timeout=620, as_user=True)
        if not r.ok:
            raise RuntimeError(f"download failed (rc={r.rc}): {r.err.strip()[:160]}")
        if safefs.sha256(archive, MAX_BIOS) != expected:  # hashed as the user: ~/Downloads may be a link
            userfs.remove(archive)
            raise RuntimeError("checksum mismatch; the file was deleted")
        files = userfs.unzip(archive, dest_dir) if archive.endswith(".zip") else []
        logger.info("[news] BIOS %s downloaded to %s", version, dest_dir)
        return {"dir": dest_dir, "files": files}
