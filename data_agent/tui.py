"""
GIS Data Agent TUI (v8.5.3).

Full-screen terminal interface powered by Textual + Rich.
Three-panel layout: Chat | Report | Status.
Reuses pipeline_runner.py for headless execution — zero Chainlit dependency.

Usage:
    python -m data_agent tui
    python -m data_agent tui --user admin --role admin
"""

import asyncio
import getpass
import os
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.worker import Worker, WorkerState
from textual import work

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# ---------------------------------------------------------------------------
# GISAgentApp
# ---------------------------------------------------------------------------

class GISAgentApp(App):
    """Full-screen TUI for GIS Data Agent."""

    CSS_PATH = "tui.tcss"
    TITLE = "GIS Data Agent TUI v8.5"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_panels", "Clear", show=True),
        Binding("f1", "show_help", "Help", show=True),
    ]

    def __init__(self, user: str = "", role: str = "analyst",
                 verbose: bool = False):
        super().__init__()
        self.user = user or getpass.getuser()
        self.role = role
        self.verbose = verbose
        self._previous_pipeline: Optional[str] = None
        self._pipeline_running = False
        self._command_history: list[str] = []
        self._history_index = -1

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="chat-panel"):
                yield RichLog(id="chat-log", markup=True, wrap=True,
                              highlight=True)
                yield Input(
                    placeholder="gis> Type prompt or /help",
                    id="chat-input",
                )
            with Vertical(id="report-panel"):
                yield Static("Report", id="report-header")
                yield RichLog(id="report-log", markup=True, wrap=True,
                              highlight=True)
            with Vertical(id="status-panel"):
                yield Static("Status", id="status-header")
                yield RichLog(id="status-log", markup=True, wrap=True,
                              highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        # Welcome banner
        self._write_chat(
            "[bold blue]GIS Data Agent TUI v8.5[/bold blue]\n"
            f"User: [cyan]{self.user}[/cyan] | Role: [cyan]{self.role}[/cyan]\n"
            "Type a prompt to analyze, or /help for commands.\n"
            "Press [bold]Ctrl+Q[/bold] to quit."
        )
        self._write_status(
            f"[bold]System Info[/bold]\n"
            f"User: {self.user}\n"
            f"Role: {self.role}\n"
            f"Verbose: {'on' if self.verbose else 'off'}"
        )
        # Focus the input
        self.query_one("#chat-input", Input).focus()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return

        # Save to history
        self._command_history.append(text)
        self._history_index = -1

        if self._pipeline_running:
            self._write_chat("[yellow]Pipeline is running, please wait...[/yellow]")
            return

        if text.startswith("/"):
            self._handle_command(text)
            return

        # Analysis prompt
        self._write_chat(f"[bold green]> {text}[/bold green]")
        self._clear_report()
        self._pipeline_running = True  # Set in main thread before worker starts
        self._run_pipeline(text)

    def on_key(self, event) -> None:
        """Handle up/down arrow for command history."""
        input_widget = self.query_one("#chat-input", Input)
        if not input_widget.has_focus:
            return

        if event.key == "up":
            if self._command_history and self._history_index < len(self._command_history) - 1:
                self._history_index += 1
                input_widget.value = self._command_history[-(self._history_index + 1)]
                input_widget.cursor_position = len(input_widget.value)
                event.prevent_default()
        elif event.key == "down":
            if self._history_index > 0:
                self._history_index -= 1
                input_widget.value = self._command_history[-(self._history_index + 1)]
                input_widget.cursor_position = len(input_widget.value)
                event.prevent_default()
            elif self._history_index == 0:
                self._history_index = -1
                input_widget.value = ""
                event.prevent_default()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Reset _running when pipeline worker finishes (success, error, or cancelled)."""
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._pipeline_running = False

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/help":
            self.action_show_help()
        elif cmd == "/clear":
            self.action_clear_panels()
        elif cmd == "/verbose":
            self.verbose = not self.verbose
            self._write_chat(f"Verbose mode: [bold]{'on' if self.verbose else 'off'}[/bold]")
        elif cmd == "/status":
            self._show_status()
        elif cmd == "/catalog":
            self._show_catalog(args)
        elif cmd == "/sql":
            if not args:
                self._write_chat("[yellow]Usage: /sql SELECT ...[/yellow]")
            else:
                self._run_sql(args)
        elif cmd == "/cancel":
            if self._pipeline_running:
                # Cancel all workers
                for worker in self.workers:
                    worker.cancel()
                self._pipeline_running = False
                self._write_chat("[yellow]Pipeline cancelled.[/yellow]")
            else:
                self._write_chat("[dim]No pipeline running.[/dim]")
        else:
            self._write_chat(f"[yellow]Unknown command: {cmd}. Type /help[/yellow]")

    # ------------------------------------------------------------------
    # Actions (key bindings)
    # ------------------------------------------------------------------

    def action_clear_panels(self) -> None:
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#report-log", RichLog).clear()
        self.query_one("#status-log", RichLog).clear()

    def action_show_help(self) -> None:
        self._write_chat(
            "[bold]Commands:[/bold]\n"
            "  /help       Show this help\n"
            "  /status     Token usage statistics\n"
            "  /catalog    List data catalog assets\n"
            "  /catalog <q> Search catalog\n"
            "  /sql <SQL>  Execute SQL query\n"
            "  /verbose    Toggle verbose mode\n"
            "  /cancel     Cancel running pipeline\n"
            "  /clear      Clear all panels\n"
            "  /quit       Exit TUI\n"
            "\n"
            "[bold]Shortcuts:[/bold]\n"
            "  Ctrl+Q  Quit\n"
            "  Ctrl+L  Clear panels\n"
            "  F1      Help\n"
            "  Up/Down Command history"
        )

    # ------------------------------------------------------------------
    # Panel helpers
    # ------------------------------------------------------------------

    def _write_chat(self, markup: str) -> None:
        """Write Rich-markup text to the chat panel."""
        log = self.query_one("#chat-log", RichLog)
        log.write(Text.from_markup(markup))

    def _write_status(self, markup: str) -> None:
        """Write Rich-markup text to the status panel."""
        log = self.query_one("#status-log", RichLog)
        log.write(Text.from_markup(markup))

    def _write_report(self, content) -> None:
        """Write a Rich renderable to the report panel."""
        log = self.query_one("#report-log", RichLog)
        log.write(content)

    def _clear_report(self) -> None:
        """Clear the report panel."""
        self.query_one("#report-log", RichLog).clear()

    # ------------------------------------------------------------------
    # Pipeline execution (threaded worker)
    # ------------------------------------------------------------------

    @work(exclusive=True, thread=True)
    def _run_pipeline(self, prompt: str) -> None:
        """Run analysis pipeline in a background thread."""
        self.call_from_thread(
            self._write_status,
            "[cyan]Classifying intent...[/cyan]"
        )

        try:
            self._run_pipeline_inner(prompt)
        except Exception as e:
            self.call_from_thread(
                self._write_chat,
                f"[red]Error: {e}[/red]"
            )
        finally:
            self._pipeline_running = False

    def _run_pipeline_inner(self, prompt: str) -> None:
        """Inner pipeline logic (runs in worker thread)."""
        # Lazy imports (same pattern as cli.py)
        from data_agent.cli import (
            _load_env, _set_user_context, _select_agent,
            _get_app_module, _get_session_service,
        )
        from data_agent.pipeline_runner import run_pipeline_headless
        from data_agent.user_context import current_tool_categories

        _load_env()
        session_id = _set_user_context(self.user, self.role)
        app_mod = _get_app_module()

        # Intent classification
        intent, reason, router_tokens, tool_cats = app_mod.classify_intent(
            prompt, self._previous_pipeline
        )
        self.call_from_thread(
            self._write_status,
            f"Intent: [bold]{intent}[/bold] ({reason})"
        )

        # RBAC check
        if self.role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
            self.call_from_thread(
                self._write_chat,
                f"[red]Access denied: role '{self.role}' cannot use {intent} pipeline[/red]"
            )
            return

        agent, pipeline_type = _select_agent(app_mod, intent)
        current_tool_categories.set(tool_cats)

        # Build prompt with router hint for planner
        dynamic_planner = getattr(app_mod, "DYNAMIC_PLANNER", False)
        full_prompt = prompt
        if dynamic_planner:
            full_prompt = prompt + f"\n\n[意图分类提示] 路由器判断: {intent}（{reason}）"

        # TUI always uses InMemorySessionService (no DB session needed)
        session_service = _get_session_service()

        # on_event callback → push to TUI panels via call_from_thread
        def tui_event_callback(event: dict):
            etype = event.get("type")
            if etype == "agent":
                self.call_from_thread(
                    self._write_status,
                    f"[dim cyan]Agent: {event['name']}[/dim cyan]"
                )
            elif etype == "tool_call":
                self.call_from_thread(
                    self._write_status,
                    f"[dim]>> {event['name']}()[/dim]"
                )
            elif etype == "tool_result":
                summary = event.get("summary", "")[:80]
                icon = "[green]ok[/green]"
                self.call_from_thread(
                    self._write_status,
                    f"[dim]   #{event['step']} {icon} {summary}[/dim]"
                )
            elif etype == "text":
                self.call_from_thread(
                    self._write_report, event["content"]
                )

        self.call_from_thread(
            self._write_status,
            f"[bold green]Running {pipeline_type} pipeline...[/bold green]"
        )

        # Run async pipeline from sync thread
        result = asyncio.run(run_pipeline_headless(
            agent=agent,
            session_service=session_service,
            user_id=self.user,
            session_id=session_id,
            prompt=full_prompt,
            pipeline_type=pipeline_type,
            intent=intent,
            router_tokens=router_tokens,
            use_dynamic_planner=dynamic_planner,
            role=self.role,
            on_event=tui_event_callback if self.verbose else None,
        ))

        # Render final result
        self.call_from_thread(self._render_pipeline_result, result)
        self._previous_pipeline = pipeline_type

        # Record token usage (non-fatal)
        try:
            from data_agent.token_tracker import record_usage
            tracking_type = pipeline_type
            if dynamic_planner and pipeline_type == "planner":
                tracking_type = intent.lower() if intent != "AMBIGUOUS" else "general"
            record_usage(
                self.user, tracking_type,
                result.total_input_tokens, result.total_output_tokens,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------

    def _render_pipeline_result(self, result) -> None:
        """Render PipelineResult to report and status panels."""
        report_log = self.query_one("#report-log", RichLog)
        report_log.clear()

        if result.error:
            report_log.write(Panel(
                Text.from_markup(f"[red bold]Error:[/red bold] {result.error}"),
                title="Pipeline Error", border_style="red",
            ))
            self._write_chat("[red]Pipeline failed.[/red]")
            return

        # Markdown report
        report = result.report_text or "(no output)"
        if len(report) > 5000:
            report = report[:5000] + "\n... (truncated)"
        try:
            report_log.write(Panel(Markdown(report), title="Analysis Report",
                                   border_style="green"))
        except Exception:
            report_log.write(Panel(report, title="Analysis Report",
                                   border_style="green"))

        # Generated files
        if result.generated_files:
            report_log.write(Text.from_markup("\n[bold]Generated Files:[/bold]"))
            for f in result.generated_files:
                report_log.write(Text.from_markup(f"  {f}"))

        # Tool execution log (verbose)
        if self.verbose and result.tool_execution_log:
            table = Table(title="Tool Execution Log", show_lines=True)
            table.add_column("#", width=4)
            table.add_column("Agent", max_width=18)
            table.add_column("Tool", max_width=22)
            table.add_column("Dur", width=6)
            table.add_column("Result", max_width=30)
            for entry in result.tool_execution_log:
                dur = f"{entry.get('duration', 0):.1f}s"
                status = "[red]ERR[/red]" if entry.get("is_error") else "[green]ok[/green]"
                table.add_row(
                    str(entry["step"]),
                    entry.get("agent_name", ""),
                    entry["tool_name"],
                    dur,
                    f"{status} {entry.get('result_summary', '')[:25]}",
                )
            self.query_one("#status-log", RichLog).write(table)

        # Stats line
        self._write_status(
            f"[dim]Pipeline: {result.pipeline_type} | "
            f"Duration: {result.duration_seconds:.1f}s | "
            f"Tokens: {result.total_input_tokens}in/{result.total_output_tokens}out[/dim]"
        )
        self._write_chat("[green]Analysis complete.[/green]")

    # ------------------------------------------------------------------
    # /status command
    # ------------------------------------------------------------------

    def _show_status(self) -> None:
        """Show token usage in status panel."""
        try:
            from data_agent.cli import _load_env, _set_user_context
            _load_env()
            _set_user_context(self.user, self.role)

            from data_agent.token_tracker import (
                get_daily_usage, get_monthly_usage, get_pipeline_breakdown,
            )

            daily = get_daily_usage(self.user)
            monthly = get_monthly_usage(self.user)

            table = Table(title="Token Usage")
            table.add_column("Period", width=12)
            table.add_column("Requests", width=10, justify="right")
            table.add_column("Tokens", width=12, justify="right")
            table.add_row(
                "Today",
                str(daily.get("count", 0)),
                f"{daily.get('tokens', 0):,}",
            )
            table.add_row(
                "This month",
                str(monthly.get("count", 0)),
                f"{monthly.get('total_tokens', 0):,}",
            )

            status_log = self.query_one("#status-log", RichLog)
            status_log.write(table)

            # Pipeline breakdown
            breakdown = get_pipeline_breakdown(self.user)
            if breakdown:
                bd_table = Table(title="Pipeline Breakdown")
                bd_table.add_column("Pipeline", width=14)
                bd_table.add_column("Count", width=8, justify="right")
                bd_table.add_column("Tokens", width=12, justify="right")
                for row in breakdown:
                    bd_table.add_row(
                        row.get("pipeline_type", ""),
                        str(row.get("count", 0)),
                        f"{row.get('tokens', 0):,}",
                    )
                status_log.write(bd_table)

        except Exception as e:
            self._write_status(f"[red]Error loading status: {e}[/red]")

    # ------------------------------------------------------------------
    # /catalog command
    # ------------------------------------------------------------------

    def _show_catalog(self, args: str) -> None:
        """List or search data catalog."""
        try:
            from data_agent.cli import _load_env, _set_user_context
            _load_env()
            _set_user_context(self.user, self.role)

            report_log = self.query_one("#report-log", RichLog)
            report_log.clear()

            if args:
                # Search mode
                from data_agent.data_catalog import search_data_assets
                result = search_data_assets(args)
                if isinstance(result, str):
                    report_log.write(Text.from_markup(f"[red]{result}[/red]"))
                    return
                if result.get("status") == "error":
                    report_log.write(Text.from_markup(
                        f"[red]Error: {result.get('message', '')}[/red]"
                    ))
                    return
                assets = result.get("assets", [])
                title = f"Search: '{args}' ({len(assets)} results)"
            else:
                # List mode
                from data_agent.data_catalog import list_data_assets
                result = list_data_assets()
                if result.get("status") == "error":
                    report_log.write(Text.from_markup(
                        f"[red]Error: {result.get('message', '')}[/red]"
                    ))
                    return
                assets = result.get("assets", [])
                title = f"Data Catalog ({result.get('count', len(assets))} assets)"

            if not assets:
                report_log.write(Text.from_markup("[yellow]No assets found.[/yellow]"))
                return

            table = Table(title=title)
            table.add_column("ID", width=4)
            table.add_column("Name", max_width=28)
            table.add_column("Type", width=10)
            table.add_column("Description", max_width=40)
            for a in assets:
                table.add_row(
                    str(a.get("id", "")),
                    a.get("name", ""),
                    a.get("type", ""),
                    (a.get("description") or "")[:40],
                )
            report_log.write(table)

        except Exception as e:
            self._write_chat(f"[red]Catalog error: {e}[/red]")

    # ------------------------------------------------------------------
    # /sql command
    # ------------------------------------------------------------------

    def _run_sql(self, query: str) -> None:
        """Execute a read-only SQL query."""
        try:
            from data_agent.cli import _load_env, _set_user_context
            _load_env()
            _set_user_context(self.user, self.role)

            from data_agent.database_tools import query_database
            result = query_database(query)

            report_log = self.query_one("#report-log", RichLog)
            report_log.clear()

            if result.get("status") == "error":
                report_log.write(Text.from_markup(
                    f"[red]Error: {result.get('message', 'Query failed')}[/red]"
                ))
                return

            report_log.write(Text.from_markup(
                f"[green]{result.get('message', 'OK')}[/green]"
            ))

            # Render CSV as table
            output_path = result.get("output_path", "")
            if output_path and os.path.exists(output_path) and output_path.endswith(".csv"):
                try:
                    import pandas as pd
                    df = pd.read_csv(output_path, nrows=50)
                    table = Table(
                        title=f"Query Results ({result.get('record_count', len(df))} rows)"
                    )
                    for col in df.columns:
                        table.add_column(str(col), max_width=25)
                    for _, row in df.iterrows():
                        table.add_row(*[str(v)[:25] for v in row])
                    report_log.write(table)
                except Exception:
                    report_log.write(Text.from_markup(
                        f"[dim]Output: {output_path}[/dim]"
                    ))
            elif output_path:
                report_log.write(Text.from_markup(
                    f"[dim]Output: {output_path}[/dim]"
                ))

        except Exception as e:
            self._write_chat(f"[red]SQL error: {e}[/red]")
