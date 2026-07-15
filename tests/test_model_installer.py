from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.install_yolo_model import install_model, sha256


def test_installer_downloads_and_verifies_local_source(tmp_path: Path) -> None:
    content = b"test-model-content"
    source = tmp_path / "source.onnx"
    source.write_bytes(content)
    target = tmp_path / "models" / "model.onnx"
    expected = hashlib.sha256(content).hexdigest()

    assert install_model(target, url=source.as_uri(), expected_sha256=expected) == target.resolve()
    assert sha256(target) == expected


def test_installer_rejects_invalid_checksum_without_replacing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.onnx"
    source.write_bytes(b"bad")
    target = tmp_path / "model.onnx"
    target.write_bytes(b"existing")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        install_model(target, url=source.as_uri(), expected_sha256="0" * 64, force=True)

    assert target.read_bytes() == b"existing"
