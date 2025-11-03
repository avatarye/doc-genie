"""Quip platform client wrapper."""

from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from doc_genie.quip_api import QuipAPI


class QuipClient:
    """Wrapper around Quip API for document sync."""

    def __init__(self, api_token: str, base_url: str = "https://quip-amazon.com"):
        # Use 5 minute timeout for large video uploads (default is only 10s)
        self.client = QuipAPI(access_token=api_token, base_url=base_url, request_timeout=300)
        self.base_url = base_url
        logger.debug("QuipClient initialized: base_url={}", base_url)

    def find_document_by_title(self, folder_id: str, title: str) -> Optional[str]:
        """
        Find document in folder by exact title match.

        Args:
            folder_id: Quip folder ID to search in
            title: Document title to search for

        Returns:
            Thread ID if found, None otherwise
        """
        try:
            # Get folder contents
            folder = self.client.get_folder(folder_id)
            thread_ids = [child['thread_id'] for child in folder.get('children', [])
                         if child.get('thread_id')]

            if not thread_ids:
                logger.debug("No documents in folder: {}", folder_id)
                return None

            # Get thread details to check titles
            threads_data = self.client.get_threads(thread_ids)
            for thread_id, thread_info in threads_data.items():
                if thread_info.get('thread', {}).get('title') == title:
                    logger.info("Found existing Quip doc by title '{}': {}", title, thread_id[:13] + "...")
                    return thread_id

            logger.debug("No existing Quip doc found with title: {}", title)
            return None

        except Exception as e:
            logger.warning("Failed to search folder for title '{}': {}", title, e)
            return None

    def create_document(self, title: str, content_html: str, folder_id: Optional[str] = None) -> str:
        """Create a new Quip document.

        Args:
            title: Document title
            content_html: HTML content
            folder_id: Optional folder ID to create document in

        Returns:
            Thread ID of created document
        """
        try:
            # Create document
            response = self.client.new_document(
                content=content_html,
                title=title,
                member_ids=[folder_id] if folder_id else None
            )

            thread_id = response['thread']['id']
            logger.info("Quip document created: thread_id={}", thread_id)
            return thread_id

        except Exception as e:
            logger.error("Failed to create Quip document: {}", e)
            raise

    def delete_document(self, thread_id: str):
        """Delete a Quip document.

        Args:
            thread_id: Quip thread ID to delete
        """
        try:
            self.client.delete_thread(thread_id)
            logger.debug("Deleted Quip document: {}", thread_id[:13] + "...")
        except Exception as e:
            logger.error("Failed to delete Quip document: {}", e)
            raise

    def update_document(self, thread_id: str, content_html: str):
        """Update existing Quip document by deleting placeholder and appending content.

        Args:
            thread_id: Quip thread ID
            content_html: New HTML content
        """
        try:
            # Fetch existing document to get the first section ID
            thread = self.client.get_thread(thread_id)
            existing_html = thread.get('html', '')

            # Extract first section ID from HTML (sections have id='...')
            import re
            section_ids = re.findall(r"id='([^']+)'", existing_html)

            # Delete the placeholder section
            if section_ids:
                self.client.edit_document(
                    thread_id=thread_id,
                    content="",
                    operation=self.client.DELETE_SECTION,
                    section_id=section_ids[0]
                )
                logger.debug("Deleted placeholder section")

            # Append all new content
            self.client.edit_document(
                thread_id=thread_id,
                content=content_html,
                operation=self.client.APPEND
            )
            logger.debug("Appended new content")

        except Exception as e:
            logger.error("Failed to update Quip document: {}", e)
            raise

    def find_backlinks(self, thread_id: str) -> list[str]:
        """Find documents that link to this thread.

        Args:
            thread_id: Quip thread ID to search for

        Returns:
            List of thread IDs that contain links to this thread
        """
        try:
            # Search for documents containing this thread ID
            # This will find documents with links like quip.com/{thread_id}
            results = self.client.get_matching_threads(query=thread_id, count=100)

            backlink_threads = []
            for thread_data in results:
                found_thread_id = thread_data.get('thread', {}).get('id')
                if found_thread_id and found_thread_id != thread_id:
                    backlink_threads.append(found_thread_id)

            logger.info("Found {} documents linking to {}", len(backlink_threads), thread_id[:13] + "...")
            return backlink_threads

        except Exception as e:
            logger.warning("Failed to find backlinks: {}", e)
            return []

    def update_backlinks(self, old_thread_id: str, new_thread_id: str, backlink_threads: list[str]):
        """Update backlinks from old thread ID to new thread ID.

        Args:
            old_thread_id: Old Quip thread ID
            new_thread_id: New Quip thread ID
            backlink_threads: List of thread IDs containing backlinks
        """
        if not backlink_threads:
            return

        logger.info("Updating backlinks in {} documents", len(backlink_threads))

        for thread_id in backlink_threads:
            try:
                # Fetch document HTML
                thread = self.client.get_thread(thread_id)
                html = thread.get('html', '')

                # Replace old thread ID with new one
                # Handles both full URLs and relative paths
                import re
                updated_html = re.sub(
                    rf'/({old_thread_id})',
                    rf'/\1'.replace(old_thread_id, new_thread_id),
                    html
                )
                updated_html = re.sub(
                    rf'(quip(?:-amazon)?\.com/)({old_thread_id})',
                    rf'\1{new_thread_id}',
                    updated_html
                )

                if updated_html != html:
                    # Extract first section ID and replace content
                    section_ids = re.findall(r"id='([^']+)'", html)
                    if section_ids:
                        # Use REPLACE_SECTION on the first section with updated HTML
                        self.client.edit_document(
                            thread_id=thread_id,
                            content=updated_html,
                            operation=self.client.REPLACE_SECTION,
                            section_id=section_ids[0]
                        )
                        logger.info("✓ Updated backlinks in: {}", thread_id[:13] + "...")

            except Exception as e:
                logger.warning("Failed to update backlinks in {}: {}", thread_id[:13] + "...", e)

    def replace_document_with_backlink_update(self, old_thread_id: str, title: str,
                                             content_html: str, folder_id: str) -> str:
        """Replace document using delete+create strategy with backlink updates.

        This preserves external references by finding and updating all backlinks.

        Strategy:
        1. Find all documents linking to the old thread
        2. Delete old document, create new one
        3. Update all backlinks with new thread ID

        Args:
            old_thread_id: Current thread ID to replace
            title: Document title
            content_html: New HTML content
            folder_id: Folder to create new document in

        Returns:
            New thread ID
        """
        try:
            # Step 1: Find backlinks before deleting
            backlink_threads = self.find_backlinks(old_thread_id)

            # Step 2: Delete old document
            try:
                self.delete_document(old_thread_id)
                logger.debug("Deleted old document: {}", old_thread_id[:13] + "...")
            except Exception as e:
                logger.warning("Could not delete old document: {}", e)

            # Step 3: Create new document
            new_thread_id = self.create_document(title, content_html, folder_id)
            logger.info("✓ Created new document: {}", new_thread_id[:13] + "...")

            # Step 4: Update backlinks
            if backlink_threads:
                self.update_backlinks(old_thread_id, new_thread_id, backlink_threads)
                logger.info("✓ Updated {} backlinks", len(backlink_threads))

            return new_thread_id

        except Exception as e:
            logger.error("Failed to replace document with backlink updates: {}", e)
            raise

    def upload_blob(self, thread_id: str, file_path: Path) -> tuple[str, str]:
        """Upload file as blob to Quip thread.

        Args:
            thread_id: Quip thread ID to upload to
            file_path: Path to file to upload

        Returns:
            Tuple of (blob_id, blob_url) from Quip API response
        """
        if not file_path.exists():
            logger.error("File does not exist: {}", file_path)
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        # Warn for large files
        if size_mb > 50:
            logger.warning("Uploading large file: {} ({:.2f} MB) - this may take several minutes",
                         file_path.name, size_mb)
        else:
            logger.info("Uploading blob to Quip: {} ({:.2f} MB)", file_path.name, size_mb)

        try:
            with open(file_path, 'rb') as f:
                blob_data = f.read()

            response = self.client.put_blob(
                thread_id=thread_id,
                blob=blob_data,
                name=file_path.name
            )

            # Log full response to debug
            logger.debug("put_blob response: {}", response)

            # Response format: {"url": "...", "id": "..."}
            blob_id = response.get('id')
            blob_url = response.get('url')

            if not blob_id or not blob_url:
                logger.error("Missing blob ID or URL in response: {}", response)
                raise ValueError(f"Blob upload failed - incomplete response: {response}")

            logger.debug("✓ Blob uploaded: id={}, url={}", blob_id, blob_url)
            return (blob_id, blob_url)

        except TimeoutError as e:
            logger.error("Upload timed out for {}: {} - file size: {:.2f} MB",
                        file_path.name, e, size_mb)
            raise
        except Exception as e:
            logger.error("Failed to upload blob {}: {}", file_path.name, e)
            raise

    def get_blob_url(self, thread_id: str, blob_id: str) -> str:
        """Get URL for a blob (DEPRECATED - use URL from upload_blob response instead).

        Args:
            thread_id: Quip thread ID
            blob_id: Blob ID

        Returns:
            Blob URL
        """
        # NOTE: This method is deprecated. The correct URL is returned by put_blob API.
        # Keeping for backwards compatibility but should use URL from upload_blob instead.
        return f"{self.base_url}/blob/{thread_id}/{blob_id}"

    def get_document(self, thread_id: str) -> Dict:
        """Get document content and metadata.

        Args:
            thread_id: Quip thread ID

        Returns:
            Document data including HTML content
        """
        try:
            thread = self.client.get_thread(thread_id)
            return thread

        except Exception as e:
            logger.error("Failed to get Quip document: {}", e)
            raise
