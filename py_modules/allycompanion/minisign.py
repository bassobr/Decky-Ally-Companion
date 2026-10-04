"""minisign-compatible signing and verification (https://jedisct1.github.io/minisign/).

Public key file: comment line + base64("Ed" || key_id[8] || pk[32]).
Signature file: comment line, base64(alg[2] || key_id[8] || sig[64]),
"trusted comment: ..." line, base64(global_sig[64]). alg "ED" signs
BLAKE2b-512(file), "Ed" signs the raw file; global_sig covers sig || comment.

CLI: python3 -m allycompanion.minisign keygen|sign|verify
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
from typing import Dict, Optional, Tuple

from . import ed25519

UNTRUSTED_PREFIX = "untrusted comment: "
TRUSTED_PREFIX = "trusted comment: "


def _b64(line: str) -> bytes:
    try:
        return base64.b64decode(line.strip(), validate=True)
    except Exception as e:
        raise ValueError(f"invalid base64 in minisign data: {e}")


def _prehash(content: bytes) -> bytes:
    return hashlib.blake2b(content, digest_size=64).digest()


def parse_public_key(text: str) -> Tuple[bytes, bytes]:
    """Returns (key_id, public_key)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    payload = next((ln for ln in lines if not ln.startswith(UNTRUSTED_PREFIX)), None)
    if payload is None:
        raise ValueError("public key file has no key line")
    blob = _b64(payload)
    if len(blob) != 42 or blob[:2] != b"Ed":
        raise ValueError("not a minisign Ed25519 public key")
    return blob[2:10], blob[10:42]


def parse_signature(text: str) -> Dict[str, object]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        raise ValueError("signature file must have four lines")
    if not lines[0].startswith(UNTRUSTED_PREFIX) or not lines[2].startswith(TRUSTED_PREFIX):
        raise ValueError("signature file comments malformed")
    blob = _b64(lines[1])
    if len(blob) != 74 or blob[:2] not in (b"ED", b"Ed"):
        raise ValueError("not a minisign Ed25519 signature")
    glob_sig = _b64(lines[3])
    if len(glob_sig) != 64:
        raise ValueError("global signature must be 64 bytes")
    return {"alg": blob[:2], "key_id": blob[2:10], "signature": blob[10:74],
            "trusted_comment": lines[2][len(TRUSTED_PREFIX):], "global_signature": glob_sig}


def verify_bytes(content: bytes, sig_text: str, pubkey_text: str) -> Tuple[bool, str]:
    try:
        key_id, pk = parse_public_key(pubkey_text)
        sig = parse_signature(sig_text)
    except ValueError as e:
        return False, str(e)
    if sig["key_id"] != key_id:
        return False, "signature was made with a different key (key id mismatch)"
    msg = _prehash(content) if sig["alg"] == b"ED" else content
    if not ed25519.verify(pk, msg, sig["signature"]):  # type: ignore[arg-type]
        return False, "file signature invalid"
    tc = str(sig["trusted_comment"]).encode("utf-8")
    if not ed25519.verify(pk, sig["signature"] + tc, sig["global_signature"]):  # type: ignore[operator]
        return False, "trusted comment signature invalid"
    return True, f"valid signature, trusted comment: {sig['trusted_comment']}"


def verify_file(file_path: str, sig_text: str, pubkey_text: str) -> Tuple[bool, str]:
    with open(file_path, "rb") as f:
        return verify_bytes(f.read(), sig_text, pubkey_text)


def public_key_text(key_id: bytes, pk: bytes, comment: str) -> str:
    return f"{UNTRUSTED_PREFIX}{comment}\n" + base64.b64encode(b"Ed" + key_id + pk).decode() + "\n"


def generate_keypair(comment: Optional[str] = None) -> Tuple[bytes, str]:
    """Returns (seed, public_key_file_text). Keep the seed secret."""
    seed = os.urandom(32)
    key_id = os.urandom(8)
    pk = ed25519.secret_to_public(seed)
    comment = comment or f"minisign public key {key_id.hex().upper()}"
    return seed, public_key_text(key_id, pk, comment)


def sign_bytes(content: bytes, seed: bytes, pubkey_text: str, trusted_comment: str,
               untrusted_comment: str = "signature from Ally Companion CI") -> str:
    key_id, pk = parse_public_key(pubkey_text)
    if ed25519.secret_to_public(seed) != pk:
        raise ValueError("seed does not match the public key file")
    sig = ed25519.sign(seed, _prehash(content))
    glob_sig = ed25519.sign(seed, sig + trusted_comment.encode("utf-8"))
    return (f"{UNTRUSTED_PREFIX}{untrusted_comment}\n" + base64.b64encode(b"ED" + key_id + sig).decode() + "\n"
            + f"{TRUSTED_PREFIX}{trusted_comment}\n" + base64.b64encode(glob_sig).decode() + "\n")


def sign_file(file_path: str, seed: bytes, pubkey_text: str, trusted_comment: str) -> str:
    with open(file_path, "rb") as f:
        return sign_bytes(f.read(), seed, pubkey_text, trusted_comment)


def _seed_from_env(var: str) -> bytes:
    raw = os.environ.get(var, "").strip()
    if not raw:
        raise SystemExit(f"{var} is not set")
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        seed = base64.b64decode(raw)
    if len(seed) != 32:
        raise SystemExit("seed must be 32 bytes (hex or base64)")
    return seed


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="allycompanion.minisign")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen", help="write a new public key file and print the seed (hex) to stdout")
    g.add_argument("--pub", required=True)
    g.add_argument("--comment")
    s = sub.add_parser("sign", help="sign FILE with the seed from $MINISIGN_SEED, writing FILE.minisig")
    s.add_argument("file")
    s.add_argument("--pub", required=True)
    s.add_argument("--trusted-comment", required=True)
    s.add_argument("--seed-env", default="MINISIGN_SEED")
    v = sub.add_parser("verify", help="verify FILE against SIG with PUB")
    v.add_argument("file")
    v.add_argument("sig")
    v.add_argument("pub")
    a = ap.parse_args(argv)
    if a.cmd == "keygen":
        seed, pub_text = generate_keypair(a.comment)
        with open(a.pub, "w", encoding="utf-8") as f:
            f.write(pub_text)
        print(seed.hex())
        return 0
    if a.cmd == "sign":
        with open(a.pub, "r", encoding="utf-8") as f:
            pub_text = f.read()
        sig_text = sign_file(a.file, _seed_from_env(a.seed_env), pub_text, a.trusted_comment)
        with open(a.file + ".minisig", "w", encoding="utf-8") as f:
            f.write(sig_text)
        print(f"wrote {a.file}.minisig")
        return 0
    with open(a.sig, "r", encoding="utf-8") as f:
        sig_text = f.read()
    with open(a.pub, "r", encoding="utf-8") as f:
        pub_text = f.read()
    ok, detail = verify_file(a.file, sig_text, pub_text)
    print(("OK: " if ok else "FAIL: ") + detail)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
