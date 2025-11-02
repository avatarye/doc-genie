# Doc Genie - Project Context for Claude

## Project Overview

**Doc Genie** is a CLI tool for bidirectional document synchronization across three platforms:
- **Obsidian** (local markdown files in Dropbox)
- **Notion** (personal database)
- **Quip** (Amazon's internal Quip server)

**Key Design Principle**: Bidirectional sync along a fixed route: `Obsidian ↔ Notion ↔ Quip`

## Why This Tool Exists

Existing sync tools don't handle embedded media files (images, videos) well. This tool focuses on:
- Robust media file handling (upload to Notion and Quip)
- Support for both Obsidian wikilink syntax `![[image.png]]` and standard markdown `![](image.png)`
- Named sync routes for organizing different document collections
- Simple overwrites - no complex merge logic

## Architecture Decisions

### 1. Bidirectional Sync Route
- Same route works both directions: Obsidian → Notion → Quip AND Quip → Notion → Obsidian
- User specifies direction in CLI
- Each platform can be source or destination

### 2. Named Routes
Routes are pre-configured sync paths stored in `~/.doc_genie/config.toml`:
```toml
[routes.work-docs]
name = "work-docs"
source = "/Users/yongye/Dropbox/Obsidian/Work"  # Can be file or directory
notion_database = "abc123"
quip_folder = "xyz789"
```

### 3. No Complex Conflict Resolution
- Always complete overwrite of destination
- No merge logic, no diff tracking
- User responsible for not editing same doc on multiple platforms
- Simple timestamp tracking for awareness

### 4. Conversion Flow
**Obsidian → Notion → Quip:**
- Markdown → Notion blocks → Quip HTML

**Quip → Notion → Obsidian:**
- Quip HTML → Notion blocks → Markdown

Why through Notion? Table compatibility issues (Obsidian tables work in Notion, but not directly in Quip).

## Project Structure

```
doc-genie/
├── src/
│   └── doc_genie/
│       ├── cli.py                    # CLI commands (Click + Rich + Loguru)
│       ├── config.py                 # Manage ~/.doc_genie/config.toml
│       ├── state.py                  # Manage ~/.doc_genie/state.json
│       ├── document.py               # Document model
│       ├── media.py                  # Media extraction & upload
│       ├── converter.py              # Format conversions (MD ↔ Notion ↔ HTML)
│       ├── sync_engine.py            # Main sync orchestration
│       ├── platforms/
│       │   ├── obsidian.py          # Read/write .md files
│       │   ├── notion_client.py     # Notion API wrapper
│       │   └── quip_client.py       # Quip API wrapper
│       └── quip_api/                # Migrated from VitDtQuipTools
│           ├── __init__.py
│           └── quip.py              # Official Quip Python API
├── pyproject.toml
├── CLAUDE.md                         # This file
└── DEVELOPMENT.md                    # Implementation plan
```

## Key Files

### ~/.doc_genie/config.toml
User-managed configuration:
- Platform credentials (not encrypted - personal use only)
- Named sync routes (source paths, target database/folder IDs)

### ~/.doc_genie/state.json
Auto-managed sync state:
- Tracks which documents synced to which platforms
- Stores platform IDs (notion_page_id, quip_thread_id)
- Media file mappings (URLs/blob IDs)
- Last sync timestamps

## Technology Stack

- **Python**: 3.11+ (3.11/3.12/3.13)
- **Package Manager**: uv (fast Python package installer and resolver)
- **CLI Framework**: Click (command-line interface)
- **CLI Output**: Rich (formatted/colored terminal output)
- **Logging**: Loguru (structured logging with auto-formatting)
- **Config**: TOML parsing
- **Notion API**: `notion-client` official SDK
- **Quip API**: Migrated from VitDtQuipTools (official Quip Python API)
- **Markdown Parsing**: `mistune`
- **HTML Parsing**: BeautifulSoup4
- **HTML↔Markdown**: `markdownify`

## Markdown Feature Support

**Essential features only:**
- Headings (# ## ###)
- Paragraphs
- Lists (bulleted and numbered)
- Images
- Tables
- Code blocks
- Bold/italic

**Not prioritized:**
- Advanced Obsidian features (dataview, templates, etc.)
- Complex nested structures
- Mermaid diagrams

## Media Handling

### Obsidian
- Two link syntaxes: `![[image.png]]` (wikilink) and `![](image.png)` (standard)
- Media files stored in vault directory
- Need to resolve relative paths

### Notion
- New file upload API (May 2025)
- Files <20MB: single upload
- Files >20MB: multi-part upload
- Files expire after 1 hour, must be attached within that window
- Returns hosted URL

### Quip
- Use `put_blob()` API from official Quip client
- Upload to thread, get blob ID
- Reference in HTML as `<img src="blob-url">`

## Sync Behavior

### Direction: Obsidian → Notion → Quip
1. Read markdown from Obsidian
2. Extract media files (both link types)
3. Upload media to Notion, get URLs
4. Convert markdown → Notion blocks (with media URLs)
5. Create/update Notion page
6. Fetch Notion blocks
7. Upload media to Quip, get blob IDs
8. Convert Notion blocks → Quip HTML (with blob references)
9. Create/update Quip document

### Direction: Quip → Notion → Obsidian
1. Fetch Quip document HTML
2. Download Quip media blobs
3. Convert Quip HTML → Notion blocks
4. Create/update Notion page
5. Fetch Notion blocks
6. Download Notion media files
7. Convert Notion blocks → Markdown
8. Save markdown to Obsidian vault
9. Save media files to vault media directory

### Create vs Update
No distinction - always complete overwrite:
- If document exists in state: update existing platform IDs
- If document doesn't exist: create new, save IDs to state

## CLI Commands

```bash
# Setup
doc-genie init                              # Initialize credentials
doc-genie route-add work-docs               # Add named route

# Sync (bidirectional)
doc-genie sync document.md --route work-docs --direction forward   # Obsidian → Quip
doc-genie sync document.md --route work-docs --direction reverse   # Quip → Obsidian
doc-genie sync document.md -r work-docs -d forward                 # Short form

# Management
doc-genie status document.md --route work-docs    # Check sync status
doc-genie route-list                              # List all routes
doc-genie config-show                             # Show config (masked credentials)
doc-genie route-remove old-route                  # Remove route
```

## Important Notes for Implementation

### 1. Quip API Migration
- Copy `/Users/yongye/TechDepot/DT_Packages/VitDtQuipTools/src/vit_dt_quip_tools/quip_api/` to this project
- Keep it unchanged (Apache 2.0 license)
- Reference implementation patterns from VitDtQuipTools:
  - `document.py`: HTML ↔ Markdown conversion with BeautifulSoup + markdownify
  - `manager.py`: Async requests with semaphore for rate limiting
  - `quip.py`: Blob upload/download methods

### 2. Path Handling
- Routes can specify file OR directory
- For directories: recursive scan for .md files
- Track relative paths within route for state management
- Validate file belongs to route before syncing

### 3. Media Path Resolution
- Obsidian wikilinks: `![[image.png]]` searches vault
- Standard markdown: `![](./images/image.png)` relative to document
- Need to handle both and normalize to absolute paths

### 4. Error Handling
- Personal tool - simple error messages, no complex retry logic
- If media upload fails, fail the whole sync (don't partial sync)
- Log errors with Rich console formatting

### 5. State Management
- State is per-route, per-document
- Store minimal info: IDs, timestamps, hashes
- Don't cache content - always read from source

## Reference Code Locations

**VitDtQuipTools** (reference only, don't modify):
- Location: `/Users/yongye/TechDepot/DT_Packages/VitDtQuipTools`
- Key files:
  - `src/vit_dt_quip_tools/quip_api/quip.py` - Official Quip API
  - `src/vit_dt_quip_tools/document.py` - Document model with conversion
  - `src/vit_dt_quip_tools/manager.py` - Async patterns
  - `README.md` - API usage examples

## Current Working Directory
`/Users/yongye/TechDepot/LHY_Packages/BeagleSimBlenderUsdManager`

Note: The project should be in its own directory, not BeagleSimBlenderUsdManager.

## User Preferences
- Simple, pragmatic solutions over over-engineering
- No complex rate limiting logic
- No encryption for credentials (personal use)
- Focus on robustness for updates (frequent use case)
- Handle both Obsidian link types transparently
- Rich CLI output with progress indicators

## Known Limitations
- No merge conflict resolution
- No partial syncs
- No undo functionality
- Tables may not work perfectly in Quip (known issue)
- User must manage not editing same doc on multiple platforms

## Next Steps
See DEVELOPMENT.md for implementation plan and task breakdown.
