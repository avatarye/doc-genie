"""Sync engine for orchestrating document sync operations."""

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
from doc_genie.converter import MarkdownConverter


class SyncEngine:
    """Orchestrate bidirectional sync: Obsidian ↔ Notion ↔ Quip."""

    def __init__(self, config: Config, state: State):
        self.config = config
        self.state = state
        self.converter = MarkdownConverter()
        logger.debug("SyncEngine initialized")

    def sync(self, filepath: Path, route_name: str, direction: str = 'forward') -> SyncResult:
        """
        Sync document through route in specified direction.

        Args:
            filepath: Path to document
            route_name: Named route to use
            direction: 'forward' (Obsidian → Notion) or 'reverse' (Notion → Obsidian)

        Returns:
            SyncResult with operation details
        """
        route = self.config.get_route(route_name)
        if not route:
            raise ValueError(f"Route not found: {route_name}")

        if direction == 'forward':
            return self._sync_forward(filepath, route)
        elif direction == 'reverse':
            return self._sync_reverse(filepath, route)
        else:
            raise ValueError(f"Invalid direction: {direction}. Must be 'forward' or 'reverse'")

    def _sync_forward(self, filepath: Path, route: Route) -> SyncResult:
        """Obsidian → Notion (simplified, no Quip yet)."""
        try:
            # Initialize clients
            obsidian = ObsidianClient(route.source_path)
            creds = self.config.get_credentials()

            if not creds.notion_token:
                raise ValueError("Notion token not configured. Run 'dg init' first.")

            notion = NotionClient(creds.notion_token, route.notion_database)

            # Get relative path for state tracking
            relative_path = obsidian.get_relative_path(filepath)
            existing_state = self.state.get_document(route.name, relative_path)

            # Read from Obsidian
            doc = obsidian.read_document(filepath)
            logger.info("Syncing: {} → Notion ({})", filepath.name, route.name)

            # Handle media files
            media_map_notion = {}
            media_state = {}  # Track media files for state storage

            if doc.media_files:
                for media in doc.media_files:
                    # Check if file actually exists
                    if media.local_path.exists() and not str(media.local_path).startswith("/missing"):
                        # Calculate file hash
                        file_hash = notion.calculate_file_hash(media.local_path)
                        file_size = media.local_path.stat().st_size

                        # Check if we already uploaded this file (hash comparison)
                        should_upload = True
                        cached_file_id = None

                        if existing_state and existing_state.media_files:
                            cached_media = existing_state.media_files.get(media.filename)
                            if cached_media:
                                cached_hash = cached_media.get('hash')
                                cached_file_id = cached_media.get('file_upload_id')

                                if cached_hash == file_hash and cached_file_id:
                                    logger.info("✓ Using cached upload: {} (hash match)", media.filename)
                                    should_upload = False
                                    file_upload_id = cached_file_id

                        # Upload if needed
                        if should_upload:
                            logger.info("Uploading: {} ({:.2f} MB)", media.filename, file_size / (1024 * 1024))
                            try:
                                file_upload_id = notion.upload_file(media.local_path)
                                if not file_upload_id:
                                    logger.warning("Upload failed: {}", media.filename)
                                    continue
                            except Exception as e:
                                logger.warning("Upload failed {}: {}", media.filename, e)
                                continue

                        # Store in media_map (with file type) and state
                        # media_map format: {original_ref: (file_upload_id, file_type)}
                        media_map_notion[media.original_ref] = (file_upload_id, media.file_type)
                        media_state[media.filename] = {
                            'hash': file_hash,
                            'file_upload_id': file_upload_id,
                            'size': str(file_size)
                        }
                    else:
                        logger.debug("File not found, will show as callout: {}", media.filename)

            # Convert and sync to Notion
            notion_blocks = self.converter.markdown_to_notion_blocks(doc.content, media_map_notion)

            if existing_state and existing_state.notion_page_id:
                # Archive old page and create new one
                try:
                    notion.archive_page(existing_state.notion_page_id)
                except Exception:
                    pass  # Already archived or doesn't exist

            notion_page_id = notion.create_page(doc.title, notion_blocks)

            # Save state
            content_hash = self._calculate_hash(doc.content)
            doc_state = DocumentState(
                source_path=str(filepath),
                notion_page_id=notion_page_id,
                quip_thread_id=None,  # Not syncing to Quip yet
                last_synced=datetime.now().isoformat(),
                content_hash=content_hash,
                media_files=media_state  # Save media file hashes and IDs
            )
            self.state.save_document(route.name, relative_path, doc_state)

            logger.success("Synced successfully → {}", notion_page_id[:13] + "...")
            return SyncResult(
                success=True,
                route_name=route.name,
                direction='forward',
                source_path=filepath,
                notion_page_id=notion_page_id,
                quip_thread_id=None,
                media_count=len(doc.media_files)
            )

        except Exception as e:
            logger.exception("Forward sync failed: {}", e)
            return SyncResult(
                success=False,
                route_name=route.name,
                direction='forward',
                source_path=filepath,
                error=str(e)
            )

    def _sync_reverse(self, filepath: Path, route: Route) -> SyncResult:
        """Notion → Obsidian (not implemented yet)."""
        logger.warning("Reverse sync not implemented yet")
        raise NotImplementedError("Reverse sync (Notion → Obsidian) not implemented yet")

    def _calculate_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()
