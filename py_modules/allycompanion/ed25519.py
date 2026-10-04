"""Ed25519 (RFC 8032) in pure Python with extended coordinates.

Decky's bundled Python has no Ed25519 primitive. Used to verify release
signatures on the device and to sign in CI. Not constant-time; do not use it
with long-lived secrets on user devices. Tested against the RFC 8032 vectors.
"""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
Point = Tuple[int, int, int, int]  # extended coordinates (X, Y, Z, T)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


def _recover_x(y: int, sign: int) -> Optional[int]:
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * pow(2, (P - 1) // 4, P) % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = (4 * _inv(5)) % P
_GX = _recover_x(_GY, 0)
assert _GX is not None
G: Point = (_GX, _GY, 1, _GX * _GY % P)
IDENTITY: Point = (0, 1, 1, 0)


def point_add(p1: Point, p2: Point) -> Point:
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def point_mul(s: int, p: Point) -> Point:
    q = IDENTITY
    while s > 0:
        if s & 1:
            q = point_add(q, p)
        p = point_add(p, p)
        s >>= 1
    return q


def point_equal(p1: Point, p2: Point) -> bool:
    return (p1[0] * p2[2] - p2[0] * p1[2]) % P == 0 and (p1[1] * p2[2] - p2[1] * p1[2]) % P == 0


def point_compress(p: Point) -> bytes:
    zinv = _inv(p[2])
    x = p[0] * zinv % P
    y = p[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def point_decompress(s: bytes) -> Optional[Point]:
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _secret_expand(secret: bytes) -> Tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("Ed25519 secret key must be 32 bytes")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def secret_to_public(secret: bytes) -> bytes:
    a, _ = _secret_expand(secret)
    return point_compress(point_mul(a, G))


def sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _secret_expand(secret)
    pub = point_compress(point_mul(a, G))
    r = int.from_bytes(_sha512(prefix + msg), "little") % Q
    rs = point_compress(point_mul(r, G))
    h = int.from_bytes(_sha512(rs + pub + msg), "little") % Q
    s = (r + h * a) % Q
    return rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = point_decompress(public)
    if a is None:
        return False
    rs = signature[:32]
    r = point_decompress(rs)
    if r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= Q:
        return False
    h = int.from_bytes(_sha512(rs + public + msg), "little") % Q
    return point_equal(point_mul(s, G), point_add(r, point_mul(h, a)))
