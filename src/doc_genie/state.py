"""State management for Doc Genie sync operations."""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
import json
from loguru import logger

STATE_FILE = Path.home() / ".doc_genie" / "state.json"


@dataclass
class DocumentState:
    """Sync state for a single document."""
    source_path: str
    notion_page_id: Optional[str] = None
    quip_thread_id: Optional[str] = None
    last_synced: Optional[str] = None  # ISO format timestamp
    content_hash: Optional[str] = None
    media_files: Optional[Dict[str, Dict[str, str]]] = None
    # media_files format: {
    #   "filename.png": {
    #       "hash": "sha256_hash",
    #       "file_upload_id": "notion_file_id",
    #       "size": "12345"
    #   }
    # }

    def __post_init__(self):
        """Initialize media_files dict if None."""
        if self.media_files is None:
            self.media_files = {}


class State:
    """Manage sync state in ~/.doc_genie/state.json."""

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self._ensure_state_file()

    def _ensure_state_file(self):
        """Ensure state file and directory exist."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self.state_file.write_text('{"routes": {}}')
            logger.debug("Created new state file: {}", self.state_file)
        else:
            logger.debug("Using existing state file: {}", self.state_file)

    def load(self) -> dict:
        """Load state from file."""
        try:
            state_data = json.loads(self.state_file.read_text())
            logger.debug("Loaded state from {}", self.state_file)
            return state_data
        except Exception as e:
            # Only log as debug - empty/corrupt state is fine, we'll create it
            logger.debug("State file not loaded (will be created): {}", e)
            return {"routes": {}}

    def save(self, state_data: dict):
        """Save state to file."""
        try:
            self.state_file.write_text(json.dumps(state_data, indent=2))
            logger.debug("Saved state to {}", self.state_file)
        except Exception as e:
            logger.error("Failed to save state: {}", e)
            raise

    def get_document(self, route_name: str, relative_path: str) -> Optional[DocumentState]:
        """Get document state for a specific route and path."""
        data = self.load()
        route_data = data.get('routes', {}).get(route_name, {})
        doc_data = route_data.get('documents', {}).get(relative_path)
        if not doc_data:
            logger.debug("No state found for document: route={}, path={}", route_name, relative_path)
            return None
        logger.debug("Found state for document: route={}, path={}", route_name, relative_path)
        return DocumentState(**doc_data)

    def save_document(self, route_name: str, relative_path: str, doc_state: DocumentState):
        """Save document state for a specific route and path."""
        data = self.load()
        if 'routes' not in data:
            data['routes'] = {}
        if route_name not in data['routes']:
            data['routes'][route_name] = {'documents': {}}
        if 'documents' not in data['routes'][route_name]:
            data['routes'][route_name]['documents'] = {}

        data['routes'][route_name]['documents'][relative_path] = asdict(doc_state)
        self.save(data)
        logger.info("Saved document state: route={}, path={}", route_name, relative_path)

    def exists(self, route_name: str, relative_path: str) -> bool:
        """Check if document state exists."""
        return self.get_document(route_name, relative_path) is not None

    def get_route_documents(self, route_name: str) -> Dict[str, DocumentState]:
        """Get all document states for a route."""
        data = self.load()
        route_data = data.get('routes', {}).get(route_name, {})
        docs = route_data.get('documents', {})
        return {path: DocumentState(**doc_data) for path, doc_data in docs.items()}
