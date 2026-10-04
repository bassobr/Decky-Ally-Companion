import os

import pytest

from conftest import FIXTURES
from allycompanion import minisign


def _read(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


def test_verifies_real_reference_release_signature():
    ok, detail = minisign.verify_file(os.path.join(FIXTURES, "ref_SHA256SUMS"), _read("ref_SHA256SUMS.minisig"),
                                      _read("ref_minisign.pub"))
    assert ok, detail
    assert "v0.15.1" in detail


def test_rejects_modified_content_and_comment():
    content = _read("ref_SHA256SUMS").encode()
    sig = _read("ref_SHA256SUMS.minisig")
    pub = _read("ref_minisign.pub")
    assert minisign.verify_bytes(content, sig, pub)[0]
    assert not minisign.verify_bytes(content.replace(b"aa9d", b"aa9e"), sig, pub)[0]
    bad_comment = sig.replace("trusted comment: wifi-optimizer-streaming v0.15.1", "trusted comment: evil v9")
    assert not minisign.verify_bytes(content, bad_comment, pub)[0]


def test_roundtrip_keygen_sign_verify(tmp_path):
    seed, pub = minisign.generate_keypair("test key")
    data = b"hello release\n"
    sig = minisign.sign_bytes(data, seed, pub, "ally-companion v9.9.9")
    ok, detail = minisign.verify_bytes(data, sig, pub)
    assert ok and "v9.9.9" in detail
    other_seed, other_pub = minisign.generate_keypair()
    assert not minisign.verify_bytes(data, sig, other_pub)[0]
    with pytest.raises(ValueError):
        minisign.sign_bytes(data, other_seed, pub, "mismatch")


def test_parse_errors():
    with pytest.raises(ValueError):
        minisign.parse_public_key("untrusted comment: x\nnot base64!!\n")
    with pytest.raises(ValueError):
        minisign.parse_signature("only\ntwo\n")
