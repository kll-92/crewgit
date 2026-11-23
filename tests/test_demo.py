from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from crewgit.demo import run_demo


def test_demo_is_green_and_has_one_blocked_task(tmp_path: Path) -> None:
    result = run_demo(directory=tmp_path / "demo", force=True)
    board = result["board"]
    assert board["counts"]["done"] == 3
    assert board["counts"]["blocked"] == 1
    assert result["reproduced"] is True

    demo_dir = Path(result["path"])
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_cart.py"],
        cwd=str(demo_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    cart = (demo_dir / "cart.py").read_text(encoding="utf-8")
    assert "round(total, 2)" in cart
    assert "round(total, 1)" not in cart


def test_demo_refuses_to_overwrite(tmp_path: Path) -> None:
    run_demo(directory=tmp_path / "demo", force=True)
    try:
        run_demo(directory=tmp_path / "demo", force=False)
    except Exception as exc:  # noqa: BLE001 - assert the public behaviour
        assert "already exists" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("demo should refuse to overwrite")
