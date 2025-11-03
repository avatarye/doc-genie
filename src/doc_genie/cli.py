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
@click.option('--no-quip', is_flag=True, help='Skip Quip sync (Obsidian → Notion only)')
def sync(filepath, route, no_quip):
    """
    Sync document from Obsidian to Notion (and optionally Quip)

    Examples:
        dg sync document.md -r work-docs
        dg sync document.md  # Uses default route
        dg sync document.md --no-quip  # Skip Quip, sync to Notion only
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
            result = engine.sync(filepath, route, direction='forward', skip_quip=no_quip)
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
@click.argument('filepath', type=click.Path())
@click.option('--route', '-r', help='Named route to use (uses default if not specified)')
@click.option('--no-notion', is_flag=True, help='Skip Notion sync (Quip → Obsidian only)')
def rsync(filepath, route, no_notion):
    """
    Reverse sync: Download document from Quip/Notion to Obsidian

    Searches for document by title in Quip first, then Notion.
    If found in Quip: Downloads to Obsidian, then syncs to Notion (unless --no-notion).
    If found in Notion: Downloads to Obsidian only.

    Examples:
        dg rsync DocumentName.md -r work-docs
        dg rsync DocumentName.md  # Uses default route
        dg rsync DocumentName.md --no-notion  # Quip to Obsidian only
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
                console.print("  Or: [cyan]dg rsync <file> -r <route>[/cyan]")
                raise click.Abort()

        # Resolve filepath
        filepath = Path(filepath)
        if not filepath.is_absolute():
            # Get route to resolve relative paths
            route_config = config.get_route(route)
            if not route_config:
                console.print(f"[red]✗ Route not found: {route}[/red]")
                raise click.Abort()

            # For reverse sync, filepath might not exist yet
            # Resolve relative to route's source directory
            filepath = (Path(route_config.source) / filepath).resolve()

        # Use Progress with transient=True
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task(f"Reverse syncing {filepath.name}...", total=None)
            result = engine.sync(filepath, route, direction='reverse', skip_notion=no_notion)
            progress.update(task, completed=True)

        if result.success:
            if result.media_count > 0:
                console.print(f"  [dim]Media: {result.media_count} files[/dim]")
        else:
            console.print(f"\n[red]✗ Reverse sync failed: {result.error}[/red]")

    except Exception as e:
        logger.exception("Reverse sync failed: {}", e)
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


@cli.command()
@click.argument('folder_id')
def quip_list(folder_id):
    """List documents in a Quip folder (performance test)"""
    config = Config()
    creds = config.get_credentials()

    if not creds.quip_token:
        console.print("[red]✗ Quip token not configured. Run 'dg init' first.[/red]")
        raise click.Abort()

    try:
        import time
        from doc_genie.quip_api import QuipAPI

        quip_api = QuipAPI(access_token=creds.quip_token, base_url=creds.quip_base_url)

        console.print(f"[blue]Listing documents in folder: {folder_id}[/blue]\n")

        # Time the folder fetch
        start_time = time.time()
        folder = quip_api.get_folder(folder_id)
        fetch_time = time.time() - start_time

        console.print(f"[green]✓ Folder fetched in {fetch_time:.3f}s[/green]\n")

        # Show folder info
        folder_info = folder.get('folder', {})
        console.print(f"[cyan]Folder: {folder_info.get('title', 'Unknown')}[/cyan]")

        children = folder.get('children', [])
        console.print(f"[cyan]Total items: {len(children)}[/cyan]\n")

        # Collect thread IDs for batch fetch
        thread_ids = [child['thread_id'] for child in children if child.get('thread_id')]

        # Batch fetch thread details for title lookup
        threads_data = {}
        fetch_details_time = 0
        if thread_ids:
            console.print(f"[yellow]Fetching details for {len(thread_ids)} documents...[/yellow]")
            start_fetch = time.time()
            threads_data = quip_api.get_threads(thread_ids[:100])  # Limit to 100 for performance test
            fetch_details_time = time.time() - start_fetch
            console.print(f"[green]✓ Thread details fetched in {fetch_details_time:.3f}s[/green]\n")

        # Create table of documents
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Title", style="green", width=50)
        table.add_column("Thread ID", style="yellow")
        table.add_column("Type", style="blue")

        doc_count = 0
        folder_count = 0

        for child in children[:50]:  # Limit to first 50 for display
            if child.get('thread_id'):
                # It's a document
                thread_id = child['thread_id']
                thread_info = threads_data.get(thread_id, {})
                title = thread_info.get('thread', {}).get('title', 'Untitled')
                table.add_row(title, thread_id, 'document')
                doc_count += 1
            elif child.get('folder_id'):
                # It's a subfolder
                folder_id_child = child['folder_id']
                title = child.get('folder', {}).get('title', 'Untitled')
                table.add_row(f"📁 {title}", folder_id_child, 'folder')
                folder_count += 1

        console.print(table)

        if len(children) > 50:
            console.print(f"\n[dim]Showing first 50 of {len(children)} items[/dim]")

        console.print(f"\n[cyan]Documents: {doc_count}[/cyan]")
        console.print(f"[cyan]Folders: {folder_count}[/cyan]")

        total_time = fetch_time + fetch_details_time
        console.print(f"\n[yellow]Performance:[/yellow]")
        console.print(f"  Folder list: {fetch_time:.3f}s")
        console.print(f"  Thread details: {fetch_details_time:.3f}s ({len(thread_ids)}/batch)")
        console.print(f"  Total: {total_time:.3f}s for {len(children)} items")

    except Exception as e:
        logger.exception("Failed to list folder: {}", e)
        console.print(f"[red]✗ Failed to list folder: {e}[/red]")
        raise click.Abort()


@cli.command()
def quip_test():
    """Test Quip API connectivity"""
    config = Config()
    creds = config.get_credentials()

    if not creds.quip_token:
        console.print("[red]✗ Quip token not configured. Run 'dg init' first.[/red]")
        raise click.Abort()

    try:
        import urllib.request
        import urllib.error

        base_url = creds.quip_base_url
        token = creds.quip_token

        # Test URL that the API client constructs
        test_url = f"{base_url}/1/users/current"

        console.print("[blue]Testing Quip API connectivity...[/blue]\n")
        console.print(f"[dim]Base URL: {base_url}[/dim]")
        console.print(f"[dim]Test endpoint: {test_url}[/dim]")
        console.print(f"[dim]Token: {token[:20]}...[/dim]\n")

        # Make request with authentication
        request = urllib.request.Request(test_url)
        request.add_header("Authorization", f"Bearer {token}")

        try:
            console.print("[yellow]Sending request...[/yellow]")
            response = urllib.request.urlopen(request, timeout=10)
            data = response.read().decode('utf-8')

            console.print("[green]✓ Connection successful![/green]\n")

            import json
            user_data = json.loads(data)
            console.print(f"[cyan]User: {user_data.get('name', 'Unknown')}[/cyan]")
            console.print(f"[cyan]Email: {user_data.get('email', 'Unknown')}[/cyan]")
            console.print(f"[cyan]User ID: {user_data.get('id', 'Unknown')}[/cyan]")

        except urllib.error.HTTPError as e:
            console.print(f"[red]✗ HTTP Error {e.code}: {e.reason}[/red]\n")
            console.print("[yellow]Try these alternatives:[/yellow]")

            # Try alternative API paths
            alternatives = [
                f"{base_url}/api/1/users/current",
                f"{base_url}/api/users/current",
                f"{base_url}/1/users/current",
            ]

            for alt_url in alternatives:
                console.print(f"  • {alt_url}")

            console.print("\n[dim]You can test these URLs in your browser with the token in dev tools[/dim]")
            raise

    except Exception as e:
        console.print(f"[red]✗ Connection failed: {e}[/red]")
        raise click.Abort()


@cli.command()
@click.option('--debug', is_flag=True, help='Show raw user data for debugging')
def quip_folders(debug):
    """List your Quip folders to find folder IDs"""
    config = Config()
    creds = config.get_credentials()

    if not creds.quip_token:
        console.print("[red]✗ Quip token not configured. Run 'dg init' first.[/red]")
        raise click.Abort()

    try:
        from doc_genie.platforms.quip_client import QuipClient
        from doc_genie.quip_api import QuipAPI

        # Show connection info
        console.print(f"[dim]Connecting to: {creds.quip_base_url}[/dim]")
        console.print(f"[dim]Token: {creds.quip_token[:20]}...[/dim]\n")

        quip_api = QuipAPI(access_token=creds.quip_token, base_url=creds.quip_base_url)

        # Get authenticated user to find folder IDs
        console.print("[blue]Fetching your Quip folders...[/blue]\n")
        try:
            user = quip_api.get_authenticated_user()
        except Exception as e:
            console.print(f"[red]✗ Failed to connect to Quip API[/red]")
            console.print(f"[yellow]Error: {e}[/yellow]")
            console.print(f"\n[dim]Possible issues:[/dim]")
            console.print(f"  • Check if base_url is correct: {creds.quip_base_url}")
            console.print(f"  • Check if API token is valid")
            console.print(f"  • Check if Quip server is accessible")
            console.print(f"  • Try accessing {creds.quip_base_url}/api/users/current in browser")
            raise

        # Debug mode: show raw user data
        if debug:
            import json
            console.print("[yellow]Raw user data:[/yellow]")
            console.print(json.dumps(user, indent=2))
            return

        # Create a table to display folders
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Folder Name", style="green", width=40)
        table.add_column("Folder ID", style="yellow")
        table.add_column("Type", style="blue")

        # Helper to safely get folder
        def add_folder_row(name, folder_id, folder_type):
            try:
                folder = quip_api.get_folder(folder_id)
                table.add_row(name, folder_id, folder_type)
                return folder
            except Exception as e:
                logger.debug(f"Could not fetch folder {folder_id}: {e}")
                return None

        # Add starred folder
        if user.get("starred_folder_id"):
            add_folder_row("⭐ Starred", user["starred_folder_id"], "starred")

        # Add private folder and its children
        private_folder = None
        if user.get("private_folder_id"):
            private_folder = add_folder_row("🔒 Private", user["private_folder_id"], "private")

        # Add desktop folder and its children
        desktop_folder = None
        if user.get("desktop_folder_id"):
            desktop_folder = add_folder_row("💻 Desktop", user["desktop_folder_id"], "desktop")

        # Add archive folder
        if user.get("archive_folder_id"):
            add_folder_row("📦 Archive", user["archive_folder_id"], "archive")

        # List children of folders
        for parent_folder, parent_name in [(private_folder, "Private"), (desktop_folder, "Desktop")]:
            if parent_folder and parent_folder.get("children"):
                for child in parent_folder["children"]:
                    if child.get("folder_id"):
                        try:
                            child_folder = quip_api.get_folder(child["folder_id"])
                            title = child_folder.get("folder", {}).get("title", "Untitled")
                            table.add_row(f"  └─ {title}", child["folder_id"], f"{parent_name.lower()}/group")
                        except Exception as e:
                            logger.debug(f"Could not fetch child folder {child['folder_id']}: {e}")

        console.print(table)
        console.print("\n[green]✓ Use the Folder ID when configuring routes[/green]")
        console.print("\n[dim]Tip: Your private groups are usually in the Private or Desktop folders[/dim]")

    except Exception as e:
        logger.exception("Failed to list Quip folders: {}", e)
        console.print(f"[red]✗ Failed to list folders: {e}[/red]")
        raise click.Abort()


if __name__ == '__main__':
    cli()
