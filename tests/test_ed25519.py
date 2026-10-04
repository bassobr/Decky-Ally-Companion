import json
import os

from conftest import FIXTURES
from allycompanion import ed25519


def _vectors():
    with open(os.path.join(FIXTURES, "ed25519_vectors.json")) as f:
        return json.load(f)


def test_rfc8032_vectors_sign_and_verify():
    vecs = _vectors()
    assert len(vecs) >= 5
    for v in vecs:
        sk, pk, msg, sig = (bytes.fromhex(v[k]) for k in ("sk", "pk", "msg", "sig"))
        assert ed25519.secret_to_public(sk) == pk, v["name"]
        assert ed25519.sign(sk, msg) == sig, v["name"]
        assert ed25519.verify(pk, msg, sig), v["name"]


def test_tampering_is_detected():
    v = _vectors()[1]
    pk, msg, sig = bytes.fromhex(v["pk"]), bytes.fromhex(v["msg"]), bytes.fromhex(v["sig"])
    assert not ed25519.verify(pk, msg + b"x", sig)
    bad = bytearray(sig)
    bad[0] ^= 1
    assert not ed25519.verify(pk, msg, bytes(bad))
    assert not ed25519.verify(pk[:-1], msg, sig)
    assert not ed25519.verify(pk, msg, sig[:-1])


def test_rejects_non_canonical_scalar():
    v = _vectors()[0]
    pk, msg, sig = bytes.fromhex(v["pk"]), bytes.fromhex(v["msg"]), bytes.fromhex(v["sig"])
    s = int.from_bytes(sig[32:], "little") + ed25519.Q
    assert not ed25519.verify(pk, msg, sig[:32] + s.to_bytes(32, "little"))
