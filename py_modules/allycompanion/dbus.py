"""D-Bus through busctl's JSON output.

Decky's bundled Python has no xml.etree, which the pure-Python D-Bus libraries need for
introspection, so the backend talks to InputPlumber and steamos-manager through busctl.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from .util import run


class DBusError(RuntimeError):
    pass


def _busctl(args: List[str], user_bus: bool, timeout: float) -> Any:
    cmd = ["busctl", "--user" if user_bus else "--system", "--json=short", *args]
    r = run(cmd, timeout=timeout, as_user=user_bus)
    if not r.ok:
        raise DBusError((r.err or r.out).strip()[:300] or f"busctl rc={r.rc}")
    out = r.out.strip()
    return json.loads(out) if out else None


def get_property(service: str, path: str, interface: str, prop: str, user_bus: bool = False,
                 timeout: float = 5) -> Any:
    reply = _busctl(["get-property", service, path, interface, prop], user_bus, timeout)
    return unwrap(reply)


def call(service: str, path: str, interface: str, method: str, signature: str = "", *args: Any,
         user_bus: bool = False, timeout: float = 10) -> Any:
    argv = ["call", service, path, interface, method]
    if signature:
        argv += [signature, *(_arg(a) for a in args)]
    reply = _busctl(argv, user_bus, timeout)
    data = unwrap(reply)
    return data[0] if isinstance(data, list) and len(data) == 1 else data


def try_get_property(*args: Any, **kwargs: Any) -> Optional[Any]:
    try:
        return get_property(*args, **kwargs)
    except (DBusError, ValueError):
        return None


def unwrap(reply: Any) -> Any:
    """busctl wraps values as {"type": sig, "data": value}; variants nest the same way."""
    if isinstance(reply, dict) and set(reply) == {"type", "data"}:
        return unwrap(reply["data"])
    if isinstance(reply, list):
        return [unwrap(x) for x in reply]
    if isinstance(reply, dict):
        return {k: unwrap(v) for k, v in reply.items()}
    return reply


def _arg(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
