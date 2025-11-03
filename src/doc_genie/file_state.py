"""Per-file state management for document sync.

Stores state in .dg files next to each .md file for Dropbox sync.
"""

from pathlib import Path
from typing import Dict, Optional
import json
from datetime import datetime
from loguru import logger


class FileState:
    """Manages per-document state stored in .dg files."""

    def __init__(self, md_file_path: Path):
        """Initialize state manager for a markdown file.

        Args:
            md_file_path: Path to the .md file
        """
        self.md_file_path = md_file_path
        self.state_file_path = md_file_path.with_suffix(md_file_path.suffix + '.dg')
        self._state = self._load()

    def _load(self) -> Dict:
        """Load state from .dg file."""
        if not self.state_file_path.exists():
            logger.debug("No state file found: {}", self.state_file_path)
            return {
                "media_files": {},
                "notion_page_id": None,
                "quip_thread_id": None,
                "last_synced": None
            }

        try:
            with open(self.state_file_path, 'r') as f:
                state = json.load(f)
                logger.debug("Loaded state from: {}", self.state_file_path)
                return state
        except Exception as e:
            logger.warning("Failed to load state file {}: {}", self.state_file_path, e)
            return {
                "media_files": {},
                "notion_page_id": None,
                "quip_thread_id": None,
                "last_synced": None
            }

    def save(self):
        """Save state to .dg file."""
        try:
            self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file_path, 'w') as f:
                json.dump(self._state, f, indent=2)
            logger.debug("Saved state to: {}", self.state_file_path)
        except Exception as e:
            logger.error("Failed to save state file {}: {}", self.state_file_path, e)
            raise

    def get_media_hash(self, relative_path: str) -> Optional[str]:
        """Get hash for a media file.

        Args:
            relative_path: Relative path from .md file to media file

        Returns:
            Hash if found, None otherwise
        """
        media_info = self._state.get("media_files", {}).get(relative_path)
        if media_info:
            return media_info.get('hash')
        return None

    def get_media_file_upload_id(self, relative_path: str) -> Optional[str]:
        """Get Notion file_upload_id for a media file.

        Args:
            relative_path: Relative path from .md file to media file

        Returns:
            file_upload_id if found, None otherwise
        """
        media_info = self._state.get("media_files", {}).get(relative_path)
        if media_info:
            return media_info.get('file_upload_id')
        return None

    def get_media_quip_blob_id(self, relative_path: str) -> Optional[str]:
        """Get Quip blob_id for a media file.

        Args:
            relative_path: Relative path from .md file to media file

        Returns:
            blob_id if found, None otherwise
        """
        media_info = self._state.get("media_files", {}).get(relative_path)
        if media_info:
            return media_info.get('quip_blob_id')
        return None

    def update_media(self, relative_path: str, file_hash: str,
                    file_upload_id: Optional[str] = None,
                    quip_blob_id: Optional[str] = None,
                    size: Optional[int] = None):
        """Update media file info.

        Args:
            relative_path: Relative path from .md file to media file
            file_hash: SHA256 hash of file
            file_upload_id: Notion file_upload_id (optional)
            quip_blob_id: Quip blob_id (optional)
            size: File size in bytes (optional)
        """
        if "media_files" not in self._state:
            self._state["media_files"] = {}

        # Get existing media info or create new
        media_info = self._state["media_files"].get(relative_path, {})

        # Update fields
        media_info['hash'] = file_hash
        if file_upload_id:
            media_info['file_upload_id'] = file_upload_id
        if quip_blob_id:
            media_info['quip_blob_id'] = quip_blob_id
        if size is not None:
            media_info['size'] = size

        self._state["media_files"][relative_path] = media_info

    def update_notion_page_id(self, page_id: str):
        """Update Notion page ID."""
        self._state["notion_page_id"] = page_id

    def update_quip_thread_id(self, thread_id: str):
        """Update Quip thread ID."""
        self._state["quip_thread_id"] = thread_id

    def update_last_synced(self):
        """Update last synced timestamp."""
        self._state["last_synced"] = datetime.now().isoformat()

    def get_notion_page_id(self) -> Optional[str]:
        """Get Notion page ID."""
        return self._state.get("notion_page_id")

    def get_quip_thread_id(self) -> Optional[str]:
        """Get Quip thread ID."""
        return self._state.get("quip_thread_id")

    def get_last_synced(self) -> Optional[str]:
        """Get last synced timestamp."""
        return self._state.get("last_synced")

    def get_all_media_files(self) -> Dict[str, Dict]:
        """Get all media file entries.

        Returns:
            Dict of {relative_path: {hash, file_upload_id, ...}}
        """
        return self._state.get("media_files", {})
