"""Obsidian platform client for reading and writing markdown files."""

from pathlib import Path
from typing import List, Optional
from loguru import logger

from doc_genie.document import Document, MediaFile
from doc_genie.media import MediaHandler


class ObsidianClient:
    """Read and write Obsidian markdown files."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.media_handler = MediaHandler(vault_path)
        logger.debug("ObsidianClient initialized: vault={}", vault_path)

    def read_document(self, filepath: Path) -> Document:
        """Read markdown file and extract metadata."""
        logger.info("Reading document from Obsidian: {}", filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"Document not found: {filepath}")

        try:
            content = filepath.read_text(encoding='utf-8')
            logger.debug("Read {} characters from {}", len(content), filepath.name)
        except Exception as e:
            logger.error("Failed to read document: {}", e)
            raise

        # Extract title (from # heading or filename)
        title = self._extract_title(content) or filepath.stem

        # Extract media files
        media_files = self.media_handler.extract_from_markdown(content, filepath)

        logger.info("Document loaded: title={}, media_count={}", title, len(media_files))

        return Document(
            filepath=filepath,
            title=title,
            content=content,
            media_files=media_files
        )

    def write_document(self, filepath: Path, title: str, content: str, media_files: List[MediaFile]):
        """Write markdown file to vault."""
        logger.info("Writing document to Obsidian: {}", filepath)

        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Write content
            filepath.write_text(content, encoding='utf-8')
            logger.debug("Wrote {} characters to {}", len(content), filepath.name)

            # Save media files to vault
            if media_files:
                media_dir = filepath.parent / '_media'
                media_dir.mkdir(exist_ok=True)

                for media in media_files:
                    target_path = media_dir / media.filename
                    if not target_path.exists():
                        # Copy/download media file
                        target_path.write_bytes(media.local_path.read_bytes())
                        logger.debug("Saved media file: {}", media.filename)

            logger.info("Document written successfully: {}", filepath.name)

        except Exception as e:
            logger.error("Failed to write document: {}", e)
            raise

    def _extract_title(self, content: str) -> Optional[str]:
        """Extract title from first # heading."""
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('# '):
                title = line[2:].strip()
                logger.debug("Extracted title from heading: {}", title)
                return title
        return None

    def get_relative_path(self, filepath: Path) -> str:
        """Get path relative to vault."""
        try:
            rel_path = str(filepath.relative_to(self.vault_path))
            logger.debug("Relative path: {}", rel_path)
            return rel_path
        except ValueError as e:
            logger.error("Path is not relative to vault: {}", e)
            raise ValueError(f"File {filepath} is not in vault {self.vault_path}")
