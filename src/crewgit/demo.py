"""Deterministic offline demo: a real repo, three agents, one blocked violation, one merge."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import Paths, write_default_config
from .contracts import write_task_file
from .gitops import Git
from .models import CrewGitError, GateError, Run, iso_now
from .runner import Runner

console = Console()

DEMO_README = """# demo-shop

A deliberately tiny cart library used by the CrewGit demo.

    python -m unittest -q test_cart

The rounding bug (`round(total, 1)`) is fixed by the coder agent during the demo.
"""

DEMO_CART = '''"""Tiny shopping cart used by the CrewGit demo."""

TAX_RATE = 0.08


def subtotal(items):
    return sum(price * quantity for price, quantity in items)


def cart_total(items, discount=0.0):
    total = subtotal(items) * (1 - discount)
    total = total * (1 + TAX_RATE)
    return round(total, 1)  # bug: cents are lost
'''

DEMO_TEST = '''import unittest

from cart import cart_total


class CartTotalTest(unittest.TestCase):
    def test_cart_total_keeps_cents(self):
        # 19.99 * 3 = 59.97, 10% off = 53.973, +8% tax = 58.29084 -> 58.29
        self.assertEqual(cart_total([(19.99, 3)], discount=0.10), 58.29)

    def test_cart_total_simple(self):
        self.assertEqual(cart_total([(10.00, 1)]), 10.80)

    def test_cart_total_empty(self):
        self.assertEqual(cart_total([]), 0.0)


if __name__ == "__main__":
    unittest.main()
'''

PLAN_TASK = {
    "id": "T-100",
    "title": "Plan the discount rounding fix",
    "agent": "planner",
    "scope": ["docs/plan-T-100.md"],
    "acceptance": {"tests": None},
    "budget": {"max_files": 1, "max_lines": 60},
    "context": "The cart total loses cents (round to 1 decimal). Plan a minimal fix and the test to prove it.",
}

FIX_TASK = {
    "id": "T-101",
    "title": "Fix discount rounding to cents",
    "agent": "coder",
    "depends_on": ["T-100"],
    "scope": ["cart.py", "test_cart.py"],
    "acceptance": {"tests": "__UNITTEST__"},
    "budget": {"max_files": 2, "max_lines": 60},
    "context": "cart_total rounds to one decimal, so 58.29084 becomes 58.3 instead of 58.29. Fix the rounding and keep the tests meaningful.",
    "mock_actions": [
        {
            "op": "patch",
            "path": "cart.py",
            "find": "round(total, 1)  # bug: cents are lost",
            "replace": "round(total, 2)  # keep cents (T-101)",
        }
    ],
}

ROGUE_TASK = {
    "id": "T-102",
    "title": "Add changelog (and a sneaky version bump)",
    "agent": "coder",
    "depends_on": ["T-101"],
    "scope": ["CHANGELOG.md"],
    "acceptance": {"tests": None},
    "budget": {"max_files": 2, "max_lines": 40},
    "context": "Write a changelog entry for the rounding fix. Do not touch packaging files.",
    "mock_actions": [
        {
            "op": "write",
            "path": "CHANGELOG.md",
            "content": "# Changelog\n\n## 0.1.1\n- Fix discount rounding in `cart_total` (T-101)\n",
        },
        {
            "op": "write",
            "path": "pyproject.toml",
            "content": '[project]\nname = "demo-shop"\nversion = "0.1.1"\n',
        },
    ],
}

FIXED_TASK = {
    "id": "T-102R",
    "title": "Add changelog entry (corrected contract)",
    "agent": "coder",
    "depends_on": ["T-101"],
    "scope": ["CHANGELOG.md"],
    "acceptance": {"tests": None},
    "budget": {"max_files": 1, "max_lines": 20},
    "context": "Same intent as T-102, but the contract now forbids packaging files explicitly.",
    "forbid": ["pyproject.toml", "setup.py"],
    "mock_actions": [
        {
            "op": "write",
            "path": "CHANGELOG.md",
            "content": "# Changelog\n\n## 0.1.1\n- Fix discount rounding in `cart_total` (T-101)\n",
        }
    ],
}


def _git_identity(git: Git) -> None:
    proc = subprocess.run(["git", "config", "user.email"], cwd=str(git.root), capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        subprocess.run(["git", "config", "user.name", "CrewGit Demo"], cwd=str(git.root), check=True)
        subprocess.run(["git", "config", "user.email", "demo@crewgit.local"], cwd=str(git.root), check=True)


def _commit(git: Git, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=str(git.root), check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(git.root), check=True, capture_output=True)
    return git.head()


def _gate_chips(run: Run) -> str:
    colors = {"pass": "green", "fail": "red", "skip": "dim", "error": "yellow"}
    return "  ".join(
        f"[{colors.get(gate.status, 'white')}]{gate.name}:{gate.status}[/]" for gate in run.gates
    )


def _print_run(run: Run) -> None:
    console.print(
        Panel(
            f"[bold]{run.task_id}[/bold] {run.title}\n"
            f"agent [bold]{run.agent}[/bold] ({run.adapter})   "
            f"diff {run.diff_stat.get('files', 0)}f "
            f"[green]+{run.diff_stat.get('insertions', 0)}[/green] "
            f"[red]-{run.diff_stat.get('deletions', 0)}[/red]\n"
            f"{_gate_chips(run) or '[dim]no gates[/dim]'}",
            title=f"{run.run_id} · {run.status}",
            border_style="green" if run.status == "passed" else "red",
        )
    )
    if run.error and run.status != "passed":
        console.print(f"[red]{run.error.splitlines()[0][:240]}[/red]")


def _task_yaml(task: dict[str, Any]) -> dict[str, Any]:
    data = dict(task)
    if data.get("acceptance", {}).get("tests") == "__UNITTEST__":
        data["acceptance"] = {"tests": f"{sys.executable} -m unittest -q test_cart"}
    return data


_RAN = re.compile(r"Ran (\d+) tests?")
_FAILURES = re.compile(r"failures=(\d+)")


def _test_summary(output: str) -> str:
    """Turn unittest's tail into a one-line count; no pytest dependency in the demo."""
    ran = _RAN.search(output)
    if not ran:
        return output.strip().splitlines()[-1] if output.strip() else "no test output"
    total = int(ran.group(1))
    failures = 0
    match = _FAILURES.search(output)
    if match:
        failures = int(match.group(1))
    if failures:
        return f"{failures} failed, {total - failures} passed"
    return f"{total} passed"


def run_demo(*, directory: Path | None = None, force: bool = False) -> dict[str, Any]:
    target = Path(directory).resolve() if directory else (Path.cwd() / "crewgit-demo").resolve()
    if target.exists():
        if not force:
            raise CrewGitError(f"{target} already exists; pass --force to rebuild it")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel(
            "[bold]CrewGit demo[/bold]\n"
            "3 agents · 1 repo · 1 blocked scope violation · 0 merge conflicts\n"
            f"[dim]{target}[/dim]",
            border_style="green",
        )
    )

    git = Git(target)
    git.init("main")
    git.ensure_excluded()
    _git_identity(git)

    (target / "README.md").write_text(DEMO_README, encoding="utf-8")
    (target / "cart.py").write_text(DEMO_CART, encoding="utf-8")
    (target / "test_cart.py").write_text(DEMO_TEST, encoding="utf-8")
    base_commit = _commit(git, "demo: tiny cart with a rounding bug")

    console.rule("[bold]01 · baseline")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", "test_cart"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    summary = _test_summary(proc.stdout or proc.stderr)
    console.print(f"unittest on main: [red]{summary}[/red]  (the bug is real)")
    console.print("[dim]the coder agent must fix it inside a declared scope[/dim]")

    console.rule("[bold]02 · team and contracts")
    write_default_config(target, "demo-shop")
    for task in (PLAN_TASK, FIX_TASK, ROGUE_TASK, FIXED_TASK):
        write_task_file(Paths(target).tasks_dir / f"{task['id']}.yaml", _task_yaml(task))
    _commit(git, "chore: demo task contracts")

    table = Table(header_style="bold", box=None)
    for column in ("agent", "adapter", "role"):
        table.add_column(column)
    table.add_row("planner", "mock", "writes the plan")
    table.add_row("coder", "mock", "fixes the bug")
    table.add_row("reviewer", "mock", "gate: approve / revise")
    console.print(table)

    runner = Runner(target)
    run_ids: dict[str, str] = {}

    console.rule("[bold]03 · planner T-100")
    plan_run = runner.run_task("T-100")
    run_ids["T-100"] = plan_run.run_id
    _print_run(plan_run)
    if plan_run.status == "passed":
        merge = runner.merge(plan_run.run_id)
        console.print(f"[green]✓[/green] merged as {merge['commit'][:7]}  (plan is reviewable like any branch)")

    console.rule("[bold]04 · coder T-101 — fix inside scope")
    fix_run = runner.run_task("T-101")
    run_ids["T-101"] = fix_run.run_id
    _print_run(fix_run)
    if fix_run.status == "passed":
        merge = runner.merge(fix_run.run_id)
        console.print(f"[green]✓[/green] merged as {merge['commit'][:7]}  (tests were run in an isolated worktree)")
    else:
        raise CrewGitError("the coder run failed; demo cannot continue")

    console.rule("[bold]05 · coder T-102 — the sneaky version bump")
    rogue_run = runner.run_task("T-102")
    run_ids["T-102"] = rogue_run.run_id
    _print_run(rogue_run)
    console.print("[yellow]attempting to merge T-102 anyway…[/yellow]")
    try:
        runner.merge(rogue_run.run_id)
    except GateError as exc:
        console.print(f"[red]✗ merge refused:[/red] {exc.message}")
    console.print("[dim]nothing outside the declared scope can reach main — not even with a good intention[/dim]")

    console.rule("[bold]06 · coder T-102R — corrected contract")
    fixed_run = runner.run_task("T-102R")
    run_ids["T-102R"] = fixed_run.run_id
    _print_run(fixed_run)
    if fixed_run.status == "passed":
        merge = runner.merge(fixed_run.run_id)
        console.print(f"[green]✓[/green] merged as {merge['commit'][:7]}")

    console.rule("[bold]07 · main is green")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", "test_cart"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    summary = _test_summary(proc.stdout or proc.stderr)
    console.print(f"unittest on main: [green]{summary}[/green]")

    console.rule("[bold]08 · provenance and replay")
    log = subprocess.run(
        ["git", "log", "--oneline", "--decorate", "-5"],
        cwd=str(target),
        capture_output=True,
        text=True,
    ).stdout.strip()
    console.print(Panel(log, title="git log", border_style="dim"))
    trailers = subprocess.run(
        ["git", "log", "-1", "--format=%B", "HEAD"],
        cwd=str(target),
        capture_output=True,
        text=True,
    ).stdout.strip()
    console.print(Panel(trailers, title="merge commit body (trailers)", border_style="dim"))

    original = runner.load_run(run_ids["T-101"])
    replay = runner.replay(run_ids["T-101"])
    same = replay.reproduced
    console.print(
        f"replay T-101: {'[green]identical diff[/green]' if same else '[yellow]diverged[/yellow]'}  "
        f"{original.diff_sha256[:20]}… vs {replay.diff_sha256[:20]}…"
    )

    console.rule("[bold]09 · board")
    board = runner.board()
    table = Table(header_style="bold", box=None)
    for column in ("task", "status", "title", "latest gates"):
        table.add_column(column, overflow="fold")
    for item in board["tasks"]:
        latest = item["latest_run"]
        chips = " ".join(f"{gate['name']}:{gate['status']}" for gate in latest["gates"]) if latest else "—"
        table.add_row(item["id"], item["status"], item["title"], chips)
    console.print(table)
    console.print(
        f"runs {board['totals']['runs']} · cost "
        f"{'unmetered (mock agents)' if board['totals']['unmetered_runs'] else '$0'} · "
        f"overrides 0"
    )

    console.print(
        Panel(
            f"cd {target}\n"
            "crewgit board              # same board in the terminal\n"
            "crewgit serve --open       # board UI at http://127.0.0.1:7878\n"
            f"crewgit replay {run_ids['T-101']}\n"
            "git log --show-notes=crewgit\n"
            "crewgit mcp                # let other agents join",
            title="try it yourself",
            border_style="green",
        )
    )

    return {
        "path": str(target),
        "base_commit": base_commit,
        "runs": run_ids,
        "board": board,
        "reproduced": bool(same),
        "finished_at": iso_now(),
    }
