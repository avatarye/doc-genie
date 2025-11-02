# Doc Genie - Development Plan

## Implementation Overview

This document outlines the implementation plan for Doc Genie, a bidirectional document sync tool for Obsidian ↔ Notion ↔ Quip.

## Development Environment Setup

```bash
# Create project directory
mkdir -p ~/TechDepot/Github/doc-genie
cd ~/TechDepot/Github/doc-genie

# Initialize project with uv
uv init

# Install dependencies (uv will read from pyproject.toml)
uv sync

# Install with dev dependencies
uv sync --all-extras

# Setup project structure
mkdir -p src/doc_genie/platforms
mkdir -p src/doc_genie/quip_api
mkdir -p tests
```

## pyproject.toml Configuration

```toml
[project]
name = "doc-genie"
version = "0.1.0"
description = "Bidirectional document sync across Obsidian, Notion, and Quip"
authors = [
    {name = "Yongye"}
]
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "loguru>=0.7",
    "toml>=0.10",
    "notion-client>=2.0",  # Official Notion SDK
    "requests>=2.31",
    "beautifulsoup4>=4.12",
    "markdownify>=0.12",
    "mistune>=3.0",
    "lxml>=5.0",  # For BeautifulSoup
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "black>=24.0",
    "mypy>=1.8",
    "pytest-cov>=4.1",
]

[project.scripts]
doc-genie = "doc_genie.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/doc_genie"]
```

## Logging Configuration

Doc Genie uses **loguru** for clean, structured logging with minimal boilerplate.

**Key Features:**
- Automatic colorization for terminal output
- Structured logging with context
- Easy file logging for debugging
- No complex configuration needed

**Setup in `cli.py`:**
```python
from loguru import logger
import sys

# Configure logger
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)

# Add file logging for debug
logger.add(
    "~/.doc_genie/logs/doc_genie_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)
```

**Usage throughout the codebase:**
```python
from loguru import logger

logger.info("Syncing document: {}", filepath.name)
logger.debug("Media files found: {}", len(media_files))
logger.error("Failed to upload file: {}", error)
logger.success("Sync completed successfully")
```

## Implementation Tasks

### Task 1: Project Setup & Quip API Migration

**Files to create:**
- `src/doc_genie/__init__.py`
- `src/doc_genie/quip_api/__init__.py`
- `src/doc_genie/quip_api/quip.py`

**Steps:**
1. Create project structure
2. Copy Quip API from VitDtQuipTools:
   ```bash
   cp /Users/yongye/TechDepot/DT_Packages/VitDtQuipTools/src/vit_dt_quip_tools/quip_api/quip.py \
      src/doc_genie/quip_api/quip.py
   ```
3. Create `__init__.py` to expose QuipClient:
   ```python
   from .quip import QuipClient
   __all__ = ['QuipClient']
   ```
4. Test import works

**Validation:**
```python
from doc_genie.quip_api import QuipClient
# Should import without errors
```

---

### Task 2: Configuration Management

**File:** `src/doc_genie/config.py`

**Implementation:**
```python
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional
import toml

CONFIG_DIR = Path.home() / ".doc_genie"
CONFIG_FILE = CONFIG_DIR / "config.toml"

@dataclass
class Credentials:
    notion_token: str
    quip_token: str
    quip_base_url: str = "https://quip-amazon.com"

@dataclass
class Route:
    name: str
    description: str
    source: str  # Path as string
    notion_database: str
    quip_folder: str
    enabled: bool = True

    @property
    def source_path(self) -> Path:
        return Path(self.source).expanduser()

    def is_directory(self) -> bool:
        return self.source_path.is_dir()

class Config:
    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / "config.toml"
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        return self.config_file.exists()

    def load(self) -> dict:
        if not self.exists():
            return {}
        return toml.load(self.config_file)

    def save(self, config_data: dict):
        with open(self.config_file, 'w') as f:
            toml.dump(config_data, f)

    def get_credentials(self) -> Credentials:
        data = self.load()
        creds = data.get('credentials', {})
        return Credentials(
            notion_token=creds.get('notion', {}).get('api_token', ''),
            quip_token=creds.get('quip', {}).get('api_token', ''),
            quip_base_url=creds.get('quip', {}).get('base_url', 'https://quip-amazon.com')
        )

    def save_credentials(self, notion_token: str, quip_token: str, quip_base_url: str):
        data = self.load()
        data['credentials'] = {
            'notion': {'api_token': notion_token},
            'quip': {
                'api_token': quip_token,
                'base_url': quip_base_url
            }
        }
        self.save(data)

    def get_route(self, route_name: str) -> Optional[Route]:
        data = self.load()
        routes = data.get('routes', {})
        route_data = routes.get(route_name)
        if not route_data:
            return None
        return Route(**route_data)

    def list_routes(self) -> List[Route]:
        data = self.load()
        routes = data.get('routes', {})
        return [Route(**route_data) for route_data in routes.values()]

    def add_route(self, route: Route):
        data = self.load()
        if 'routes' not in data:
            data['routes'] = {}
        data['routes'][route.name] = asdict(route)
        self.save(data)

    def remove_route(self, route_name: str):
        data = self.load()
        if 'routes' in data and route_name in data['routes']:
            del data['routes'][route_name]
            self.save(data)
```

**Tests:**
```python
def test_config_credentials():
    config = Config()
    config.save_credentials("notion_token", "quip_token", "https://quip.com")
    creds = config.get_credentials()
    assert creds.notion_token == "notion_token"

def test_config_routes():
    config = Config()
    route = Route(
        name="test",
        description="Test route",
        source="/tmp/test",
        notion_database="db123",
        quip_folder="folder456"
    )
    config.add_route(route)
    loaded = config.get_route("test")
    assert loaded.name == "test"
```

---

### Task 3: State Management

**File:** `src/doc_genie/state.py`

**Implementation:**
```python
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
import json

STATE_FILE = Path.home() / ".doc_genie" / "state.json"

@dataclass
class DocumentState:
    source_path: str
    notion_page_id: Optional[str] = None
    quip_thread_id: Optional[str] = None
    last_synced: Optional[str] = None  # ISO format
    content_hash: Optional[str] = None
    media_files: Optional[Dict[str, Dict[str, str]]] = None

    def __post_init__(self):
        if self.media_files is None:
            self.media_files = {}

class State:
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self._ensure_state_file()

    def _ensure_state_file(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self.state_file.write_text('{"routes": {}}')

    def load(self) -> dict:
        return json.loads(self.state_file.read_text())

    def save(self, state_data: dict):
        self.state_file.write_text(json.dumps(state_data, indent=2))

    def get_document(self, route_name: str, relative_path: str) -> Optional[DocumentState]:
        data = self.load()
        route_data = data.get('routes', {}).get(route_name, {})
        doc_data = route_data.get('documents', {}).get(relative_path)
        if not doc_data:
            return None
        return DocumentState(**doc_data)

    def save_document(self, route_name: str, relative_path: str, doc_state: DocumentState):
        data = self.load()
        if 'routes' not in data:
            data['routes'] = {}
        if route_name not in data['routes']:
            data['routes'][route_name] = {'documents': {}}
        if 'documents' not in data['routes'][route_name]:
            data['routes'][route_name]['documents'] = {}

        data['routes'][route_name]['documents'][relative_path] = asdict(doc_state)
        self.save(data)

    def exists(self, route_name: str, relative_path: str) -> bool:
        return self.get_document(route_name, relative_path) is not None

    def get_route_documents(self, route_name: str) -> Dict[str, DocumentState]:
        data = self.load()
        route_data = data.get('routes', {}).get(route_name, {})
        docs = route_data.get('documents', {})
        return {path: DocumentState(**doc_data) for path, doc_data in docs.items()}
```

---

### Task 4: Document Models

**File:** `src/doc_genie/document.py`

**Implementation:**
```python
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

@dataclass
class MediaFile:
    """Represents an embedded media file"""
    original_ref: str       # Original markdown reference: ![[image.png]] or ![](path)
    local_path: Path        # Absolute path to file
    filename: str           # Just the filename
    file_type: str          # image, video, pdf

    @property
    def extension(self) -> str:
        return self.local_path.suffix.lower()

    def is_image(self) -> bool:
        return self.extension in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']

    def is_video(self) -> bool:
        return self.extension in ['.mp4', '.mov', '.avi', '.webm']

@dataclass
class Document:
    """Platform-agnostic document representation"""
    filepath: Path
    title: str
    content: str            # Raw content (markdown for Obsidian, HTML for Quip)
    media_files: List[MediaFile]
    metadata: Optional[dict] = None

    @property
    def filename(self) -> str:
        return self.filepath.name

@dataclass
class SyncResult:
    """Result of a sync operation"""
    success: bool
    route_name: str
    direction: str  # 'forward' or 'reverse'
    source_path: Path
    notion_page_id: Optional[str] = None
    quip_thread_id: Optional[str] = None
    error: Optional[str] = None
    media_count: int = 0
```

---

### Task 5: Media Handler

**File:** `src/doc_genie/media.py`

**Implementation:**
```python
import re
from pathlib import Path
from typing import List, Dict, Tuple
from doc_genie.document import MediaFile

class MediaHandler:
    """Extract and manage media files from documents"""

    # Regex patterns for both link types
    WIKILINK_PATTERN = r'!\[\[([^\]]+)\]\]'  # ![[image.png]]
    MARKDOWN_PATTERN = r'!\[([^\]]*)\]\(([^\)]+)\)'  # ![alt](path)

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path

    def extract_from_markdown(self, content: str, doc_path: Path) -> List[MediaFile]:
        """Extract all media files from markdown content"""
        media_files = []

        # Extract wikilinks: ![[image.png]]
        for match in re.finditer(self.WIKILINK_PATTERN, content):
            ref = match.group(1)
            local_path = self._resolve_wikilink(ref, doc_path)
            if local_path:
                media_files.append(self._create_media_file(match.group(0), local_path))

        # Extract standard markdown: ![alt](path)
        for match in re.finditer(self.MARKDOWN_PATTERN, content):
            path = match.group(2)
            # Skip URLs
            if path.startswith(('http://', 'https://')):
                continue
            local_path = self._resolve_relative_path(path, doc_path)
            if local_path:
                media_files.append(self._create_media_file(match.group(0), local_path))

        return media_files

    def _resolve_wikilink(self, ref: str, doc_path: Path) -> Optional[Path]:
        """Resolve wikilink to absolute path (search vault)"""
        # Try relative to document first
        relative = doc_path.parent / ref
        if relative.exists():
            return relative.resolve()

        # Search vault root
        vault_file = self.vault_path / ref
        if vault_file.exists():
            return vault_file.resolve()

        # Search common media folders
        for media_folder in ['_media', 'assets', 'images', 'attachments']:
            media_path = self.vault_path / media_folder / ref
            if media_path.exists():
                return media_path.resolve()

        return None

    def _resolve_relative_path(self, path: str, doc_path: Path) -> Optional[Path]:
        """Resolve relative path to absolute"""
        if path.startswith('/'):
            # Absolute path from vault root
            resolved = self.vault_path / path.lstrip('/')
        else:
            # Relative to document
            resolved = (doc_path.parent / path).resolve()

        return resolved if resolved.exists() else None

    def _create_media_file(self, original_ref: str, local_path: Path) -> MediaFile:
        """Create MediaFile object"""
        return MediaFile(
            original_ref=original_ref,
            local_path=local_path,
            filename=local_path.name,
            file_type='image' if local_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif'] else 'file'
        )

    def normalize_wikilinks(self, content: str) -> str:
        """Convert ![[image.png]] to ![](image.png) for processing"""
        def replace_wikilink(match):
            filename = match.group(1)
            return f'![]({filename})'

        return re.sub(self.WIKILINK_PATTERN, replace_wikilink, content)

    def replace_media_refs(self, content: str, media_map: Dict[str, str]) -> str:
        """Replace media references with new URLs/paths"""
        result = content
        for original_ref, new_ref in media_map.items():
            result = result.replace(original_ref, new_ref)
        return result
```

---

### Task 6: Platform Clients

**File:** `src/doc_genie/platforms/obsidian.py`

```python
from pathlib import Path
from typing import List
from doc_genie.document import Document, MediaFile
from doc_genie.media import MediaHandler

class ObsidianClient:
    """Read and write Obsidian markdown files"""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.media_handler = MediaHandler(vault_path)

    def read_document(self, filepath: Path) -> Document:
        """Read markdown file and extract metadata"""
        content = filepath.read_text(encoding='utf-8')

        # Extract title (from # heading or filename)
        title = self._extract_title(content) or filepath.stem

        # Extract media files
        media_files = self.media_handler.extract_from_markdown(content, filepath)

        return Document(
            filepath=filepath,
            title=title,
            content=content,
            media_files=media_files
        )

    def write_document(self, filepath: Path, title: str, content: str, media_files: List[MediaFile]):
        """Write markdown file to vault"""
        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        filepath.write_text(content, encoding='utf-8')

        # Save media files to vault
        media_dir = filepath.parent / '_media'
        media_dir.mkdir(exist_ok=True)

        for media in media_files:
            target_path = media_dir / media.filename
            if not target_path.exists():
                # Copy/download media file
                target_path.write_bytes(media.local_path.read_bytes())

    def _extract_title(self, content: str) -> Optional[str]:
        """Extract title from first # heading"""
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('# '):
                return line[2:].strip()
        return None

    def get_relative_path(self, filepath: Path) -> str:
        """Get path relative to vault"""
        return str(filepath.relative_to(self.vault_path))
```

**File:** `src/doc_genie/platforms/notion_client.py`

```python
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger
from notion_client import Client
from doc_genie.document import MediaFile

class NotionClient:
    """Wrapper around notion-sdk-py"""

    def __init__(self, api_token: str, database_id: str):
        self.client = Client(auth=api_token)
        self.database_id = database_id
        logger.debug("NotionClient initialized: database={}", database_id)

    def create_page(self, title: str, blocks: List[Dict]) -> str:
        """Create page in database"""
        logger.info("Creating Notion page: title={}, blocks={}", title, len(blocks))
        response = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties={
                "Name": {"title": [{"text": {"content": title}}]}
            },
            children=blocks
        )
        logger.debug("Notion page created: id={}", response['id'])
        return response['id']

    def update_page_content(self, page_id: str, blocks: List[Dict]):
        """Replace page content (delete all blocks, add new ones)"""
        logger.info("Updating Notion page content: page_id={}, blocks={}", page_id, len(blocks))

        # Get existing blocks
        existing = self.client.blocks.children.list(page_id)
        logger.debug("Found {} existing blocks to delete", len(existing['results']))

        # Delete all blocks
        for block in existing['results']:
            self.client.blocks.delete(block['id'])

        # Add new blocks
        self.client.blocks.children.append(page_id, children=blocks)
        logger.debug("Page content updated successfully")

    def get_blocks(self, page_id: str) -> List[Dict]:
        """Fetch all blocks from page"""
        response = self.client.blocks.children.list(page_id)
        return response['results']

    def upload_file(self, file_path: Path) -> str:
        """Upload file to Notion, return URL"""
        # TODO: Implement using new Notion file upload API (May 2025)
        # For now, this is a placeholder
        # Real implementation needs to use create_file_upload endpoint
        raise NotImplementedError("Notion file upload not yet implemented")

    def download_file(self, file_url: str, output_path: Path):
        """Download file from Notion URL"""
        import requests
        response = requests.get(file_url)
        output_path.write_bytes(response.content)
```

**File:** `src/doc_genie/platforms/quip_client.py`

```python
from pathlib import Path
from typing import Dict
from doc_genie.quip_api import QuipClient as BaseQuipClient
from doc_genie.document import MediaFile

class QuipClient:
    """Wrapper around Quip API"""

    def __init__(self, api_token: str, base_url: str, folder_id: str):
        self.client = BaseQuipClient(access_token=api_token, base_url=base_url)
        self.folder_id = folder_id

    def create_document(self, title: str, html_content: str) -> str:
        """Create document in folder"""
        response = self.client.new_document(
            content=html_content,
            format="html",
            title=title,
            member_ids=[self.folder_id]
        )
        return response['thread']['id']

    def update_document(self, thread_id: str, html_content: str):
        """Replace document content"""
        # Use REPLACE_SECTION on the document root
        self.client.edit_document(
            thread_id=thread_id,
            content=html_content,
            operation=self.client.REPLACE_SECTION,
            format="html"
        )

    def get_document(self, thread_id: str) -> Dict:
        """Fetch document"""
        return self.client.get_thread(thread_id)

    def upload_blob(self, thread_id: str, file_path: Path) -> Dict:
        """Upload file blob, return blob info"""
        with open(file_path, 'rb') as f:
            return self.client.put_blob(thread_id, f, name=file_path.name)

    def download_blob(self, thread_id: str, blob_id: str, output_path: Path):
        """Download blob to file"""
        blob_data = self.client.get_blob(thread_id, blob_id)
        with open(output_path, 'wb') as f:
            f.write(blob_data.read())
```

---

### Task 7: Format Converter

**File:** `src/doc_genie/converter.py`

This is the most complex component. It needs to handle bidirectional conversion.

```python
from typing import List, Dict
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import mistune

class MarkdownConverter:
    """Convert between Markdown, Notion blocks, and Quip HTML"""

    def markdown_to_notion_blocks(self, markdown: str, media_map: Dict[str, str]) -> List[Dict]:
        """Convert markdown to Notion block objects"""
        blocks = []

        # Parse markdown with mistune
        markdown_ast = mistune.create_markdown(renderer='ast')
        tokens = markdown_ast(markdown)

        for token in tokens:
            block = self._token_to_notion_block(token, media_map)
            if block:
                blocks.append(block)

        return blocks

    def _token_to_notion_block(self, token: dict, media_map: Dict) -> Dict:
        """Convert mistune token to Notion block"""
        token_type = token['type']

        if token_type == 'heading':
            level = token['attrs']['level']
            return {
                "type": f"heading_{level}",
                f"heading_{level}": {
                    "rich_text": [{"type": "text", "text": {"content": token['children'][0]['raw']}}]
                }
            }

        elif token_type == 'paragraph':
            # Extract text and check for images
            text = self._extract_text(token)
            return {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            }

        # TODO: Implement list, table, code block, image conversions

        return None

    def notion_blocks_to_markdown(self, blocks: List[Dict]) -> str:
        """Convert Notion blocks to markdown"""
        markdown_lines = []

        for block in blocks:
            block_type = block['type']

            if block_type.startswith('heading_'):
                level = int(block_type.split('_')[1])
                text = self._extract_notion_text(block[block_type]['rich_text'])
                markdown_lines.append(f"{'#' * level} {text}")

            elif block_type == 'paragraph':
                text = self._extract_notion_text(block['paragraph']['rich_text'])
                markdown_lines.append(text)

            elif block_type == 'image':
                # Handle image block
                url = block['image'].get('file', {}).get('url', '')
                markdown_lines.append(f"![]({url})")

            # TODO: Implement list, table, code block conversions

            markdown_lines.append("")  # Blank line between blocks

        return "\n".join(markdown_lines)

    def notion_blocks_to_quip_html(self, blocks: List[Dict], media_map: Dict[str, str]) -> str:
        """Convert Notion blocks to Quip HTML"""
        html_parts = []

        for block in blocks:
            block_type = block['type']

            if block_type.startswith('heading_'):
                level = int(block_type.split('_')[1])
                text = self._extract_notion_text(block[block_type]['rich_text'])
                html_parts.append(f"<h{level}>{text}</h{level}>")

            elif block_type == 'paragraph':
                text = self._extract_notion_text(block['paragraph']['rich_text'])
                html_parts.append(f"<p>{text}</p>")

            elif block_type == 'image':
                # Replace with Quip blob reference
                url = block['image'].get('file', {}).get('url', '')
                blob_id = media_map.get(url, url)
                html_parts.append(f'<img src="{blob_id}"/>')

            # TODO: Implement list, table, code block conversions

        return "\n".join(html_parts)

    def quip_html_to_notion_blocks(self, html: str) -> List[Dict]:
        """Convert Quip HTML to Notion blocks"""
        soup = BeautifulSoup(html, 'html.parser')
        blocks = []

        for element in soup.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'img']):
            if element.name in ['h1', 'h2', 'h3']:
                level = int(element.name[1])
                blocks.append({
                    "type": f"heading_{level}",
                    f"heading_{level}": {
                        "rich_text": [{"type": "text", "text": {"content": element.get_text()}}]
                    }
                })

            elif element.name == 'p':
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": element.get_text()}}]
                    }
                })

            elif element.name == 'img':
                # Will need to download and re-upload
                src = element.get('src', '')
                blocks.append({
                    "type": "image",
                    "image": {"type": "external", "external": {"url": src}}
                })

        return blocks

    def _extract_text(self, token: dict) -> str:
        """Extract text from mistune token"""
        if 'raw' in token:
            return token['raw']
        if 'children' in token:
            return ''.join(self._extract_text(child) for child in token['children'])
        return ''

    def _extract_notion_text(self, rich_text: List[Dict]) -> str:
        """Extract plain text from Notion rich_text array"""
        return ''.join(item['text']['content'] for item in rich_text)
```

---

### Task 8: Sync Engine

**File:** `src/doc_genie/sync_engine.py`

```python
from pathlib import Path
from typing import Dict
import hashlib
from datetime import datetime
from loguru import logger

from doc_genie.config import Config, Route
from doc_genie.state import State, DocumentState
from doc_genie.document import SyncResult
from doc_genie.platforms.obsidian import ObsidianClient
from doc_genie.platforms.notion_client import NotionClient
from doc_genie.platforms.quip_client import QuipClient
from doc_genie.converter import MarkdownConverter
from doc_genie.media import MediaHandler

class SyncEngine:
    """Orchestrate bidirectional sync: Obsidian ↔ Notion ↔ Quip"""

    def __init__(self, config: Config, state: State):
        self.config = config
        self.state = state
        self.converter = MarkdownConverter()
        logger.debug("SyncEngine initialized")

    def sync(self, filepath: Path, route_name: str, direction: str) -> SyncResult:
        """
        Sync document through route in specified direction

        Args:
            filepath: Path to document
            route_name: Named route to use
            direction: 'forward' (Obsidian → Quip) or 'reverse' (Quip → Obsidian)
        """
        route = self.config.get_route(route_name)
        if not route:
            raise ValueError(f"Route not found: {route_name}")

        if direction == 'forward':
            return self._sync_forward(filepath, route)
        elif direction == 'reverse':
            return self._sync_reverse(filepath, route)
        else:
            raise ValueError(f"Invalid direction: {direction}")

    def _sync_forward(self, filepath: Path, route: Route) -> SyncResult:
        """Obsidian → Notion → Quip"""
        logger.info("Forward sync started: Obsidian → Notion → Quip")

        # Initialize clients
        logger.debug("Initializing platform clients")
        obsidian = ObsidianClient(route.source_path)
        creds = self.config.get_credentials()
        notion = NotionClient(creds.notion_token, route.notion_database)
        quip = QuipClient(creds.quip_token, creds.quip_base_url, route.quip_folder)

        # Get relative path for state tracking
        relative_path = obsidian.get_relative_path(filepath)
        existing_state = self.state.get_document(route.name, relative_path)
        logger.debug("Document state: exists={}", existing_state is not None)

        # Read from Obsidian
        logger.info("Reading document from Obsidian: {}", filepath.name)
        doc = obsidian.read_document(filepath)
        logger.debug("Document loaded: title={}, media_count={}", doc.title, len(doc.media_files))

        # Upload media to Notion
        logger.info("Uploading {} media files to Notion", len(doc.media_files))
        media_map_notion = {}
        for media in doc.media_files:
            logger.debug("Uploading media: {}", media.filename)
            url = notion.upload_file(media.local_path)
            media_map_notion[media.original_ref] = url

        # Convert and sync to Notion
        logger.info("Converting markdown to Notion blocks")
        notion_blocks = self.converter.markdown_to_notion_blocks(doc.content, media_map_notion)

        if existing_state and existing_state.notion_page_id:
            logger.info("Updating existing Notion page: {}", existing_state.notion_page_id)
            notion.update_page_content(existing_state.notion_page_id, notion_blocks)
            notion_page_id = existing_state.notion_page_id
        else:
            logger.info("Creating new Notion page")
            notion_page_id = notion.create_page(doc.title, notion_blocks)
            logger.debug("Notion page created: {}", notion_page_id)

        # Get blocks back from Notion (for conversion to Quip)
        logger.debug("Fetching blocks from Notion")
        notion_blocks = notion.get_blocks(notion_page_id)

        # Upload media to Quip
        if not existing_state or not existing_state.quip_thread_id:
            logger.info("Creating new Quip document")
            quip_thread_id = quip.create_document(doc.title, "")
            logger.debug("Quip thread created: {}", quip_thread_id)
        else:
            quip_thread_id = existing_state.quip_thread_id
            logger.info("Using existing Quip thread: {}", quip_thread_id)

        logger.info("Uploading {} media blobs to Quip", len(doc.media_files))
        media_map_quip = {}
        for media in doc.media_files:
            logger.debug("Uploading blob: {}", media.filename)
            blob_info = quip.upload_blob(quip_thread_id, media.local_path)
            media_map_quip[media_map_notion[media.original_ref]] = blob_info['id']

        # Convert and sync to Quip
        logger.info("Converting Notion blocks to Quip HTML")
        quip_html = self.converter.notion_blocks_to_quip_html(notion_blocks, media_map_quip)
        logger.debug("Updating Quip document content")
        quip.update_document(quip_thread_id, quip_html)

        # Save state
        logger.debug("Saving sync state")
        content_hash = self._calculate_hash(doc.content)
        doc_state = DocumentState(
            source_path=str(filepath),
            notion_page_id=notion_page_id,
            quip_thread_id=quip_thread_id,
            last_synced=datetime.now().isoformat(),
            content_hash=content_hash,
            media_files={}
        )
        self.state.save_document(route.name, relative_path, doc_state)

        logger.success("Forward sync completed successfully")
        return SyncResult(
            success=True,
            route_name=route.name,
            direction='forward',
            source_path=filepath,
            notion_page_id=notion_page_id,
            quip_thread_id=quip_thread_id,
            media_count=len(doc.media_files)
        )

    def _sync_reverse(self, filepath: Path, route: Route) -> SyncResult:
        """Quip → Notion → Obsidian"""
        # Initialize clients
        obsidian = ObsidianClient(route.source_path)
        creds = self.config.get_credentials()
        notion = NotionClient(creds.notion_token, route.notion_database)
        quip = QuipClient(creds.quip_token, creds.quip_base_url, route.quip_folder)

        # Get state
        relative_path = obsidian.get_relative_path(filepath)
        existing_state = self.state.get_document(route.name, relative_path)

        if not existing_state or not existing_state.quip_thread_id:
            raise ValueError(f"Document not synced yet: {filepath}")

        # Fetch from Quip
        quip_doc = quip.get_document(existing_state.quip_thread_id)
        quip_html = quip_doc['html']

        # Convert to Notion blocks
        notion_blocks = self.converter.quip_html_to_notion_blocks(quip_html)

        # Update Notion
        notion.update_page_content(existing_state.notion_page_id, notion_blocks)

        # Get blocks back
        notion_blocks = notion.get_blocks(existing_state.notion_page_id)

        # Convert to Markdown
        markdown = self.converter.notion_blocks_to_markdown(notion_blocks)

        # Download media (TODO: implement)
        # Save to Obsidian
        obsidian.write_document(filepath, quip_doc['thread']['title'], markdown, [])

        # Update state
        content_hash = self._calculate_hash(markdown)
        doc_state = DocumentState(
            source_path=str(filepath),
            notion_page_id=existing_state.notion_page_id,
            quip_thread_id=existing_state.quip_thread_id,
            last_synced=datetime.now().isoformat(),
            content_hash=content_hash,
            media_files={}
        )
        self.state.save_document(route.name, relative_path, doc_state)

        return SyncResult(
            success=True,
            route_name=route.name,
            direction='reverse',
            source_path=filepath,
            notion_page_id=existing_state.notion_page_id,
            quip_thread_id=existing_state.quip_thread_id
        )

    def _calculate_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content"""
        return hashlib.sha256(content.encode()).hexdigest()
```

---

### Task 9: CLI Implementation

**File:** `src/doc_genie/cli.py`

```python
import sys
import click
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from doc_genie.config import Config, Route
from doc_genie.state import State
from doc_genie.sync_engine import SyncEngine

console = Console()

# Configure loguru
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)

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
    """Doc Genie - Bidirectional document sync for Obsidian, Notion, and Quip"""
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
        logger.debug("Verbose logging enabled")

@cli.command()
def init():
    """Initialize configuration with credentials"""
    console.print("[bold cyan]Doc Genie Setup[/bold cyan]\n")

    config = Config()

    console.print("[blue]Enter Notion credentials:[/blue]")
    notion_token = click.prompt("Notion API token", hide_input=True)

    console.print("\n[blue]Enter Quip credentials:[/blue]")
    quip_token = click.prompt("Quip API token", hide_input=True)
    quip_base_url = click.prompt("Quip base URL", default="https://quip-amazon.com")

    config.save_credentials(notion_token, quip_token, quip_base_url)
    console.print("\n[green]✓ Configuration saved to ~/.doc_genie/config.toml[/green]")

@cli.command()
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--route', '-r', required=True, help='Named route to use')
@click.option('--direction', '-d',
              type=click.Choice(['forward', 'reverse']),
              default='forward',
              help='Sync direction: forward (Obsidian→Quip) or reverse (Quip→Obsidian)')
def sync(filepath, route, direction):
    """
    Sync document through named route

    Examples:
        doc-genie sync document.md -r work-docs -d forward
        doc-genie sync document.md -r personal -d reverse
    """
    try:
        logger.info("Starting sync: file={}, route={}, direction={}", filepath, route, direction)

        config = Config()
        state = State()
        engine = SyncEngine(config, state)

        filepath = Path(filepath).resolve()
        logger.debug("Resolved filepath: {}", filepath)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Syncing {filepath.name}...", total=None)
            result = engine.sync(filepath, route, direction)
            progress.update(task, completed=True)

        logger.success("Sync completed: notion={}, quip={}", result.notion_page_id, result.quip_thread_id)

        direction_arrow = "→" if direction == 'forward' else "←"
        console.print(f"\n[green]✓ Synced successfully![/green]")
        console.print(f"  Route: [cyan]{route}[/cyan] ({direction_arrow})")
        console.print(f"  Notion: [blue]{result.notion_page_id}[/blue]")
        console.print(f"  Quip: [blue]{result.quip_thread_id}[/blue]")
        if result.media_count > 0:
            console.print(f"  Media files: {result.media_count}")
            logger.info("Media files synced: {}", result.media_count)

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
        try:
            obsidian = ObsidianClient(r.source_path)
            relative_path = obsidian.get_relative_path(filepath)
            doc_state = state.get_document(r.name, relative_path)

            if doc_state:
                found = True
                console.print(f"\n[bold]Route:[/bold] {r.name}")
                console.print(f"  File: {relative_path}")
                console.print(f"  Notion: {doc_state.notion_page_id}")
                console.print(f"  Quip: {doc_state.quip_thread_id}")
                console.print(f"  Last synced: {doc_state.last_synced}")
        except ValueError:
            continue

    if not found:
        console.print(f"[yellow]Document not synced in any route[/yellow]")

@cli.command()
@click.argument('route_name')
def route_add(route_name):
    """Add a new sync route interactively"""
    config = Config()

    console.print(f"[bold]Adding route: {route_name}[/bold]\n")

    description = click.prompt("Description")
    source = click.prompt("Source path (file or directory)", type=click.Path(exists=True))
    notion_db = click.prompt("Notion database ID")
    quip_folder = click.prompt("Quip folder ID")

    route = Route(
        name=route_name,
        description=description,
        source=str(source),
        notion_database=notion_db,
        quip_folder=quip_folder,
        enabled=True
    )

    config.add_route(route)
    console.print(f"\n[green]✓ Route '{route_name}' added![/green]")

@cli.command()
@click.argument('route_name')
def route_remove(route_name):
    """Remove a sync route"""
    config = Config()
    if click.confirm(f"Remove route '{route_name}'?"):
        config.remove_route(route_name)
        console.print(f"[green]✓ Route '{route_name}' removed[/green]")

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
def config_show():
    """Show current configuration (credentials masked)"""
    config = Config()

    if not config.exists():
        console.print("[yellow]No configuration found. Run 'doc-genie init' first.[/yellow]")
        return

    console.print("[bold]Credentials:[/bold]")
    creds = config.get_credentials()
    console.print(f"  Notion token: {creds.notion_token[:10]}..." if creds.notion_token else "  Notion: Not configured")
    console.print(f"  Quip token: {creds.quip_token[:10]}..." if creds.quip_token else "  Quip: Not configured")
    console.print(f"  Quip URL: {creds.quip_base_url}")

    console.print("\n[bold]Routes:[/bold]")
    routes = config.list_routes()
    if routes:
        for route in routes:
            console.print(f"  • {route.name}: {route.source}")
    else:
        console.print("  No routes configured")

if __name__ == '__main__':
    cli()
```

---

## Testing Strategy

### Unit Tests
- Test configuration loading/saving
- Test state management
- Test media extraction (both link types)
- Test path resolution
- Test format conversion

### Integration Tests
- Test Obsidian → Notion sync
- Test Notion → Quip sync
- Test reverse sync
- Test with real files (mock API calls)

### Manual Testing Checklist
- [ ] Initialize config
- [ ] Add route
- [ ] Sync document with images (forward)
- [ ] Update document, resync
- [ ] Sync document with wikilinks
- [ ] Sync document with tables
- [ ] Reverse sync
- [ ] Check status
- [ ] List routes

---

## Known Issues & TODOs

1. **Notion File Upload API**: New API (May 2025) - need to implement properly
2. **Table Conversion**: Complex - may not work perfectly in Quip
3. **Media Download**: Need to implement for reverse sync
4. **Error Handling**: Add proper error messages and recovery
5. **Rate Limiting**: Notion/Quip may rate limit - add basic retry
6. **Large Files**: Handle >20MB files for Notion multi-part upload

---

## Deployment

```bash
# Build package with uv
uv build

# Install locally
uv pip install dist/doc_genie-0.1.0-py3-none-any.whl

# Or install in editable mode for development
uv pip install -e .

# Test
doc-genie --help
```

---

## Future Enhancements

- Batch sync (directory)
- Watch mode (auto-sync on file change)
- Dry-run mode
- Rollback capability
- Better conflict detection
- GUI/TUI interface
