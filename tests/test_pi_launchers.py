from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


@pytest.mark.skipif(
    BASH is None or os.name == "nt",
    reason="Raspberry Pi launcher integration tests require a native Unix bash",
)
def test_desktop_launcher_installer_creates_all_module_shortcuts(tmp_path: Path) -> None:
    desktop_dir = tmp_path / "Desktop"
    applications_dir = tmp_path / "applications"
    env = os.environ.copy()
    env.update(
        {
            "HOME": tmp_path.as_posix(),
            "HOMEBASE_DESKTOP_DIR": desktop_dir.as_posix(),
            "HOMEBASE_APPLICATIONS_DIR": applications_dir.as_posix(),
        }
    )

    command = [BASH, str(ROOT / "scripts" / "install_desktop_launcher.sh")]
    first = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    second = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    expected_actions = {
        "Homebase Camera.desktop": "start",
        "Homebase Zone Editor.desktop": "zones",
        "Homebase Health.desktop": "health --pause",
        "Homebase Empty Baseline.desktop": "baseline --pause",
        "Homebase Logs.desktop": "logs",
        "Homebase Restart.desktop": "restart --pause",
        "Homebase Stop.desktop": "stop --pause",
        "Homebase Menu.desktop": "menu",
    }

    assert {path.name for path in desktop_dir.glob("*.desktop")} == set(expected_actions)
    assert {path.name for path in applications_dir.glob("*.desktop")} == set(expected_actions)

    for file_name, action in expected_actions.items():
        contents = (desktop_dir / file_name).read_text(encoding="utf-8")
        assert "Type=Application" in contents
        assert "Name[ko]=" in contents
        assert f'Exec=/bin/bash "{ROOT.as_posix()}/scripts/pi_control.sh" {action}' in contents
        assert f"Path={ROOT.as_posix()}" in contents
        assert "Terminal=true" in contents
        assert "Categories=Utility;" in contents
        assert (applications_dir / file_name).read_text(encoding="utf-8") == contents


@pytest.mark.skipif(
    BASH is None or os.name == "nt",
    reason="Raspberry Pi launcher integration tests require a native Unix bash",
)
def test_homebase_help_does_not_start_services() -> None:
    result = subprocess.run(
        [BASH, str(ROOT / "homebase"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "./homebase [명령]" in result.stdout
    assert "baseline" in result.stdout
