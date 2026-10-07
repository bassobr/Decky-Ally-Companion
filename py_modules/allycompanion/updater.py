"""Update check and release verification; installation is delegated to Decky Loader.

Decky removes the installed version before it checks the zip's hash, so a zip that fails the check
would leave no plugin behind (and the uninstall cleanup would run). The backend therefore downloads
and checks the zip itself and hands Decky a local file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from typing import Any, Dict, Optional, Tuple

from . import paths
from .constants import GITHUB_REPO, PLUGIN_NAME, RELEASE_ZIP_TEMPLATE, UPDATE_CHECK_INTERVAL_S, UPDATE_RETRY_S, USER_AGENT
from .log import logger
from .minisign import verify_bytes
from .util import run

STAGING = "/run/ally-companion-update"  # root only; cleared when the backend starts
MAX_ZIP = 128 << 20


def parse_version(v: str) -> Tuple[int, ...]:
    core = str(v).strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for piece in core.split("."):
        m = re.match(r"\d+", piece)
        parts.append(int(m.group(0)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest(repo: str = GITHUB_REPO) -> Optional[Dict[str, Any]]:
    """The latest release, or None while the repository has none."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    r = run(["curl", "-fsSL", "--max-time", "20", "-A", USER_AGENT, "-H", "Accept: application/vnd.github+json",
             "-H", "X-GitHub-Api-Version: 2022-11-28", url], timeout=30)
    if r.rc == 22 and "error: 404" in r.err:
        return None
    if not r.ok:
        raise RuntimeError(f"GitHub API request failed (rc={r.rc}): {r.err.strip()[:160]}")
    data = json.loads(r.out)
    tag = str(data.get("tag_name", ""))
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", []) or []}
    return {"tag": tag, "version": tag.lstrip("vV"), "assets": assets, "html_url": data.get("html_url"),
            "published_at": data.get("published_at"), "prerelease": bool(data.get("prerelease"))}


def check_due(state: Dict[str, Any], now: Optional[float] = None) -> bool:
    """The cache is older than the check interval and the last attempt older than the retry delay."""
    now = time.time() if now is None else now
    stale = not state.get("latest") or now - int(state.get("lastCheck") or 0) >= UPDATE_CHECK_INTERVAL_S
    return stale and now - int(state.get("lastAttempt") or 0) >= UPDATE_RETRY_S


def check(state: Dict[str, Any], current_version: str, force: bool = False, fetch: bool = True) -> Dict[str, Any]:
    """`state` is settings['update']; mutated in place. fetch=False only reads the cache."""
    now = int(time.time())
    fresh = state.get("latest") and now - int(state.get("lastCheck") or 0) < UPDATE_CHECK_INTERVAL_S
    if fetch and (force or not fresh):
        state["lastAttempt"] = now
        try:
            state["latest"] = fetch_latest()
            state["lastCheck"] = now
            state["error"] = None
        except Exception as e:
            logger.warning("update check failed: %s", e)
            state["error"] = str(e)
    latest = state.get("latest")
    result = {"currentVersion": current_version, "latestVersion": None, "updateAvailable": False,
              "releaseUrl": None, "checkedAt": state.get("lastCheck"), "error": state.get("error")}
    if latest:
        result["latestVersion"] = latest.get("version")
        result["releaseUrl"] = latest.get("html_url")
        result["updateAvailable"] = bool(latest.get("version")) and is_newer(latest["version"], current_version)
    return result


def parse_sums(text: str) -> Dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


def _fetch_text(url: str, timeout: int = 30) -> str:
    """Small release assets straight into memory: no files in the user-owned data directory."""
    r = run(["curl", "-fsSL", "--max-time", str(timeout), "-A", USER_AGENT, url], timeout=timeout + 5)
    if not r.ok:
        raise RuntimeError(f"download failed: {url.rsplit('/', 1)[-1]} (rc={r.rc})")
    return r.out


def verify_release(latest: Dict[str, Any], pubkey_path: str = paths.PUBKEY_FILE) -> Dict[str, Any]:
    """Verify SHA256SUMS.minisig with the pinned key and return artifact URL, name, version, sha256."""
    version = str(latest.get("version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?", version):
        raise RuntimeError(f"refusing unexpected version string {version!r}")
    assets = latest.get("assets") or {}
    zip_name = RELEASE_ZIP_TEMPLATE.format(version=version)
    zip_url = assets.get(zip_name)
    sums_url = assets.get("SHA256SUMS")
    sig_url = assets.get("SHA256SUMS.minisig")
    if not zip_url or not sums_url or not sig_url:
        raise RuntimeError("release is missing the zip, SHA256SUMS or SHA256SUMS.minisig asset")
    prefix = f"https://github.com/{GITHUB_REPO}/releases/download/v{version}/"
    if not all(str(u).startswith(prefix) for u in (zip_url, sums_url, sig_url)):
        raise RuntimeError("release assets come from an unexpected place")
    sums_text = _fetch_text(sums_url)
    sig_text = _fetch_text(sig_url)
    with open(pubkey_path, "r", encoding="utf-8") as f:
        pub_text = f.read()
    ok, detail = verify_bytes(sums_text.encode("utf-8"), sig_text, pub_text)
    if not ok:
        raise RuntimeError(f"signature check failed: {detail}")
    sums = parse_sums(sums_text)
    sha = sums.get(zip_name)
    if not sha:
        raise RuntimeError(f"SHA256SUMS has no entry for {zip_name}")
    return {"artifact": zip_url, "name": PLUGIN_NAME, "version": version, "hash": sha, "detail": detail}


def download_verified(release: Dict[str, Any], staging: str = STAGING) -> Dict[str, Any]:
    """Download the verified release's zip into a root-only directory, check it against the signed
    SHA-256 and return the release with a file:// artifact for Decky's installer."""
    clear_staging(staging)
    os.makedirs(staging, mode=0o700)
    dest = os.path.join(staging, RELEASE_ZIP_TEMPLATE.format(version=release["version"]))
    r = run(["curl", "-fsSL", "--max-time", "300", "--max-filesize", str(MAX_ZIP), "-A", USER_AGENT, "-o", dest,
             release["artifact"]], timeout=320)
    if not r.ok:
        raise RuntimeError(f"download failed (rc={r.rc}): {r.err.strip()[:160]}")
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != release["hash"]:
        clear_staging(staging)
        raise RuntimeError("the downloaded zip does not match the signed checksum")
    return dict(release, artifact="file://" + dest)


def clear_staging(staging: str = STAGING) -> None:
    shutil.rmtree(staging, ignore_errors=True)
