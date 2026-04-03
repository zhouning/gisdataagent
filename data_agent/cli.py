"""
GIS Data Agent CLI (v8.5).

Terminal interface powered by Typer + Rich.
Reuses pipeline_runner.py for headless execution — zero Chainlit dependency.

Usage:
    python -m data_agent run "分析土地数据"
    python -m data_agent chat
    python -m data_agent catalog list
    python -m data_agent sql "SELECT count(*) FROM ..."
    python -m data_agent status
"""

import asyncio
import getpass
import importlib
import os
import sys
import uuid
import webbrowser
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="gis-agent",
    help="GIS Data Agent CLI v12.0 — AI-powered geospatial analysis",
    no_args_is_help=True,
)
catalog_app = typer.Typer(help="Data catalog operations")
skills_app = typer.Typer(help="Custom skill management")
app.add_typer(catalog_app, name="catalog")
app.add_typer(skills_app, name="skills")

console = Console()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_env_loaded = False


def _load_env():
    """Load .env from data_agent directory (idempotent)."""
    global _env_loaded
    if _env_loaded:
        return
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    _env_loaded = True


def _set_user_context(user: str, role: str) -> str:
    """Set ContextVars for the current user. Returns session_id."""
    from data_agent.user_context import (
        current_user_id, current_session_id, current_user_role,
    )
    session_id = f"cli_{user}_{uuid.uuid4().hex[:8]}"
    current_user_id.set(user)
    current_session_id.set(session_id)
    current_user_role.set(role)
    return session_id


def _get_session_service():
    """Create InMemorySessionService for CLI sessions."""
    from google.adk.sessions import InMemorySessionService
    return InMemorySessionService()


def _get_app_module():
    """Lazy-import data_agent.app to avoid loading Chainlit at CLI parse time."""
    return importlib.import_module("data_agent.app")


def _select_agent(app_mod, intent: str):
    """Return (agent_instance, pipeline_type) based on intent classification."""
    dynamic_planner = getattr(app_mod, "DYNAMIC_PLANNER", False)
    if dynamic_planner:
        return app_mod.planner_agent, "planner"
    if intent == "GOVERNANCE":
        return app_mod.governance_pipeline, "governance"
    if intent == "OPTIMIZATION":
        return app_mod.data_pipeline, "optimization"
    return app_mod.general_pipeline, "general"


def _streaming_callback(event: dict):
    """Rich live-update callback for verbose mode."""
    etype = event.get("type")
    if etype == "agent":
        console.print(f"  [dim cyan]Agent: {event['name']}[/dim cyan]")
    elif etype == "tool_call":
        console.print(f"  [dim]>> {event['name']}()[/dim]")
    elif etype == "tool_result":
        summary = event.get("summary", "")[:80]
        status_icon = "[green]ok[/green]"
        console.print(f"  [dim]   #{event['step']} {status_icon} {summary}[/dim]")
    elif etype == "text":
        pass  # Text is shown in final result panel


def _render_result(result, verbose: bool = False):
    """Render PipelineResult to Rich console output."""
    if result.error:
        console.print(Panel(
            f"[red bold]Error:[/red bold] {result.error}",
            title="Pipeline Error", border_style="red",
        ))
        return

    # Report text
    report = result.report_text or "(no output)"
    if len(report) > 5000:
        report = report[:5000] + "\n... (truncated)"
    try:
        console.print(Panel(Markdown(report), title="Analysis Report", border_style="green"))
    except Exception:
        console.print(Panel(report, title="Analysis Report", border_style="green"))

    # Generated files
    if result.generated_files:
        console.print("\n[bold]Generated Files:[/bold]")
        for f in result.generated_files:
            icon = "🗺️" if f.endswith(".html") else "📄"
            console.print(f"  {icon} {f}")

    # Tool execution log (verbose only)
    if verbose and result.tool_execution_log:
        table = Table(title="Tool Execution Log", show_lines=True)
        table.add_column("#", width=4)
        table.add_column("Agent", max_width=20)
        table.add_column("Tool", max_width=25)
        table.add_column("Duration", width=8)
        table.add_column("Result", max_width=40)
        for entry in result.tool_execution_log:
            dur = f"{entry.get('duration', 0):.1f}s"
            status = "[red]ERR[/red]" if entry.get("is_error") else "[green]ok[/green]"
            table.add_row(
                str(entry["step"]),
                entry.get("agent_name", ""),
                entry["tool_name"],
                dur,
                f"{status} {entry.get('result_summary', '')[:30]}",
            )
        console.print(table)

    # Stats line
    console.print(
        f"\n[dim]Pipeline: {result.pipeline_type} | "
        f"Duration: {result.duration_seconds:.1f}s | "
        f"Tokens: {result.total_input_tokens}in/{result.total_output_tokens}out[/dim]"
    )


def _open_files(file_paths: list):
    """Open HTML map files in browser, print paths for others."""
    for fpath in file_paths:
        if fpath.endswith(".html") and os.path.exists(fpath):
            console.print(f"  [blue]Opening in browser:[/blue] {fpath}")
            webbrowser.open(f"file://{os.path.abspath(fpath)}")


async def _run_single(
    prompt: str,
    user: str,
    role: str,
    verbose: bool = False,
    open_files: bool = False,
    previous_pipeline: str = None,
) -> tuple:
    """Core async execution: classify → select agent → run pipeline → render.

    Returns (pipeline_type, PipelineResult).
    """
    _load_env()
    session_id = _set_user_context(user, role)

    app_mod = _get_app_module()
    classify_intent = app_mod.classify_intent
    # CLI always uses InMemorySessionService (no DB session needed)
    session_service = _get_session_service()

    # Intent classification
    with console.status("[bold green]Classifying intent..."):
        intent, reason, router_tokens, tool_cats, _lang = classify_intent(prompt, previous_pipeline)

    if verbose:
        console.print(f"  Intent: [bold]{intent}[/bold] ({reason})")

    # RBAC check
    if role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
        console.print(f"[red]Access denied: role '{role}' cannot use {intent} pipeline[/red]")
        raise typer.Exit(1)

    agent, pipeline_type = _select_agent(app_mod, intent)

    # Build prompt with router hint for planner
    full_prompt = prompt
    dynamic_planner = getattr(app_mod, "DYNAMIC_PLANNER", False)
    if dynamic_planner:
        full_prompt = prompt + f"\n\n[意图分类提示] 路由器判断: {intent}（{reason}）"

    # Set tool categories context
    from data_agent.user_context import current_tool_categories
    current_tool_categories.set(tool_cats)

    from data_agent.pipeline_runner import run_pipeline_headless

    with console.status(f"[bold green]Running {pipeline_type} pipeline..."):
        result = await run_pipeline_headless(
            agent=agent,
            session_service=session_service,
            user_id=user,
            session_id=session_id,
            prompt=full_prompt,
            pipeline_type=pipeline_type,
            intent=intent,
            router_tokens=router_tokens,
            use_dynamic_planner=dynamic_planner,
            role=role,
            on_event=_streaming_callback if verbose else None,
        )

    _render_result(result, verbose)

    if open_files and result.generated_files:
        _open_files(result.generated_files)

    # Record token usage (non-fatal)
    try:
        from data_agent.token_tracker import record_usage
        tracking_type = pipeline_type
        if dynamic_planner and pipeline_type == "planner":
            tracking_type = intent.lower() if intent != "AMBIGUOUS" else "general"
        record_usage(user, tracking_type, result.total_input_tokens, result.total_output_tokens)
    except Exception:
        pass

    return pipeline_type, result


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def run(
    prompt: str = typer.Argument(..., help="Analysis prompt (e.g. '分析土地数据')"),
    user: str = typer.Option(None, "--user", "-u", help="Username (default: OS user)"),
    role: str = typer.Option("analyst", "--role", "-r", help="Role: admin/analyst/viewer"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool execution log"),
    open: bool = typer.Option(False, "--open", "-o", help="Open generated HTML files"),
):
    """Run a single analysis prompt through the GIS pipeline."""
    if user is None:
        user = getpass.getuser()
    asyncio.run(_run_single(prompt, user, role, verbose, open))


@app.command()
def chat(
    user: str = typer.Option(None, "--user", "-u", help="Username (default: OS user)"),
    role: str = typer.Option("analyst", "--role", "-r", help="Role: admin/analyst/viewer"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool execution log"),
):
    """Interactive REPL mode — type prompts, get analysis results."""
    if user is None:
        user = getpass.getuser()

    _load_env()
    console.print(Panel(
        "[bold]GIS Data Agent CLI v12.0[/bold]\n"
        "Type your analysis prompt. Commands: /quit, /verbose, /help\n"
        "Press Ctrl+D or type /quit to exit.",
        border_style="blue",
    ))

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        session = PromptSession(history=InMemoryHistory())
    except ImportError:
        session = None

    previous_pipeline = None
    while True:
        try:
            if session:
                text = session.prompt("gis> ")
            else:
                text = input("gis> ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        text = text.strip()
        if not text:
            continue
        if text in ("/quit", "/exit", "exit", "quit"):
            console.print("[dim]Goodbye![/dim]")
            break
        if text == "/verbose":
            verbose = not verbose
            console.print(f"Verbose mode: {'on' if verbose else 'off'}")
            continue
        if text == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit     Exit the REPL\n"
                "  /verbose  Toggle verbose mode\n"
                "  /help     Show this help\n"
                "  (anything else is an analysis prompt)"
            )
            continue

        try:
            pipeline_type, _ = asyncio.run(
                _run_single(text, user, role, verbose, open_files=False,
                            previous_pipeline=previous_pipeline)
            )
            previous_pipeline = pipeline_type
        except SystemExit:
            pass
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


@catalog_app.command("list")
def catalog_list(
    asset_type: str = typer.Option("", "--type", "-t", help="Filter: vector/raster/tabular"),
    keyword: str = typer.Option("", "--keyword", "-k", help="Filter by keyword"),
    backend: str = typer.Option("", "--backend", "-b", help="Filter: local/cloud/postgis"),
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
):
    """List data catalog assets."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    from data_agent.data_catalog import list_data_assets
    result = list_data_assets(asset_type=asset_type, keyword=keyword,
                              storage_backend=backend)

    if result.get("status") == "error":
        console.print(f"[red]Error: {result.get('message', 'Unknown error')}[/red]")
        raise typer.Exit(1)

    assets = result.get("assets", [])
    if not assets:
        console.print("[yellow]No assets found.[/yellow]")
        return

    table = Table(title=f"Data Catalog ({result.get('count', len(assets))} assets)")
    table.add_column("ID", width=4)
    table.add_column("Name", max_width=30)
    table.add_column("Type", width=10)
    table.add_column("Backend", width=10)
    table.add_column("Features", width=8, justify="right")
    table.add_column("Description", max_width=40)

    for a in assets:
        table.add_row(
            str(a.get("id", "")),
            a.get("name", ""),
            a.get("type", ""),
            a.get("backend", ""),
            str(a.get("features", "")),
            (a.get("description") or "")[:40],
        )
    console.print(table)


@catalog_app.command("search")
def catalog_search(
    query: str = typer.Argument(..., help="Search query (e.g. '土地利用')"),
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
):
    """Fuzzy search the data catalog."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    from data_agent.data_catalog import search_data_assets
    result = search_data_assets(query)

    if isinstance(result, str):
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)

    if result.get("status") == "error":
        console.print(f"[red]Error: {result.get('message', 'Unknown')}[/red]")
        raise typer.Exit(1)

    assets = result.get("assets", [])
    if not assets:
        console.print(f"[yellow]No results for '{query}'.[/yellow]")
        return

    table = Table(title=f"Search: '{query}' ({len(assets)} results)")
    table.add_column("ID", width=4)
    table.add_column("Name", max_width=30)
    table.add_column("Type", width=10)
    table.add_column("Description", max_width=50)

    for a in assets:
        table.add_row(
            str(a.get("id", "")),
            a.get("name", ""),
            a.get("type", ""),
            (a.get("description") or "")[:50],
        )
    console.print(table)


@skills_app.command("list")
def skills_list(
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
):
    """List custom skills."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    from data_agent.custom_skills import list_custom_skills
    skills = list_custom_skills(include_shared=True)

    if not skills:
        console.print("[yellow]No custom skills found.[/yellow]")
        return

    table = Table(title=f"Custom Skills ({len(skills)})")
    table.add_column("ID", width=4)
    table.add_column("Name", max_width=25)
    table.add_column("Description", max_width=40)
    table.add_column("Model", width=10)
    table.add_column("Shared", width=6)

    for s in skills:
        table.add_row(
            str(s.get("id", "")),
            s.get("skill_name", ""),
            (s.get("description") or "")[:40],
            s.get("model_tier", "standard"),
            "yes" if s.get("is_shared") else "no",
        )
    console.print(table)


@skills_app.command("delete")
def skills_delete(
    skill_id: int = typer.Argument(..., help="Skill ID to delete"),
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a custom skill by ID."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    if not force:
        confirm = typer.confirm(f"Delete skill #{skill_id}?")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            return

    from data_agent.custom_skills import delete_custom_skill
    ok = delete_custom_skill(skill_id)
    if ok:
        console.print(f"[green]Skill #{skill_id} deleted.[/green]")
    else:
        console.print(f"[red]Failed to delete skill #{skill_id} (not found or not owner).[/red]")
        raise typer.Exit(1)


@app.command()
def sql(
    query: str = typer.Argument(..., help="SQL SELECT query"),
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
):
    """Execute a read-only SQL query and display results."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    from data_agent.database_tools import query_database
    result = query_database(query)

    if result.get("status") == "error":
        console.print(f"[red]Error: {result.get('message', 'Query failed')}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{result.get('message', 'OK')}[/green]")

    # Render CSV output as Rich Table
    output_path = result.get("output_path", "")
    if output_path and os.path.exists(output_path) and output_path.endswith(".csv"):
        try:
            import pandas as pd
            df = pd.read_csv(output_path, nrows=50)
            table = Table(title=f"Query Results ({result.get('record_count', len(df))} rows)")
            for col in df.columns:
                table.add_column(str(col), max_width=30)
            for _, row in df.iterrows():
                table.add_row(*[str(v)[:30] for v in row])
            console.print(table)
        except Exception as e:
            console.print(f"[dim]Output saved to: {output_path}[/dim]")
    elif output_path:
        console.print(f"[dim]Output saved to: {output_path}[/dim]")


@app.command()
def status(
    user: str = typer.Option(None, "--user", "-u"),
    role: str = typer.Option("analyst", "--role", "-r"),
):
    """Show token usage and system status."""
    if user is None:
        user = getpass.getuser()
    _load_env()
    _set_user_context(user, role)

    console.print(Panel(
        f"[bold]GIS Data Agent[/bold] v12.0\n"
        f"User: {user} | Role: {role}",
        border_style="blue",
    ))

    # Token usage
    from data_agent.token_tracker import get_daily_usage, get_monthly_usage, get_pipeline_breakdown

    daily = get_daily_usage(user)
    monthly = get_monthly_usage(user)

    table = Table(title="Token Usage")
    table.add_column("Period", width=12)
    table.add_column("Requests", width=10, justify="right")
    table.add_column("Tokens", width=12, justify="right")

    table.add_row("Today", str(daily.get("count", 0)),
                   f"{daily.get('tokens', 0):,}")
    table.add_row("This month", str(monthly.get("count", 0)),
                   f"{monthly.get('total_tokens', 0):,}")
    console.print(table)

    # Pipeline breakdown
    breakdown = get_pipeline_breakdown(user)
    if breakdown:
        bd_table = Table(title="Pipeline Breakdown (This Month)")
        bd_table.add_column("Pipeline", width=15)
        bd_table.add_column("Count", width=8, justify="right")
        bd_table.add_column("Tokens", width=12, justify="right")
        for row in breakdown:
            bd_table.add_row(
                row.get("pipeline_type", "unknown"),
                str(row.get("count", 0)),
                f"{row.get('tokens', 0):,}",
            )
        console.print(bd_table)


# ---------------------------------------------------------------------------
# TUI command
# ---------------------------------------------------------------------------

@app.command()
def tui(
    user: str = typer.Option(None, "--user", "-u", help="Username (default: OS user)"),
    role: str = typer.Option("analyst", "--role", "-r", help="Role: admin/analyst/viewer"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool execution log"),
):
    """Full-screen TUI mode — three-panel terminal interface."""
    if user is None:
        user = getpass.getuser()
    from data_agent.tui import GISAgentApp
    tui_app = GISAgentApp(user=user, role=role, verbose=verbose)
    tui_app.run()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
