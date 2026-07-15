from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen


MODEL_URL = "https://raw.githubusercontent.com/yoobright/yolo-onnx/master/yolov8n.onnx"
MODEL_SHA256 = "adda0231eeb47d888199927f6caf7b46dacaf91bad5bfeea63fde3ebd5d7846f"
MODEL_PATH = Path("data/models/yolov8n.onnx")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_model(target: Path, *, url: str = MODEL_URL, expected_sha256: str = MODEL_SHA256, force: bool = False) -> Path:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256(target) == expected_sha256 and not force:
        return target

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".download", delete=False) as output:
            temp_path = Path(output.name)
            with urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, output)
        actual = sha256(temp_path)
        if actual != expected_sha256:
            raise RuntimeError(f"Model checksum mismatch: expected {expected_sha256}, got {actual}")
        temp_path.replace(target)
        return target
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify the pinned Homebase person detector model.")
    parser.add_argument("--target", type=Path, default=MODEL_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    installed = install_model(args.target, force=args.force)
    print(f"YOLO model ready: {installed}")
    print(f"SHA-256: {sha256(installed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
