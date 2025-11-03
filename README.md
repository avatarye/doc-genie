# Doc Genie

A CLI tool for syncing documents across **Obsidian**, **Notion**, and **Quip** with robust media file handling.

## Features

- **Bidirectional sync**: Obsidian ↔ Notion ↔ Quip
- **Media support**: Images, videos (inline players), PDFs
- **Smart deduplication**: SHA256 hash tracking prevents re-uploading unchanged files
- **Per-file state**: `.dg` files enable cross-machine sync via Dropbox
- **Backlink preservation**: Automatically updates external Quip links when recreating documents
- **Named routes**: Pre-configured sync paths for different document collections

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/doc-genie.git
cd doc-genie

# Install with uv
uv sync

# Install in editable mode for development
uv pip install -e .
```

## Quick Start

### 1. Initialize credentials

```bash
dg init
```

You'll be prompted for:
- Notion API token
- Quip API token
- Quip base URL (e.g., `https://quip-amazon.com`)

### 2. Add a sync route

```bash
dg route-add my-docs
```

Provide:
- Description
- Source path (Obsidian vault directory or single file)
- Notion database ID
- Quip folder ID

### 3. Sync a document

```bash
# Forward sync: Obsidian → Notion → Quip
dg sync path/to/document.md -r my-docs

# Reverse sync: Quip → Notion → Obsidian (not yet implemented)
dg sync path/to/document.md -r my-docs -d reverse
```

## Commands

```bash
dg init                    # Initialize credentials
dg route-add <name>        # Add named sync route
dg route-list              # List all routes
dg route-remove <name>     # Remove a route
dg sync <file> -r <route>  # Sync document
dg status <file>           # Check sync status
dg config-show             # Show configuration
```

## How It Works

### Sync Flow

**Forward (Obsidian → Quip):**
1. Read markdown from Obsidian vault
2. Extract media files (supports `![[image.png]]` and `![](image.png)`)
3. Upload media to Notion (check cache first via SHA256 hash)
4. Convert markdown → Notion blocks
5. Create/update Notion page
6. Upload media to Quip
7. Convert Notion blocks → Quip HTML (with inline video players)
8. Create new Quip document → Delete old → Update backlinks

### State Management

Doc Genie uses **per-file `.dg` state files** stored next to each markdown file:

```
MyDocument.md
MyDocument.md.dg  # State file (JSON)
```

This approach enables:
- Cross-machine sync via Dropbox
- Media deduplication (tracks SHA256 hashes)
- Platform ID preservation (Notion page_id, Quip thread_id)

### Configuration Files

**`~/.doc_genie/config.toml`** - User credentials and routes:
```toml
[credentials.notion]
api_token = "secret_..."

[credentials.quip]
api_token = "abc123..."
base_url = "https://quip-amazon.com"

[routes.my-docs]
name = "my-docs"
description = "My documentation"
source = "/Users/me/Dropbox/Obsidian/Docs"
notion_database = "abc123..."
quip_folder = "xyz789..."
```

## Supported Media Formats

- **Images**: PNG, JPG, GIF, SVG (inline display)
- **Videos**: MP4, MOV, AVI (inline player with thumbnail)
- **Documents**: PDF (link)

## Limitations

- Reverse sync (Quip → Obsidian) not yet implemented
- No merge conflict resolution (always overwrites)
- Tables may not render perfectly in Quip
- Files >20MB require multi-part upload (not yet implemented)

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for implementation details and architecture.

## License

MIT

## Acknowledgments

- Uses official [Quip Python API](https://github.com/quip/quip-api) (Apache 2.0)
- Built with [Click](https://click.palletsprojects.com/), [Rich](https://rich.readthedocs.io/), and [Loguru](https://loguru.readthedocs.io/)
