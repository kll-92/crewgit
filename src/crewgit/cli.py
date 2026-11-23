"""CrewGit command line interface."""

from __future__ import annotations

import json
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from . import __version__
from .config import Paths, find_root, load_config, write_default_config
from .contracts import dump_task_yaml, load_workspace_tasks, write_task_file
from .gitops import Git
from .models import ContractError, CrewGitError, Run
from .runner import Runner

app = typer.Typer(no_args_is_help=True, help="Git-native collaboration for coding agents.")
agent_app = typer.Typer(no_args_is_help=True, help="Manage agent definitions.")
task_app = typer.Typer(no_args_is_help=True, help="Manage task contracts.")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")

console = Console()
STATE_STYLE = {
    "todo": "white",
    "blocked": "red",
    "running": "cyan",
    "review": "yellow",
    "done": "green",
    "passed": "green",
    "failed": "red",
    "needs_human": "yellow",
    "merged": "green",
    "forced": "magenta",
    "rejected": "magenta",
    "skip": "dim",
}


def root_option() -> Path | None:
    return typer.Option(None, "--root", "-C", help="Project root (defaults to the current workspace)")


def _workspace(root: Path | None) -> Path:
    return Path(root).resolve() if root else find_root()


def _runner(root: Path | None) -> Runner:
    return Runner(_workspace(root))


@contextmanager
def guard():
    try:
        yield
    except CrewGitError as exc:
        console.print(f"[red]✗[/red] {escape(exc.message)}")
        if exc.detail:
            console.print(f"  [dim]{escape(str(exc.detail))}[/dim]")
        raise typer.Exit(code=1) from exc


def _style(value: str) -> str:
    return STATE_STYLE.get(value, "white")


def _gates_table(run: Run) -> Table:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("gate", style="bold")
    table.add_column("result")
    table.add_column("detail", overflow="fold")
    table.add_column("ms", justify="right", style="dim")
    for gate in run.gates:
        table.add_row(gate.name, f"[{_style(gate.status)}]{gate.status}[/]", gate.detail, str(gate.duration_ms))
    return table


def _print_run(run: Run, *, gates: bool = True) -> None:
    cost = f"${run.total_cost:.4f}" if run.total_cost is not None else "unmetered"
    commit = run.commit[:7] if run.commit else "—"
    lines = [
        f"[bold]{run.task_id}[/bold]  {escape(run.title)}",
        f"agent [bold]{run.agent}[/bold] ({run.adapter})   model {run.model or '—'}",
        f"branch {run.branch or '—'}   commit {commit}   cost {cost}   {run.duration_ms} ms",
        f"diff {run.diff_stat.get('files', 0)} file(s) "
        f"[green]+{run.diff_stat.get('insertions', 0)}[/green] "
        f"[red]-{run.diff_stat.get('deletions', 0)}[/red]",
    ]
    if run.changed_files:
        shown = ", ".join(run.changed_files[:8])
        more = "" if len(run.changed_files) <= 8 else f" (+{len(run.changed_files) - 8} more)"
        lines.append(f"files {shown}{more}")
    if run.error:
        lines.append(f"[red]{escape(run.error.splitlines()[0][:300])}[/red]")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"{run.run_id} · [{_style(run.status)}]{run.status}[/]",
            border_style=_style(run.status),
        )
    )
    if gates and run.gates:
        console.print(_gates_table(run))


# --------------------------------------------------------------------------- init


@app.command()
def init(
    root: Path | None = root_option(),
    project: str | None = typer.Option(None, "--project", help="Project name shown on the board"),
    branch: str = typer.Option("main", "--branch", help="Default branch"),
    init_git: bool = typer.Option(False, "--init-git", help="Run `git init` when the folder is not a repository"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing CrewGit config"),
) -> None:
    """Create .crewgit/config.yaml, tasks/ and agent defaults."""
    with guard():
        workspace = Path(root or Path.cwd()).resolve()
        paths = Paths(workspace)
        if paths.config_file.exists() and not force:
            raise ContractError("workspace is already initialised; pass --force to rewrite .crewgit/config.yaml")
        git = Git(workspace)
        if not git.is_repo():
            if not init_git:
                raise CrewGitError("not a git repository: run `git init` first, or pass --init-git")
            git.init(branch)
        elif not git.is_clean():
            console.print("[yellow]![/yellow] main worktree has uncommitted changes; commit them before running agents")
        paths.ensure()
        write_default_config(workspace, project or workspace.name, branch)
        git.ensure_excluded()
        paths.tasks_dir.mkdir(parents=True, exist_ok=True)
        console.print(
            Panel(
                f"config   {paths.config_file.relative_to(workspace)}\n"
                f"tasks    {paths.tasks_dir.relative_to(workspace)}/\n"
                f"agents   planner, coder, reviewer (mock adapters)\n\n"
                "next:\n"
                "  1. edit .crewgit/config.yaml to add your real agents\n"
                "  2. crewgit task new --id T-001 --title \"first task\" --scope 'src/**'\n"
                "  3. crewgit run T-001\n"
                "  4. crewgit serve",
                title="CrewGit workspace ready",
                border_style="green",
            )
        )


# --------------------------------------------------------------------------- agents


@agent_app.command("list")
def agent_list(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """List agents from .crewgit/config.yaml."""
    with guard():
        config = load_config(_workspace(root))
        if as_json:
            print(json.dumps({name: cfg.to_dict() for name, cfg in config.agents.items()}, indent=2, ensure_ascii=False))
            return
        table = Table(header_style="bold")
        table.add_column("agent", style="bold")
        table.add_column("adapter")
        table.add_column("role")
        table.add_column("command / model", overflow="fold")
        for name, cfg in sorted(config.agents.items()):
            table.add_row(name, cfg.adapter, cfg.role or "—", cfg.command or cfg.model or "—")
        console.print(table)


@agent_app.command("add")
def agent_add(
    name: str = typer.Argument(..., help="Agent name, used by tasks"),
    adapter: str = typer.Option("mock", "--adapter", help="mock | generic | claude"),
    role: str = typer.Option("", "--role", help="planner | coder | reviewer (mock only)"),
    command: str | None = typer.Option(None, "--command", help="Command template for the generic adapter"),
    model: str | None = typer.Option(None, "--model", help="Model label for manifests"),
    force: bool = typer.Option(False, "--force"),
    root: Path | None = root_option(),
) -> None:
    """Add or replace an agent in .crewgit/config.yaml."""
    with guard():
        workspace = _workspace(root)
        config = load_config(workspace)
        if name in config.agents and not force:
            raise ContractError(f"agent '{name}' already exists; pass --force to replace it")
        if adapter not in ("mock", "generic", "claude"):
            raise ContractError(f"unknown adapter '{adapter}' (known: mock, generic, claude)")
        if adapter == "generic" and not command:
            raise ContractError("the generic adapter needs --command, e.g. 'aider --yes --message-file {prompt_file}'")
        data = yaml.safe_load(Paths(workspace).config_file.read_text(encoding="utf-8"))
        entry: dict[str, Any] = {"adapter": adapter}
        if role:
            entry["role"] = role
        if command:
            entry["command"] = command
        if model:
            entry["model"] = model
        data.setdefault("agents", {})[name] = entry
        Paths(workspace).config_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        load_config(workspace)  # validate before claiming success
        console.print(f"[green]✓[/green] agent '{name}' saved ({adapter})")


@agent_app.command("remove")
def agent_remove(
    name: str = typer.Argument(...),
    root: Path | None = root_option(),
) -> None:
    """Remove an agent, refusing when the review gate still references it."""
    with guard():
        workspace = _workspace(root)
        data = yaml.safe_load(Paths(workspace).config_file.read_text(encoding="utf-8"))
        agents = data.get("agents") or {}
        if name not in agents:
            raise ContractError(f"agent '{name}' does not exist")
        del agents[name]
        Paths(workspace).config_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        load_config(workspace)
        console.print(f"[green]✓[/green] agent '{name}' removed")


# --------------------------------------------------------------------------- tasks


@task_app.command("list")
def task_list(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """List task contracts with derived board status."""
    with guard():
        board = _runner(root).board()
        if as_json:
            print(json.dumps(board, indent=2, ensure_ascii=False))
            return
        table = Table(header_style="bold")
        for column in ("task", "status", "title", "agent", "deps", "scope"):
            table.add_column(column, overflow="fold")
        for item in board["tasks"]:
            table.add_row(
                item["id"],
                f"[{_style(item['status'])}]{item['status']}[/]",
                item["title"],
                item["agent"] or "coder",
                ", ".join(item["depends_on"]) or "—",
                ", ".join(item["scope"]),
            )
        console.print(table)


@task_app.command("show")
def task_show(task_id: str = typer.Argument(...), root: Path | None = root_option()) -> None:
    """Show a contract and its runs."""
    with guard():
        runner = _runner(root)
        task = runner.task(task_id)
        console.print(Syntax(dump_task_yaml(task), "yaml", theme="monokai", word_wrap=True))
        runs = runner.store.list_runs(task_id)
        if not runs:
            console.print("[dim]no runs yet[/dim]")
            return
        table = Table(header_style="bold")
        for column in ("run", "agent", "status", "gates", "diff", "commit"):
            table.add_column(column)
        for run in runs:
            gate_chips = " ".join(f"{gate.name}:{gate.status}" for gate in run.gates) or "—"
            table.add_row(
                run.run_id,
                run.agent,
                f"[{_style(run.status)}]{run.status}[/]",
                gate_chips,
                f"{run.diff_stat.get('files', 0)}f +{run.diff_stat.get('insertions', 0)}/-{run.diff_stat.get('deletions', 0)}",
                run.commit[:7] if run.commit else "—",
            )
        console.print(table)


@task_app.command("new")
def task_new(
    task_id: str = typer.Option(..., "--id", help="Task id, e.g. T-101"),
    title: str = typer.Option(..., "--title"),
    scope: list[str] = typer.Option(..., "--scope", help="Path glob the agent may touch (repeatable)"),
    agent: str | None = typer.Option(None, "--agent"),
    depends: list[str] | None = typer.Option(None, "--depends", help="Dependency task id (repeatable)"),
    tests: str | None = typer.Option(None, "--tests", help="Acceptance command"),
    max_files: int = typer.Option(6, "--max-files"),
    max_lines: int = typer.Option(300, "--max-lines"),
    force: bool = typer.Option(False, "--force"),
    root: Path | None = root_option(),
) -> None:
    """Write a starter task contract."""
    with guard():
        workspace = _workspace(root)
        path = Paths(workspace).tasks_dir / f"{task_id}.yaml"
        if path.exists() and not force:
            raise ContractError(f"task file already exists: {path.name}; pass --force to overwrite")
        data: dict[str, Any] = {
            "id": task_id,
            "title": title,
            "scope": list(scope),
            "budget": {"max_files": max_files, "max_lines": max_lines},
        }
        if agent:
            data["agent"] = agent
        if depends:
            data["depends_on"] = list(depends)
        if tests:
            data["acceptance"] = {"tests": tests}
        write_task_file(path, data)
        load_workspace_tasks(workspace, load_config(workspace))  # validate now
        console.print(f"[green]✓[/green] wrote {path.relative_to(workspace)}")
        console.print("[dim]add `context` and `mock_actions`, then commit the contract[/dim]")


@task_app.command("check")
def task_check(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """Validate every contract, including dependencies and cycles."""
    with guard():
        try:
            tasks = load_workspace_tasks(_workspace(root), load_config(_workspace(root)))
        except ContractError as exc:
            if as_json:
                print(json.dumps({"ok": False, "error": exc.to_dict()}, indent=2))
            raise
        if as_json:
            print(json.dumps({"ok": True, "tasks": sorted(tasks)}, indent=2))
        else:
            console.print(f"[green]✓[/green] {len(tasks)} contract(s) valid")


# --------------------------------------------------------------------------- runs


@app.command()
def run(
    task_id: str | None = typer.Argument(None, help="Task id; omit with --ready"),
    agent: str | None = typer.Option(None, "--agent", "-a"),
    ready: bool = typer.Option(False, "--ready", help="Run every unblocked task"),
    parallel: int = typer.Option(1, "--parallel", "-p", help="Concurrent runs for --ready"),
    limit: int | None = typer.Option(None, "--limit", help="Cap the ready set"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan and resolved command, execute nothing"),
    as_json: bool = typer.Option(False, "--json"),
    root: Path | None = root_option(),
) -> None:
    """Run one task, or the whole ready set, in isolated worktrees."""
    with guard():
        runner = _runner(root)
        if dry_run:
            if not task_id:
                raise ContractError("--dry-run requires a task id")
            plan = runner.plan(task_id, agent)
            if as_json:
                print(json.dumps(plan, indent=2, ensure_ascii=False))
            else:
                table = Table(header_style="bold", show_header=False)
                table.add_column("key", style="bold")
                table.add_column("value", overflow="fold")
                for key in ("task", "title", "agent", "adapter", "branch", "worktree", "prompt_sha256", "command"):
                    table.add_row(key, str(plan[key]))
                console.print(Panel(table, title="dry run · nothing executed", border_style="yellow"))
            return
        if ready:
            runs = runner.run_ready(parallel=parallel, limit=limit)
            if not runs:
                console.print("no ready tasks")
                return
            for item in runs:
                _print_run(item)
            if any(item.status in ("failed", "needs_human") for item in runs):
                raise typer.Exit(code=1)
            return
        if not task_id:
            raise ContractError("provide a task id, or use --ready to run the ready set")
        item = runner.run_task(task_id, agent)
        if as_json:
            print(json.dumps(item.to_dict(), indent=2, ensure_ascii=False))
        else:
            _print_run(item)
        if item.status != "passed":
            raise typer.Exit(code=1)


@app.command()
def board(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """Print the board: todo / blocked / running / review / done."""
    with guard():
        data = _runner(root).board()
        if as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        counts = data["counts"]
        totals = data["totals"]
        cost = (
            "unmetered"
            if totals["runs"] and totals["unmetered_runs"] >= totals["runs"]
            else f"${totals['cost_usd']:.4f}"
        )
        console.print(
            f"[bold]{escape(data['project'])}[/bold] · "
            + "  ".join(f"{name} [{_style(name)}]{value}[/]" for name, value in counts.items())
            + f"  ·  {totals['runs']} run(s) · {cost}"
        )
        table = Table(header_style="bold", box=None)
        for column in ("task", "status", "title", "agent", "latest", "gates", "diff"):
            table.add_column(column, overflow="fold")
        for item in data["tasks"]:
            latest = item["latest_run"]
            gate_chips = " ".join(f"{gate['name']}:{gate['status']}" for gate in latest["gates"]) if latest else "—"
            diff = (
                f"{latest['diff_stat'].get('files', 0)}f +{latest['diff_stat'].get('insertions', 0)}/-{latest['diff_stat'].get('deletions', 0)}"
                if latest
                else "—"
            )
            table.add_row(
                item["id"],
                f"[{_style(item['status'])}]{item['status']}[/]",
                escape(item["title"]),
                item["agent"] or "coder",
                latest["run_id"] if latest else "—",
                gate_chips,
                diff,
            )
        console.print(table)
        blocked = [item for item in data["tasks"] if item["status"] == "blocked"]
        for item in blocked:
            console.print(f"[red]blocked[/red] {item['id']}: {escape(item.get('status_reason') or '')}")


@app.command()
def show(
    run_id: str = typer.Argument(...),
    diff: bool = typer.Option(False, "--diff", help="Print the unified diff"),
    as_json: bool = typer.Option(False, "--json"),
    root: Path | None = root_option(),
) -> None:
    """Inspect a run manifest, gates and optional diff."""
    with guard():
        runner = _runner(root)
        item = runner.load_run(run_id)
        if as_json:
            print(json.dumps(item.to_dict(), indent=2, ensure_ascii=False))
            return
        _print_run(item)
        if item.usage:
            console.print(f"[dim]usage: {json.dumps(item.usage, ensure_ascii=False)}[/dim]")
        if diff and item.commit:
            console.print(Syntax(runner.git.diff_text(item.base_commit, item.commit), "diff", word_wrap=True))


@app.command()
def merge(
    run_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Merge despite red gates (requires --reason)"),
    reason: str | None = typer.Option(None, "--reason", help="Audited override reason"),
    root: Path | None = root_option(),
) -> None:
    """Merge a passed run into the default branch with provenance trailers."""
    with guard():
        runner = _runner(root)
        result = runner.merge(run_id, force=force, reason=reason)
        item: Run = result["run"]
        status = item.status
        console.print(
            f"[green]✓[/green] merged {item.run_id} ({status}) into {runner.config.default_branch} "
            f"as {result['commit'][:7]}"
        )
        if item.override:
            console.print(f"[magenta]override recorded:[/magenta] {escape(item.override)}")


@app.command()
def reject(
    run_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason"),
    root: Path | None = root_option(),
) -> None:
    """Reject a run with a recorded reason."""
    with guard():
        item = _runner(root).reject(run_id, reason)
        console.print(f"[magenta]✗[/magenta] rejected {item.run_id}: {escape(reason)}")


@app.command()
def replay(run_id: str = typer.Argument(...), root: Path | None = root_option()) -> None:
    """Re-execute a run on its original base commit and compare diff hashes."""
    with guard():
        runner = _runner(root)
        original = runner.load_run(run_id)
        item = runner.replay(run_id)
        same = item.reproduced
        title = "replay · identical diff" if same else "replay · diverged"
        console.print(
            Panel(
                f"original {original.run_id}  {original.diff_sha256}\n"
                f"replay   {item.run_id}  {item.diff_sha256}\n"
                f"status   {item.status}\n"
                f"files    {', '.join(item.changed_files) or '—'}",
                title=title,
                border_style="green" if same else "yellow",
            )
        )


@app.command()
def stats(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """Cost and throughput per agent."""
    with guard():
        data = _runner(root).stats()
        if as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        table = Table(header_style="bold")
        for column in ("agent", "runs", "passed", "failed", "merged", "unmetered", "cost", "avg ms"):
            table.add_column(column, justify="right" if column != "agent" else "left")
        for name, entry in sorted(data["agents"].items()):
            avg = entry["duration_ms"] // entry["runs"] if entry["runs"] else 0
            table.add_row(
                name,
                str(entry["runs"]),
                str(entry["passed"]),
                str(entry["failed"]),
                str(entry["merged"]),
                str(entry["unmetered"]),
                "unmetered" if entry["runs"] and entry["unmetered"] >= entry["runs"] else f"${entry['cost_usd']:.4f}",
                str(avg),
            )
        console.print(table)
        totals = data["totals"]
        cost = (
            "unmetered"
            if totals["runs"] and totals.get("unmetered_runs", 0) >= totals["runs"]
            else f"${totals['cost_usd']:.4f}"
        )
        console.print(
            f"totals: {totals['runs']} run(s), {cost}, {data['overrides']} override(s)"
        )


@app.command()
def doctor(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """Check workspace health: dirty tree, stale locks, orphan worktrees, missing notes."""
    with guard():
        checks = _runner(root).doctor()
        if as_json:
            print(json.dumps(checks, indent=2, ensure_ascii=False))
        else:
            table = Table(header_style="bold", box=None)
            for column in ("check", "status", "detail"):
                table.add_column(column, overflow="fold")
            for check in checks:
                table.add_row(check["name"], f"[{_style(check['status'])}]{check['status']}[/]", check["detail"])
            console.print(table)
        if any(check["status"] == "fail" for check in checks):
            raise typer.Exit(code=1)


@app.command()
def gc(root: Path | None = root_option(), as_json: bool = typer.Option(False, "--json")) -> None:
    """Expire locks and clean orphan worktrees."""
    with guard():
        result = _runner(root).gc()
        if as_json:
            print(json.dumps(result, indent=2))
        else:
            console.print(f"expired locks: {result['expired_locks']}, worktrees removed: {result['worktrees_removed']}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(7878, "--port"),
    read_only: bool = typer.Option(False, "--read-only", help="Disable run/merge actions"),
    open_browser: bool = typer.Option(False, "--open", help="Open the board in a browser"),
    root: Path | None = root_option(),
) -> None:
    """Serve the board API and UI."""
    with guard():
        import uvicorn

        from .server import create_app

        workspace = _workspace(root)
        url = f"http://{host}:{port}"
        console.print(f"[green]CrewGit board[/green] {url}  (read-only={read_only})")
        if open_browser:
            webbrowser.open(url)
        uvicorn.run(create_app(workspace, read_only=read_only), host=host, port=port, log_level="warning")


@app.command()
def mcp(root: Path | None = root_option()) -> None:
    """Run the MCP stdio server so other agents can join the team."""
    with guard():
        from .mcp import serve_stdio

        serve_stdio(_workspace(root))


@app.command()
def demo(
    directory: Path | None = typer.Option(None, "--dir", help="Where to build the demo project"),
    force: bool = typer.Option(False, "--force", help="Reuse/overwrite an existing demo directory"),
    serve_board: bool = typer.Option(False, "--serve", help="Start the board after the demo"),
    root: Path | None = root_option(),
) -> None:
    """Run the offline 60-second demo: planner, coder, reviewer, a blocked scope violation, a merge."""
    with guard():
        from .demo import run_demo

        result = run_demo(directory=directory, force=force)
        if serve_board:
            import uvicorn

            from .server import create_app

            console.print("[green]serving demo board[/green] http://127.0.0.1:7879")
            uvicorn.run(create_app(Path(result["path"]), read_only=False), host="127.0.0.1", port=7879, log_level="warning")


@app.command()
def version() -> None:
    """Print the version."""
    print(f"crewgit {__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()
