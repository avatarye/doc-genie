"""Notion platform client wrapper around notion-sdk-py."""

from pathlib import Path
from typing import List, Dict, Optional
import hashlib
from loguru import logger
from notion_client import Client
import requests


class NotionClient:
    """Wrapper around notion-sdk-py with media upload support."""

    def __init__(self, api_token: str, database_id: str):
        self.client = Client(auth=api_token)
        self.api_token = api_token  # Store for direct API calls
        self.database_id = database_id
        logger.debug("NotionClient initialized: database={}", database_id)

    def find_page_by_title(self, title: str) -> Optional[str]:
        """
        Find page in database by exact title match.

        Args:
            title: Page title to search for

        Returns:
            Page ID if found, None otherwise
        """
        try:
            # Search for pages with matching title in this database
            # Note: Notion search is case-insensitive and fuzzy
            response = self.client.search(
                query=title,
                filter={"value": "page", "property": "object"}
            )

            results = response.get('results', [])

            # Filter to only pages in our database with exact title match
            for page in results:
                # Check if page is in our database
                parent = page.get('parent', {})
                if parent.get('type') == 'database_id' and parent.get('database_id') == self.database_id:
                    # Check for exact title match
                    page_title = ''
                    title_prop = page.get('properties', {}).get('Name', {})
                    if title_prop.get('type') == 'title':
                        title_array = title_prop.get('title', [])
                        page_title = ''.join([t.get('text', {}).get('content', '') for t in title_array])

                    if page_title == title:
                        page_id = page['id']
                        logger.info("Found existing page by title '{}': {}", title, page_id[:13] + "...")
                        return page_id

            logger.debug("No existing page found with title: {}", title)
            return None

        except Exception as e:
            logger.warning("Failed to search for title '{}': {}", title, e)
            return None

    def create_page(self, title: str, blocks: List[Dict]) -> str:
        """Create page in database."""
        try:
            # Limit blocks to avoid API limits (max 100 children per request)
            children = blocks[:100] if len(blocks) > 100 else blocks

            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties={
                    "Name": {"title": [{"text": {"content": title}}]}
                },
                children=children
            )
            page_id = response['id']

            # If there are more blocks, append them
            if len(blocks) > 100:
                self.append_blocks(page_id, blocks[100:])

            return page_id

        except Exception as e:
            logger.error("Failed to create Notion page: {}", e)
            raise

    def archive_page(self, page_id: str):
        """Archive (soft delete) a page."""
        try:
            self.client.pages.update(page_id, archived=True)
        except Exception as e:
            logger.error("Failed to archive page: {}", e)
            raise

    def update_page_content(self, page_id: str, blocks: List[Dict], title: Optional[str] = None):
        """
        Replace page content using erase_content API (fast, preserves page ID).

        Uses Notion's erase_content parameter to clear all blocks atomically,
        then appends new content. Much faster than deleting blocks one-by-one.

        Args:
            page_id: Notion page ID
            blocks: New blocks to add
            title: Optional new title (if None, title unchanged)
        """
        logger.info("Updating Notion page: page_id={}, blocks={}", page_id[:13] + "...", len(blocks))

        try:
            # Step 1: Erase all existing content atomically
            # Uses the erase_content parameter added in Notion API 2024
            update_payload = {"erase_content": True}
            if title:
                update_payload["properties"] = {
                    "Name": {"title": [{"text": {"content": title}}]}
                }

            self.client.pages.update(page_id, **update_payload)
            logger.debug("✓ Erased existing content")

            # Step 2: Append new blocks (in batches of 100)
            self.append_blocks(page_id, blocks)
            logger.info("✓ Page content updated successfully")

        except Exception as e:
            logger.error("Failed to update Notion page: {}", e)
            raise

    def update_page_content_slow(self, page_id: str, blocks: List[Dict]):
        """
        DEPRECATED: Replace page content (delete blocks one-by-one).

        This method is slow - use update_page_content() instead which uses
        the erase_content API parameter for atomic deletion.
        """
        logger.warning("Using DEPRECATED slow update method - use update_page_content() instead")
        logger.info("Updating Notion page content: page_id={}, blocks={}", page_id, len(blocks))

        try:
            # Get existing blocks
            existing = self.client.blocks.children.list(page_id)
            existing_blocks = existing['results']
            logger.debug("Found {} existing blocks to delete", len(existing_blocks))

            # Delete all blocks (slow - one API call per block)
            for i, block in enumerate(existing_blocks):
                if i % 10 == 0:
                    logger.debug("Deleting block {}/{}", i, len(existing_blocks))
                try:
                    self.client.blocks.delete(block['id'])
                except Exception as e:
                    logger.warning("Failed to delete block {}: {}", block['id'], e)

            # Add new blocks
            self.append_blocks(page_id, blocks)
            logger.info("Page content updated successfully")

        except Exception as e:
            logger.error("Failed to update Notion page: {}", e)
            raise

    def append_blocks(self, block_id: str, blocks: List[Dict]):
        """Append blocks to a page or block (handles batching)."""
        # Notion API limits to 100 children per request
        batch_size = 100
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i + batch_size]
            try:
                self.client.blocks.children.append(block_id, children=batch)
                logger.debug("Appended {} blocks to {}", len(batch), block_id)
            except Exception as e:
                logger.error("Failed to append blocks: {}", e)
                raise

    def get_blocks(self, page_id: str) -> List[Dict]:
        """Fetch all blocks from page."""
        logger.debug("Fetching blocks from page: {}", page_id)

        try:
            blocks = []
            has_more = True
            start_cursor = None

            while has_more:
                response = self.client.blocks.children.list(
                    page_id,
                    start_cursor=start_cursor
                )
                blocks.extend(response['results'])
                has_more = response.get('has_more', False)
                start_cursor = response.get('next_cursor')

            logger.debug("Fetched {} blocks from page", len(blocks))
            return blocks

        except Exception as e:
            logger.error("Failed to fetch blocks: {}", e)
            raise

    @staticmethod
    def calculate_file_hash(file_path: Path) -> str:
        """Calculate SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read in 8MB chunks
            for byte_block in iter(lambda: f.read(8 * 1024 * 1024), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def upload_file(self, file_path: Path) -> str:
        """
        Upload file to Notion using the official file upload API.

        Returns the file_upload_id to be used in blocks.

        Supports:
        - Simple upload for files <= 20MB
        - Multi-part upload for files > 20MB (uses upload_url from Notion)
        """
        if not file_path.exists():
            logger.error("File does not exist: {}", file_path)
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size

        # Choose upload method based on file size
        if file_size > 20 * 1024 * 1024:
            return self._upload_file_multipart(file_path, file_size)
        else:
            return self._upload_file_simple(file_path, file_size)

    def _upload_file_simple(self, file_path: Path, file_size: int) -> str:
        """Upload file using simple upload (for files <= 20MB)."""
        try:
            # Determine content type
            import mimetypes
            content_type, _ = mimetypes.guess_type(file_path.name)
            if not content_type:
                # Default to binary
                content_type = "application/octet-stream"

            logger.debug("Content type: {}", content_type)

            # Step 1: Create file upload object
            logger.debug("Step 1: Creating file upload object")

            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }

            create_payload = {
                "filename": file_path.name,
                "content_type": content_type
            }

            create_response = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers=headers,
                json=create_payload
            )
            create_response.raise_for_status()
            upload_data = create_response.json()

            file_upload_id = upload_data['id']
            logger.debug("File upload ID: {}", file_upload_id)

            # Step 2: Send file contents
            logger.debug("Step 2: Sending file contents")

            send_headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Notion-Version": "2022-06-28"
            }

            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f, content_type)}
                send_response = requests.post(
                    f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send",
                    headers=send_headers,
                    files=files
                )
                send_response.raise_for_status()

            # Return the file_upload_id (not a URL)
            return file_upload_id

        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error uploading file: {} - {}", e, e.response.text if hasattr(e, 'response') else '')
            return ""
        except Exception as e:
            logger.error("Failed to upload file {}: {}", file_path.name, e)
            return ""

    def _upload_file_multipart(self, file_path: Path, file_size: int) -> str:
        """Upload file using multi-part upload (for files > 20MB).

        Based on: https://developers.notion.com/docs/sending-larger-files
        """
        try:
            # Determine content type
            import mimetypes
            content_type, _ = mimetypes.guess_type(file_path.name)
            if not content_type:
                content_type = "application/octet-stream"

            # Calculate number of parts (using 10MB part size as recommended)
            part_size = 10 * 1024 * 1024  # 10MB
            number_of_parts = (file_size + part_size - 1) // part_size

            logger.debug("Content type: {}", content_type)
            logger.debug("File size: {:.2f} MB, splitting into {} parts of {} MB each",
                        file_size / (1024 * 1024), number_of_parts, part_size / (1024 * 1024))

            # Step 1: Create file upload object with multi-part mode
            logger.debug("Step 1: Creating multi-part file upload object")

            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }

            create_payload = {
                "filename": file_path.name,
                "content_type": content_type,
                "mode": "multi_part",  # Correct parameter name
                "number_of_parts": number_of_parts
            }

            create_response = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers=headers,
                json=create_payload
            )
            create_response.raise_for_status()
            upload_data = create_response.json()

            file_upload_id = upload_data['id']
            upload_url = upload_data.get('upload_url')

            if not upload_url:
                logger.error("No upload_url in response: {}", upload_data)
                return ""

            logger.debug("File upload ID: {}, upload_url: {}", file_upload_id, upload_url[:50] + "...")

            # Step 2: Upload file parts
            logger.debug("Step 2: Uploading {} parts", number_of_parts)

            with open(file_path, 'rb') as f:
                for part_num in range(1, number_of_parts + 1):
                    # Read chunk
                    chunk = f.read(part_size)
                    if not chunk:
                        break

                    logger.debug("Uploading part {}/{}...", part_num, number_of_parts)

                    # Upload part with part_number in form data (not query params!)
                    files = {
                        'file': (file_path.name, chunk, content_type)
                    }
                    data = {
                        'part_number': str(part_num)  # In form data, not URL params
                    }

                    # Upload_url still requires auth headers
                    upload_headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2022-06-28"
                    }

                    send_response = requests.post(
                        upload_url,
                        headers=upload_headers,
                        files=files,
                        data=data
                    )
                    send_response.raise_for_status()
                    logger.debug("Part {}/{} uploaded successfully", part_num, number_of_parts)

            # Step 3: Complete multi-part upload
            logger.debug("Step 3: Completing multi-part upload")

            complete_response = requests.post(
                f"https://api.notion.com/v1/file_uploads/{file_upload_id}/complete",
                headers=headers
            )
            complete_response.raise_for_status()

            return file_upload_id

        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error uploading file (multi-part): {} - {}", e, e.response.text if hasattr(e, 'response') else '')
            return ""
        except Exception as e:
            logger.error("Failed to upload file (multi-part) {}: {}", file_path.name, e)
            return ""

    def create_external_file_block(self, url: str, caption: str = "") -> Dict:
        """Create an image block with external URL."""
        return {
            "type": "image",
            "image": {
                "type": "external",
                "external": {
                    "url": url
                },
                "caption": [{"type": "text", "text": {"content": caption}}] if caption else []
            }
        }

    def download_file(self, file_url: str, output_path: Path):
        """Download file from Notion URL."""
        logger.info("Downloading file from Notion: {}", file_url)

        try:
            response = requests.get(file_url)
            response.raise_for_status()
            output_path.write_bytes(response.content)
            logger.debug("Downloaded file to: {}", output_path)

        except Exception as e:
            logger.error("Failed to download file: {}", e)
            raise
