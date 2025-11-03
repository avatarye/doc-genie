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
from doc_genie.platforms.quip_client import QuipClient
from doc_genie.converter import MarkdownConverter
from doc_genie.file_state import FileState


class SyncEngine:
    """Orchestrate bidirectional sync: Obsidian ↔ Notion ↔ Quip."""

    def __init__(self, config: Config, state: State):
        self.config = config
        self.state = state
        self.converter = MarkdownConverter()
        logger.debug("SyncEngine initialized")

    def sync(self, filepath: Path, route_name: str, direction: str = 'forward', skip_quip: bool = False, skip_notion: bool = False) -> SyncResult:
        """
        Sync document through route in specified direction.

        Args:
            filepath: Path to document
            route_name: Named route to use
            direction: 'forward' (Obsidian → Notion) or 'reverse' (Notion → Obsidian)
            skip_quip: If True, skip Quip sync (forward only)
            skip_notion: If True, skip Notion sync (reverse only)

        Returns:
            SyncResult with operation details
        """
        route = self.config.get_route(route_name)
        if not route:
            raise ValueError(f"Route not found: {route_name}")

        if direction == 'forward':
            return self._sync_forward(filepath, route, skip_quip=skip_quip)
        elif direction == 'reverse':
            return self._sync_reverse(filepath, route, skip_notion=skip_notion)
        else:
            raise ValueError(f"Invalid direction: {direction}. Must be 'forward' or 'reverse'")

    def _sync_forward(self, filepath: Path, route: Route, skip_quip: bool = False) -> SyncResult:
        """Obsidian → Notion → Quip (optionally skip Quip)."""
        try:
            # Initialize clients
            obsidian = ObsidianClient(route.source_path)
            creds = self.config.get_credentials()

            if not creds.notion_token:
                raise ValueError("Notion token not configured. Run 'dg init' first.")

            notion = NotionClient(creds.notion_token, route.notion_database)

            # Read from Obsidian
            doc = obsidian.read_document(filepath)
            logger.info("Syncing: {} → Notion ({})", filepath.name, route.name)

            # Load per-file state (.dg file next to .md file)
            file_state = FileState(filepath)
            logger.debug("Loaded state from: {}", file_state.state_file_path)

            # Normalize media file locations: move all to _<doc_name>.files/
            media_dir_name = f"_{filepath.stem}.files"
            media_dir = filepath.parent / media_dir_name
            content_updated = False

            if doc.media_files:
                media_dir.mkdir(exist_ok=True)
                logger.debug("Normalizing media files to: {}", media_dir)

                for media in doc.media_files:
                    if media.local_path.exists() and not str(media.local_path).startswith("/missing"):
                        # Target location in normalized directory
                        target_path = media_dir / media.filename

                        # Check if file needs to be moved
                        if media.local_path != target_path:
                            logger.info("Moving media: {} → {}", media.local_path.name, target_path.relative_to(filepath.parent))

                            # Copy file to target (overwrite if exists)
                            import shutil
                            shutil.copy2(media.local_path, target_path)

                            # Delete old file after successful copy
                            try:
                                media.local_path.unlink()
                                logger.debug("✓ Deleted old file: {}", media.local_path)
                            except Exception as e:
                                logger.warning("Could not delete old file {}: {}", media.local_path, e)

                            # Update media object to point to new location
                            old_path = media.local_path
                            media.local_path = target_path

                            # Update markdown content with new path
                            old_ref = media.original_ref
                            new_ref = f"![]({media_dir_name}/{media.filename})"

                            # Handle both wikilink and standard markdown formats
                            if old_ref != new_ref:
                                doc.content = doc.content.replace(old_ref, new_ref)
                                content_updated = True

            # Save updated markdown if paths changed
            if content_updated:
                filepath.write_text(doc.content, encoding='utf-8')
                logger.info("✓ Updated markdown with normalized media paths")

            # Handle media files
            media_map_notion = {}

            if doc.media_files:
                for media in doc.media_files:
                    # Check if file actually exists
                    if media.local_path.exists() and not str(media.local_path).startswith("/missing"):
                        # Calculate file hash
                        file_hash = notion.calculate_file_hash(media.local_path)
                        file_size = media.local_path.stat().st_size

                        # Use normalized relative path (all media is now in standard directory)
                        # Format: _<doc_name>.files/<filename>
                        media_relative_path = f"{media_dir_name}/{media.filename}"

                        # Check if we already uploaded this file (hash comparison)
                        should_upload = True
                        cached_file_id = None

                        cached_hash = file_state.get_media_hash(media_relative_path)
                        if cached_hash:
                            cached_file_id = file_state.get_media_file_upload_id(media_relative_path)

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

                        # Store in media_map (with file type)
                        # media_map format: {original_ref: (file_upload_id, file_type)}
                        media_map_notion[media.original_ref] = (file_upload_id, media.file_type)

                        # Update file state with media info
                        file_state.update_media(
                            media_relative_path,
                            file_hash=file_hash,
                            file_upload_id=file_upload_id,
                            size=file_size
                        )
                    else:
                        logger.debug("File not found, will show as callout: {}", media.filename)

            # Convert and sync to Notion
            notion_blocks = self.converter.markdown_to_notion_blocks(doc.content, media_map_notion)

            # Log media blocks for debugging
            media_blocks = [b for b in notion_blocks if b.get('type') in ['image', 'video', 'audio', 'pdf', 'file']]
            logger.info("Created {} Notion blocks ({} media blocks)", len(notion_blocks), len(media_blocks))
            for mb in media_blocks:
                block_type = mb.get('type')
                file_upload_id = mb.get(block_type, {}).get('file_upload', {}).get('id')
                logger.debug("  - {} block with file_upload_id: {}", block_type, file_upload_id)

            # Strategy for finding existing page:
            # 1. Try stored page_id from .dg file first (fast, works cross-machine via Dropbox)
            # 2. Fall back to search API if stored ID fails (handles manual page creation)
            # 3. Create new page if not found

            notion_page_id = None
            stored_page_id = file_state.get_notion_page_id()

            if stored_page_id:
                # Try to update the stored page ID
                try:
                    notion.update_page_content(stored_page_id, notion_blocks, title=doc.title)
                    notion_page_id = stored_page_id
                    logger.info("✓ Updated existing Notion page: {}", notion_page_id[:13] + "...")
                except Exception as e:
                    # Stored page ID doesn't exist or is archived, search by title
                    logger.debug("Stored page ID invalid, searching by title: {}", e)
                    existing_page_id = notion.find_page_by_title(doc.title)
                    if existing_page_id:
                        notion.update_page_content(existing_page_id, notion_blocks, title=doc.title)
                        notion_page_id = existing_page_id
                        logger.info("✓ Updated existing Notion page (found by title): {}", notion_page_id[:13] + "...")
            else:
                # No stored page ID, search by title
                existing_page_id = notion.find_page_by_title(doc.title)
                if existing_page_id:
                    notion.update_page_content(existing_page_id, notion_blocks, title=doc.title)
                    notion_page_id = existing_page_id
                    logger.info("✓ Updated existing Notion page (found by title): {}", notion_page_id[:13] + "...")

            # Create new page if not found
            if not notion_page_id:
                notion_page_id = notion.create_page(doc.title, notion_blocks)
                logger.info("✓ Created new Notion page: {}", notion_page_id[:13] + "...")

            # Sync to Quip if configured (unless --no-quip)
            quip_thread_id = None
            if route.quip_folder and creds.quip_token and not skip_quip:
                logger.info("Syncing to Quip...")
                quip = QuipClient(creds.quip_token, creds.quip_base_url)

                # Strategy: Always create NEW thread first, then delete old one
                # This ensures blobs are uploaded to the new thread
                old_thread_id = file_state.get_quip_thread_id()

                # Create NEW document first (empty, no placeholder)
                new_thread_id = quip.create_document(
                    title=doc.title,
                    content_html="",
                    folder_id=route.quip_folder
                )
                logger.info("✓ Created new Quip doc: {}", new_thread_id[:13] + "...")

                # Upload media to the NEW Quip document
                media_map_quip = {}
                media_filenames = {}  # Track filenames for alt tags
                if doc.media_files:
                    for media in doc.media_files:
                        if media.local_path.exists() and not str(media.local_path).startswith("/missing"):
                            try:
                                # Get relative path for state lookup
                                try:
                                    media_relative_path = str(media.local_path.relative_to(filepath.parent))
                                except ValueError:
                                    media_relative_path = media.filename

                                # Get the file_upload_id from media_map_notion
                                file_upload_id = media_map_notion.get(media.original_ref)
                                if isinstance(file_upload_id, tuple):
                                    file_upload_id = file_upload_id[0]  # Extract from tuple

                                if file_upload_id:
                                    # Upload media blob to the NEW document
                                    blob_id, blob_url = quip.upload_blob(new_thread_id, media.local_path)
                                    logger.info("✓ Uploaded to Quip: {}", media.filename)

                                    # Store blob URL and filename for HTML conversion
                                    media_map_quip[file_upload_id] = blob_url
                                    media_filenames[file_upload_id] = media.filename

                                    # Update file state with Quip blob ID
                                    file_state.update_media(
                                        media_relative_path,
                                        file_hash=file_state.get_media_hash(media_relative_path),  # Keep existing hash
                                        quip_blob_id=blob_id
                                    )

                            except Exception as e:
                                logger.warning("Failed to upload to Quip {}: {}", media.filename, e)

                quip_thread_id = new_thread_id

                # Convert Notion blocks to Quip HTML
                logger.debug("Building Quip HTML with {} media files", len(media_map_quip))
                logger.debug("Media map for Quip HTML conversion:")
                for fid, url in media_map_quip.items():
                    logger.debug("  {} → {}", fid[:20] + "...", url)
                quip_html = self.converter.notion_blocks_to_quip_html(notion_blocks, media_map_quip, media_filenames)

                # Log a snippet of the HTML to verify media tags
                if '<img' in quip_html:
                    logger.debug("HTML contains {} <img> tags", quip_html.count('<img'))
                    # Show first img tag
                    import re
                    img_tags = re.findall(r'<img[^>]*>', quip_html)
                    if img_tags:
                        logger.debug("First <img> tag: {}", img_tags[0])
                else:
                    logger.warning("HTML does not contain any <img> tags!")

                # Save HTML to temp file for inspection
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                    f.write(quip_html)
                    logger.debug("Generated HTML saved to: {}", f.name)

                # Update the new document with final content
                quip.update_document(quip_thread_id, quip_html)
                logger.info("✓ Updated new Quip doc with content")

                # Delete old document and update backlinks
                if old_thread_id:
                    try:
                        # Find backlinks before deleting
                        backlink_threads = quip.find_backlinks(old_thread_id)

                        # Delete old document
                        quip.delete_document(old_thread_id)
                        logger.info("✓ Deleted old Quip doc: {}", old_thread_id[:13] + "...")

                        # Update backlinks to point to new document
                        if backlink_threads:
                            quip.update_backlinks(old_thread_id, quip_thread_id, backlink_threads)
                            logger.info("✓ Updated {} backlinks", len(backlink_threads))

                    except Exception as e:
                        logger.warning("Could not delete old doc or update backlinks: {}", e)

            # Save per-file state (.dg file)
            file_state.update_notion_page_id(notion_page_id)
            if quip_thread_id:
                file_state.update_quip_thread_id(quip_thread_id)
            file_state.update_last_synced()
            file_state.save()
            logger.debug("Saved state to: {}", file_state.state_file_path)

            # Build URLs for console output
            notion_url = f"https://www.notion.so/{notion_page_id.replace('-', '')}"

            if quip_thread_id:
                # Get Quip document to extract the link
                quip_doc = quip.get_document(quip_thread_id)
                quip_url = quip_doc.get('thread', {}).get('link', f"{creds.quip_base_url}/{quip_thread_id}")

                logger.success("✓ Synced successfully!")
                logger.info("  → Notion: {}", notion_url)
                logger.info("  → Quip:   {}", quip_url)
            else:
                logger.success("✓ Synced successfully!")
                logger.info("  → Notion: {}", notion_url)
            return SyncResult(
                success=True,
                route_name=route.name,
                direction='forward',
                source_path=filepath,
                notion_page_id=notion_page_id,
                quip_thread_id=quip_thread_id,
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

    def _sync_reverse(self, filepath: Path, route: Route, skip_notion: bool = False) -> SyncResult:
        """Quip/Notion → Obsidian (optionally skip Notion sync).

        Search for document by title in Quip first, then Notion.
        Download to local Obsidian, then sync to Notion if source was Quip (unless --no-notion).
        """
        try:
            # Extract title from filename
            title = filepath.stem
            logger.info("Reverse sync: Looking for document '{}'", title)

            # Initialize credentials
            creds = self.config.get_credentials()

            # Media directory: _<doc_name>.files/
            media_dir_name = f"_{title}.files"
            media_dir = filepath.parent / media_dir_name

            quip_thread_id = None
            notion_page_id = None

            # Step 1: Try Quip first
            if route.quip_folder and creds.quip_token:
                quip = QuipClient(creds.quip_token, creds.quip_base_url)
                quip_thread_id = quip.find_document_by_title(route.quip_folder, title)

                if quip_thread_id:
                    logger.info("✓ Found in Quip: {}", quip_thread_id[:13] + "...")

                    # Download from Quip
                    quip_doc = quip.get_document(quip_thread_id)
                    quip_html = quip_doc.get('html', '')

                    # Convert HTML → Markdown with media extraction
                    markdown, blob_map = self.converter.quip_html_to_markdown(quip_html, media_dir_name)

                    # Download all blobs
                    logger.info("Downloading {} media files from Quip", len(blob_map))
                    media_files_state = {}

                    for blob_id, filename in blob_map.items():
                        output_path = media_dir / filename
                        quip.download_blob(quip_thread_id, blob_id, output_path)

                        # Calculate hash
                        file_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
                        media_files_state[f"{media_dir_name}/{filename}"] = {
                            'hash': file_hash,
                            'quip_blob_id': blob_id,
                            'size': str(output_path.stat().st_size)
                        }

                    # Save to Obsidian
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(markdown, encoding='utf-8')
                    logger.info("✓ Saved to Obsidian: {}", filepath)

                    # Create .dg file
                    from doc_genie.file_state import FileState
                    file_state = FileState(filepath)
                    file_state.update_quip_thread_id(quip_thread_id)
                    file_state.update_last_synced()

                    # Update media metadata
                    for media_path, media_info in media_files_state.items():
                        file_state.update_media(
                            media_path,
                            file_hash=media_info['hash'],
                            quip_blob_id=media_info.get('quip_blob_id'),
                            size=int(media_info['size'])
                        )

                    file_state.save()
                    logger.info("✓ Saved .dg file: {}", file_state.state_file_path)

                    # Now run forward sync to push to Notion (unless --no-notion)
                    if not skip_notion:
                        logger.info("Running forward sync to Notion...")
                        forward_result = self._sync_forward(filepath, route, skip_quip=True)

                        return SyncResult(
                            success=True,
                            route_name=route.name,
                            direction='reverse',
                            source_path=filepath,
                            notion_page_id=forward_result.notion_page_id,
                            quip_thread_id=quip_thread_id,
                            media_count=len(blob_map)
                        )
                    else:
                        logger.info("Skipping Notion sync (--no-notion)")
                        return SyncResult(
                            success=True,
                            route_name=route.name,
                            direction='reverse',
                            source_path=filepath,
                            quip_thread_id=quip_thread_id,
                            media_count=len(blob_map)
                        )

            # Step 2: If not in Quip, try Notion
            if not quip_thread_id and creds.notion_token:
                notion = NotionClient(creds.notion_token, route.notion_database)
                notion_page_id = notion.find_page_by_title(title)

                if notion_page_id:
                    logger.info("✓ Found in Notion: {}", notion_page_id[:13] + "...")

                    # Download from Notion
                    blocks = notion.get_blocks(notion_page_id)

                    # Convert blocks → Markdown
                    markdown = self.converter.notion_blocks_to_markdown(blocks)

                    # Extract and download media
                    media_files_state = {}
                    media_count = 0

                    for block in blocks:
                        block_type = block.get('type')
                        if block_type in ['image', 'video', 'audio', 'pdf', 'file']:
                            media_data = block.get(block_type, {})

                            # Get file URL
                            file_url = media_data.get('file', {}).get('url') or \
                                      media_data.get('external', {}).get('url')

                            if file_url:
                                # Generate filename
                                file_upload_id = media_data.get('file_upload', {}).get('id', '')
                                filename = f"{block_type}_{media_count}.{file_url.split('.')[-1].split('?')[0]}"

                                # Download file
                                output_path = media_dir / filename
                                media_dir.mkdir(parents=True, exist_ok=True)
                                notion.download_file(file_url, output_path)

                                # Calculate hash
                                file_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
                                media_files_state[f"{media_dir_name}/{filename}"] = {
                                    'hash': file_hash,
                                    'file_upload_id': file_upload_id,
                                    'size': str(output_path.stat().st_size)
                                }

                                # Replace URL in markdown with local path
                                markdown = markdown.replace(file_url, f"{media_dir_name}/{filename}")
                                media_count += 1

                    logger.info("Downloaded {} media files from Notion", media_count)

                    # Save to Obsidian
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(markdown, encoding='utf-8')
                    logger.info("✓ Saved to Obsidian: {}", filepath)

                    # Create .dg file
                    from doc_genie.file_state import FileState
                    file_state = FileState(filepath)
                    file_state.update_notion_page_id(notion_page_id)
                    file_state.update_last_synced()

                    # Update media metadata
                    for media_path, media_info in media_files_state.items():
                        file_state.update_media(
                            media_path,
                            file_hash=media_info['hash'],
                            file_upload_id=media_info.get('file_upload_id'),
                            size=int(media_info['size'])
                        )

                    file_state.save()
                    logger.info("✓ Saved .dg file: {}", file_state.state_file_path)

                    return SyncResult(
                        success=True,
                        route_name=route.name,
                        direction='reverse',
                        source_path=filepath,
                        notion_page_id=notion_page_id,
                        media_count=media_count
                    )

            # Step 3: Not found anywhere
            raise ValueError(f"Document '{title}' not found in Quip or Notion")

        except Exception as e:
            logger.exception("Reverse sync failed: {}", e)
            return SyncResult(
                success=False,
                route_name=route.name,
                direction='reverse',
                source_path=filepath,
                error=str(e)
            )

    def _calculate_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()
