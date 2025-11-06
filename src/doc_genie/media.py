"""Media file extraction and handling."""

import re
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

from doc_genie.document import MediaFile


class MediaHandler:
    """Extract and manage media files from documents."""

    # Regex patterns for both link types
    WIKILINK_PATTERN = r'!\[\[([^\]]+)\]\]'  # ![[image.png]]
    MARKDOWN_PATTERN = r'!\[([^\]]*)\]\(<?([^>\)]+)>?\)'  # ![alt](path) or ![alt](<path>)

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        logger.debug("MediaHandler initialized: vault={}", vault_path)

    def extract_from_markdown(self, content: str, doc_path: Path) -> List[MediaFile]:
        """Extract all media files from markdown content."""
        media_files = []

        # Extract wikilinks: ![[image.png]]
        for match in re.finditer(self.WIKILINK_PATTERN, content):
            ref = match.group(1)
            local_path = self._resolve_wikilink(ref, doc_path)
            if local_path:
                media_files.append(self._create_media_file(match.group(0), local_path))
            else:
                # Create a placeholder MediaFile for missing files
                logger.debug("Could not resolve wikilink, creating placeholder: {}", ref)
                media_files.append(self._create_placeholder_media_file(match.group(0), ref))

        # Extract standard markdown: ![alt](path)
        for match in re.finditer(self.MARKDOWN_PATTERN, content):
            path = match.group(2)
            # Skip URLs
            if path.startswith(('http://', 'https://')):
                logger.debug("Skipping external URL: {}", path)
                continue
            local_path = self._resolve_relative_path(path, doc_path)
            if local_path:
                media_files.append(self._create_media_file(match.group(0), local_path))
            else:
                # Create placeholder for missing files
                logger.debug("Could not resolve media path, creating placeholder: {}", path)
                media_files.append(self._create_placeholder_media_file(match.group(0), path))

        logger.info("Extracted {} media references from {}", len(media_files), doc_path.name)
        return media_files

    def _resolve_wikilink(self, ref: str, doc_path: Path) -> Optional[Path]:
        """Resolve wikilink to absolute path (search vault)."""
        # Try relative to document first
        relative = doc_path.parent / ref
        if relative.exists():
            logger.debug("Resolved wikilink relative to doc: {}", ref)
            return relative.resolve()

        # Search vault root
        vault_file = self.vault_path / ref
        if vault_file.exists():
            logger.debug("Resolved wikilink in vault root: {}", ref)
            return vault_file.resolve()

        # Search common media folders
        for media_folder in ['_media', 'assets', 'images', 'attachments', 'files']:
            media_path = self.vault_path / media_folder / ref
            if media_path.exists():
                logger.debug("Resolved wikilink in {}: {}", media_folder, ref)
                return media_path.resolve()

        # Try recursive search in vault (for nested folders)
        try:
            for file_path in self.vault_path.rglob(ref):
                if file_path.is_file():
                    logger.debug("Resolved wikilink via recursive search: {}", ref)
                    return file_path.resolve()
        except Exception as e:
            logger.error("Error during recursive search: {}", e)

        return None

    def _resolve_relative_path(self, path: str, doc_path: Path) -> Optional[Path]:
        """Resolve relative path to absolute."""
        if path.startswith('/'):
            # Absolute path from vault root
            resolved = self.vault_path / path.lstrip('/')
        else:
            # Relative to document
            resolved = (doc_path.parent / path).resolve()

        if resolved.exists():
            logger.debug("Resolved relative path: {}", path)
            return resolved
        else:
            logger.debug("Path does not exist: {}", resolved)
            return None

    def _create_media_file(self, original_ref: str, local_path: Path) -> MediaFile:
        """Create MediaFile object."""
        ext = local_path.suffix.lower()

        # Determine file type
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp']:
            file_type = 'image'
        elif ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
            file_type = 'video'
        elif ext in ['.pdf']:
            file_type = 'pdf'
        else:
            file_type = 'file'

        return MediaFile(
            original_ref=original_ref,
            local_path=local_path,
            filename=local_path.name,
            file_type=file_type
        )

    def _create_placeholder_media_file(self, original_ref: str, filename: str) -> MediaFile:
        """Create MediaFile object for missing file (placeholder)."""
        # Use a dummy path for missing files
        dummy_path = Path("/missing") / filename

        # Guess file type from extension
        ext = Path(filename).suffix.lower()
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp']:
            file_type = 'image'
        elif ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
            file_type = 'video'
        elif ext in ['.pdf']:
            file_type = 'pdf'
        else:
            file_type = 'file'

        return MediaFile(
            original_ref=original_ref,
            local_path=dummy_path,
            filename=filename,
            file_type=file_type
        )

    def normalize_wikilinks(self, content: str) -> str:
        """Convert ![[image.png]] to ![](image.png) for processing."""
        def replace_wikilink(match):
            filename = match.group(1)
            return f'![]({filename})'

        return re.sub(self.WIKILINK_PATTERN, replace_wikilink, content)

    def replace_media_refs(self, content: str, media_map: Dict[str, str]) -> str:
        """Replace media references with new URLs/paths."""
        result = content
        for original_ref, new_ref in media_map.items():
            result = result.replace(original_ref, new_ref)
        return result
