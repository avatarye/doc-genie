"""Document models for Doc Genie."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class MediaFile:
    """Represents an embedded media file in a document."""
    original_ref: str       # Original markdown reference: ![[image.png]] or ![](path)
    local_path: Path        # Absolute path to file
    filename: str           # Just the filename
    file_type: str          # image, video, pdf, etc.

    @property
    def extension(self) -> str:
        """Get file extension."""
        return self.local_path.suffix.lower()

    def is_image(self) -> bool:
        """Check if file is an image."""
        return self.extension in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp']

    def is_video(self) -> bool:
        """Check if file is a video."""
        return self.extension in ['.mp4', '.mov', '.avi', '.webm', '.mkv']


@dataclass
class Document:
    """Platform-agnostic document representation."""
    filepath: Path
    title: str
    content: str            # Raw content (markdown for Obsidian, HTML for Quip)
    media_files: List[MediaFile]
    metadata: Optional[dict] = None

    @property
    def filename(self) -> str:
        """Get document filename."""
        return self.filepath.name


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    route_name: str
    direction: str  # 'forward' or 'reverse'
    source_path: Path
    notion_page_id: Optional[str] = None
    quip_thread_id: Optional[str] = None
    error: Optional[str] = None
    media_count: int = 0
