"""Command-line interface for Doc Genie."""

import sys
import click
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.logging import RichHandler

from doc_genie.config import Config, Route
from doc_genie.state import State
from doc_genie.sync_engine import SyncEngine

console = Console()

# Configure loguru with RichHandler for proper integration with Rich Progress
# Use custom sink to color-code log levels
logger.remove()  # Remove default handler

def custom_rich_sink(message):
    """Custom loguru sink with color-coded levels."""
    record = message.record
    level = record["level"].name
    time = record["time"].strftime("%H:%M:%S")
    msg = record["message"]

    # Color map for different levels
    level_colors = {
        "DEBUG": "dim",
        "INFO": "blue",
        "SUCCESS": "green",
        "WARNING": "yellow",
        "ERROR": "red bold",
    }

    color = level_colors.get(level, "white")
    formatted = f"[green]{time}[/green] | [{color}]{level: <8}[/{color}] | {msg}"
    console.print(formatted, highlight=False)

logger.add(custom_rich_sink, level="INFO")

# Add file logging
LOG_DIR = Path.home() / ".doc_genie" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    LOG_DIR / "doc_genie_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def cli(verbose):
    """dg - Bidirectional document sync for Obsidian, Notion, and Quip"""
    if verbose:
        logger.remove()
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level="DEBUG"
        )
        logger.debug("Verbose logging enabled")


@cli.command()
def init():
    """Initialize configuration with credentials"""
    console.print("[bold cyan]Doc Genie Setup[/bold cyan]\n")

    config = Config()

    console.print("[blue]Enter Notion credentials:[/blue]")
    notion_token = click.prompt("Notion API token", hide_input=True)

    # For now, we're only implementing Obsidian → Notion
    # Quip credentials can be added later
    config.save_credentials(notion_token=notion_token)

    console.print("\n[green]✓ Configuration saved to ~/.doc_genie/config.toml[/green]")
    console.print("\n[yellow]Note: Quip integration not yet implemented[/yellow]")


@cli.command()
@click.argument('route_name')
def route_add(route_name):
    """Add a new sync route interactively"""
    config = Config()

    console.print(f"[bold]Adding route: {route_name}[/bold]\n")

    description = click.prompt("Description")
    source = click.prompt("Source path (file or directory)", type=click.Path(exists=True))
    notion_db = click.prompt("Notion database ID")

    route = Route(
        name=route_name,
        description=description,
        source=str(Path(source).resolve()),
        notion_database=notion_db,
        quip_folder="",  # Not used yet
        enabled=True
    )

    config.add_route(route)
    console.print(f"\n[green]✓ Route '{route_name}' added![/green]")


@cli.command()
def route_list():
    """List all configured routes"""
    config = Config()
    routes = config.list_routes()

    if not routes:
        console.print("[yellow]No routes configured. Use 'route-add' to create one.[/yellow]")
        return

    table = Table(title="Configured Routes")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Source", style="blue")
    table.add_column("Enabled", style="green")

    for route in routes:
        table.add_row(
            route.name,
            route.description,
            route.source,
            "✓" if route.enabled else "✗"
        )

    console.print(table)


@cli.command()
@click.argument('route_name')
def route_remove(route_name):
    """Remove a sync route"""
    config = Config()
    if click.confirm(f"Remove route '{route_name}'?"):
        config.remove_route(route_name)
        console.print(f"[green]✓ Route '{route_name}' removed[/green]")


@cli.command()
@click.argument('route_name', required=False)
def route_default(route_name):
    """Set or show the default sync route

    Examples:
        dg route-default test-route   # Set test-route as default
        dg route-default               # Show current default
    """
    config = Config()

    if route_name:
        # Set default route
        try:
            config.set_default_route(route_name)
            console.print(f"[green]✓ Default route set to: {route_name}[/green]")
        except ValueError as e:
            console.print(f"[red]✗ {e}[/red]")
            raise click.Abort()
    else:
        # Show current default
        default = config.get_default_route()
        if default:
            console.print(f"Default route: [cyan]{default}[/cyan]")
        else:
            console.print("[yellow]No default route set[/yellow]")
            console.print("  Use: [cyan]dg route-default <route-name>[/cyan] to set one")


@cli.command()
def config_show():
    """Show current configuration (credentials masked)"""
    config = Config()

    if not config.exists():
        console.print("[yellow]No configuration found. Run 'dg init' first.[/yellow]")
        return

    console.print("[bold]Credentials:[/bold]")
    creds = config.get_credentials()

    if creds.notion_token:
        console.print(f"  Notion token: {creds.notion_token[:10]}...")
    else:
        console.print("  Notion: Not configured")

    console.print("\n[bold]Routes:[/bold]")
    routes = config.list_routes()
    default_route = config.get_default_route()
    if routes:
        for route in routes:
            default_marker = " [cyan](default)[/cyan]" if route.name == default_route else ""
            console.print(f"  • {route.name}: {route.source}{default_marker}")
    else:
        console.print("  No routes configured")


@cli.command()
@click.argument('filepath', type=click.Path())
@click.option('--route', '-r', help='Named route to use (uses default if not specified)')
def sync(filepath, route):
    """
    Sync document from Obsidian to Notion

    Examples:
        dg sync document.md -r work-docs
        dg sync document.md  # Uses default route
        dg sync /path/to/note.md --route personal
    """
    try:
        config = Config()
        state = State()
        engine = SyncEngine(config, state)

        # Use default route if not specified
        if not route:
            route = config.get_default_route()
            if not route:
                console.print("[red]✗ No route specified and no default route set[/red]")
                console.print("  Use: [cyan]dg route-default <route-name>[/cyan] to set a default")
                console.print("  Or: [cyan]dg sync <file> -r <route>[/cyan]")
                raise click.Abort()

        # Resolve filepath - if it's just a filename, look in route's source directory
        filepath = Path(filepath)
        if not filepath.is_absolute() and not filepath.exists():
            # Try to find it in the route's source directory
            route_config = config.get_route(route)
            if not route_config:
                console.print(f"[red]✗ Route not found: {route}[/red]")
                raise click.Abort()

            # Search in route's source directory
            possible_path = Path(route_config.source) / filepath
            if possible_path.exists():
                filepath = possible_path.resolve()
            else:
                console.print(f"[red]✗ File not found: {filepath}[/red]")
                console.print(f"  Searched in: {route_config.source}")
                raise click.Abort()
        else:
            filepath = filepath.resolve()

        # Final check that file exists
        if not filepath.exists():
            console.print(f"[red]✗ File not found: {filepath}[/red]")
            raise click.Abort()

        # Use Progress with transient=True so it doesn't interfere with logs
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True  # Progress disappears when done, logs remain
        ) as progress:
            task = progress.add_task(f"Syncing {filepath.name}...", total=None)
            result = engine.sync(filepath, route, direction='forward')
            progress.update(task, completed=True)

        if result.success:
            if result.media_count > 0:
                console.print(f"  [dim]Media: {result.media_count} files[/dim]")
        else:
            console.print(f"\n[red]✗ Sync failed: {result.error}[/red]")

    except Exception as e:
        logger.exception("Sync failed: {}", e)
        console.print(f"[red]✗ Error: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--route', '-r', help='Specific route (optional)')
def status(filepath, route):
    """Show sync status of a document"""
    state = State()
    config = Config()
    filepath = Path(filepath).resolve()

    if route:
        routes = [config.get_route(route)]
    else:
        routes = config.list_routes()

    found = False
    for r in routes:
        if not r:
            continue

        try:
            from doc_genie.platforms.obsidian import ObsidianClient
            obsidian = ObsidianClient(r.source_path)
            relative_path = obsidian.get_relative_path(filepath)
            doc_state = state.get_document(r.name, relative_path)

            if doc_state:
                found = True
                console.print(f"\n[bold]Route:[/bold] {r.name}")
                console.print(f"  File: {relative_path}")
                console.print(f"  Notion Page ID: {doc_state.notion_page_id}")
                console.print(f"  Last synced: {doc_state.last_synced}")
        except ValueError:
            continue

    if not found:
        console.print(f"[yellow]Document not synced in any route[/yellow]")


if __name__ == '__main__':
    cli()
