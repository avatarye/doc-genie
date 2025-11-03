"""Format converter between Markdown, Notion blocks, and Quip HTML."""

from typing import List, Dict
from pathlib import Path
from loguru import logger
import mistune
import re
from bs4 import BeautifulSoup


class MarkdownConverter:
    """Convert between Markdown, Notion blocks, and Quip HTML."""

    def markdown_to_notion_blocks(self, markdown: str, media_map: Dict[str, str] = None) -> List[Dict]:
        """Convert markdown to Notion block objects."""
        if media_map is None:
            media_map = {}

        blocks = []

        # Parse markdown line by line for simplicity
        # This is a simplified parser - for production, use a proper AST parser
        lines = markdown.split('\n')
        i = 0
        total_lines = len(lines)

        logger.debug("Parsing {} lines of markdown", total_lines)

        while i < total_lines:
            # Progress logging every 50 lines
            if i > 0 and i % 50 == 0:
                logger.debug("Parsing progress: {}/{} lines", i, total_lines)

            line = lines[i]

            # Skip empty lines
            if not line.strip():
                i += 1
                continue

            # Headings
            if line.startswith('#'):
                block = self._parse_heading(line)
                if block:
                    blocks.append(block)
                i += 1

            # Code blocks
            elif line.startswith('```'):
                code_blocks, lines_consumed = self._parse_code_block(lines[i:])
                if code_blocks:
                    blocks.extend(code_blocks)  # extend since it's a list now
                i += max(lines_consumed, 1)  # Always increment at least 1

            # Bullet lists
            elif line.strip().startswith(('- ', '* ', '+ ')):
                list_block, lines_consumed = self._parse_bullet_list(lines[i:])
                if list_block:
                    blocks.append(list_block)
                i += max(lines_consumed, 1)  # Always increment at least 1

            # Numbered lists
            elif re.match(r'^\d+\.\s', line.strip()):
                list_block, lines_consumed = self._parse_numbered_list(lines[i:])
                if list_block:
                    blocks.append(list_block)
                i += max(lines_consumed, 1)  # Always increment at least 1

            # Tables (detect by | character)
            elif '|' in line and i + 1 < total_lines:
                table_block, lines_consumed = self._parse_table(lines[i:])
                if table_block:
                    blocks.append(table_block)
                    i += max(lines_consumed, 1)
                else:
                    # Not a table, parse as paragraph
                    para_block, lines_consumed = self._parse_paragraph(lines[i:])
                    if para_block:
                        blocks.append(para_block)
                    i += max(lines_consumed, 1)

            # Images
            elif '![' in line:
                image_blocks = self._parse_images(line, media_map)
                blocks.extend(image_blocks)
                i += 1

            # Regular paragraph
            else:
                para_block, lines_consumed = self._parse_paragraph(lines[i:])
                if para_block:
                    blocks.append(para_block)
                i += max(lines_consumed, 1)  # Always increment at least 1

        return blocks

    def _parse_heading(self, line: str) -> Dict:
        """Parse heading line."""
        # Count # symbols
        level = 0
        for char in line:
            if char == '#':
                level += 1
            else:
                break

        # Notion supports headings 1-3
        level = min(level, 3)
        text = line[level:].strip()

        return {
            "type": f"heading_{level}",
            f"heading_{level}": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            }
        }

    def _parse_paragraph(self, lines: List[str]) -> tuple[Dict, int]:
        """Parse paragraph (consume lines until empty line)."""
        if not lines:
            return None, 1

        para_lines = []
        consumed = 0

        for line in lines:
            if not line.strip():
                break
            # Stop at special syntax (check stripped version for lists)
            stripped = line.strip()
            if line.startswith(('#', '```')) or \
               stripped.startswith(('-', '*', '+')) or \
               re.match(r'^\d+\.\s', stripped):
                break
            para_lines.append(line)
            consumed += 1

        if not para_lines:
            # If we couldn't parse anything, consume at least 1 line
            return None, 1

        text = ' '.join(para_lines).strip()

        # Handle inline formatting
        rich_text = self._parse_inline_formatting(text)

        return {
            "type": "paragraph",
            "paragraph": {
                "rich_text": rich_text
            }
        }, consumed

    def _parse_inline_formatting(self, text: str) -> List[Dict]:
        """Parse inline formatting (hyperlinks, bare URLs, bold, italic, code)."""
        # Remove image references for paragraph text
        text = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', '', text)
        text = re.sub(r'!\[\[([^\]]+)\]\]', '', text)
        text = text.strip()

        if not text:
            return [{"type": "text", "text": {"content": " "}}]

        # Parse hyperlinks, bare URLs, bold, italic, and code
        rich_text = []
        i = 0

        while i < len(text):
            # Check for bare URL: http:// or https://
            if text[i:].startswith('http://') or text[i:].startswith('https://'):
                # Find the end of URL (whitespace or end of string)
                url_start = i
                url_end = i

                # Simple approach: consume until whitespace or common delimiters
                while url_end < len(text) and text[url_end] not in [' ', '\n', '\t', '\r']:
                    url_end += 1

                # Trim trailing punctuation that's likely not part of URL
                while url_end > url_start and text[url_end - 1] in ['.', ',', '!', '?', ')', ']', ';', ':']:
                    url_end -= 1

                url = text[url_start:url_end]
                rich_text.append({
                    "type": "text",
                    "text": {
                        "content": url,
                        "link": {"url": url}
                    }
                })
                i = url_end
                continue

            # Check for markdown hyperlink: [text](url)
            # Note: Must check this BEFORE checking for bold/italic to avoid conflicts
            if text[i] == '[':
                # Find the closing ]
                close_bracket = text.find(']', i+1)
                if close_bracket != -1 and close_bracket + 1 < len(text) and text[close_bracket + 1] == '(':
                    # Find the closing )
                    close_paren = text.find(')', close_bracket + 2)
                    if close_paren != -1:
                        link_text = text[i+1:close_bracket]
                        link_url = text[close_bracket+2:close_paren]

                        # Create link - Notion uses href in text object
                        rich_text.append({
                            "type": "text",
                            "text": {
                                "content": link_text,
                                "link": {"url": link_url}
                            }
                        })
                        i = close_paren + 1
                        continue

            # Check for bold: **text** or __text__
            if text[i:i+2] == '**' or text[i:i+2] == '__':
                delimiter = text[i:i+2]
                end = text.find(delimiter, i+2)
                if end != -1:
                    rich_text.append({
                        "type": "text",
                        "text": {"content": text[i+2:end]},
                        "annotations": {"bold": True}
                    })
                    i = end + 2
                    continue

            # Check for italic: *text* or _text_
            elif text[i] in ['*', '_'] and (i == 0 or text[i-1] not in ['*', '_']):
                delimiter = text[i]
                end = i + 1
                # Find matching delimiter
                while end < len(text):
                    if text[end] == delimiter and (end + 1 >= len(text) or text[end+1] not in ['*', '_']):
                        break
                    end += 1

                if end < len(text) and text[end] == delimiter:
                    rich_text.append({
                        "type": "text",
                        "text": {"content": text[i+1:end]},
                        "annotations": {"italic": True}
                    })
                    i = end + 1
                    continue

            # Check for inline code: `text`
            elif text[i] == '`':
                end = text.find('`', i+1)
                if end != -1:
                    rich_text.append({
                        "type": "text",
                        "text": {"content": text[i+1:end]},
                        "annotations": {"code": True}
                    })
                    i = end + 1
                    continue

            # Regular text - collect until next formatting
            next_special = len(text)
            for char_idx in range(i+1, len(text)):
                # Check for special formatting chars or start of URLs
                if text[char_idx] in ['*', '_', '`', '[']:
                    next_special = char_idx
                    break
                # Check for start of URL
                if text[char_idx:].startswith('http://') or text[char_idx:].startswith('https://'):
                    next_special = char_idx
                    break

            if i < next_special:
                rich_text.append({
                    "type": "text",
                    "text": {"content": text[i:next_special]}
                })
            i = next_special if next_special > i else i + 1

        return rich_text if rich_text else [{"type": "text", "text": {"content": text}}]

    def _parse_code_block(self, lines: List[str]) -> tuple[List[Dict], int]:
        """Parse code block, splitting into multiple blocks if > 2000 chars."""
        if not lines[0].startswith('```'):
            return [], 0

        language = lines[0][3:].strip() or "plain text"
        code_lines = []
        consumed = 1

        for line in lines[1:]:
            if line.startswith('```'):
                consumed += 1
                break
            code_lines.append(line)
            consumed += 1

        code = '\n'.join(code_lines)

        # Notion limit: 2000 characters per code block
        MAX_CODE_LENGTH = 2000
        blocks = []

        if len(code) <= MAX_CODE_LENGTH:
            # Single block
            blocks.append({
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": code}}],
                    "language": language
                }
            })
        else:
            # Split into multiple blocks
            # Split by lines to avoid breaking in the middle of a line
            current_chunk = []
            current_length = 0

            for line in code_lines:
                line_length = len(line) + 1  # +1 for newline

                # Check if adding this line would exceed limit
                if current_chunk and current_length + line_length > MAX_CODE_LENGTH:
                    # Flush current chunk before adding this line
                    chunk_code = '\n'.join(current_chunk)
                    blocks.append({
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": chunk_code}}],
                            "language": language
                        }
                    })
                    current_chunk = []
                    current_length = 0

                # Handle single line longer than limit (split it by characters)
                if line_length > MAX_CODE_LENGTH:
                    # Split this long line into chunks
                    for chunk_start in range(0, len(line), MAX_CODE_LENGTH):
                        line_chunk = line[chunk_start:chunk_start + MAX_CODE_LENGTH]
                        blocks.append({
                            "type": "code",
                            "code": {
                                "rich_text": [{"type": "text", "text": {"content": line_chunk}}],
                                "language": language
                            }
                        })
                else:
                    # Add line to current chunk
                    current_chunk.append(line)
                    current_length += line_length

            # Flush remaining
            if current_chunk:
                chunk_code = '\n'.join(current_chunk)
                blocks.append({
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": chunk_code}}],
                        "language": language
                    }
                })

            logger.info("Split large code block ({} chars) into {} blocks", len(code), len(blocks))

        return blocks, consumed

    def _parse_bullet_list(self, lines: List[str]) -> tuple[Dict, int]:
        """Parse bullet list - return first item, caller handles rest."""
        line = lines[0].strip()

        # Remove list marker
        for prefix in ['- ', '* ', '+ ']:
            if line.startswith(prefix):
                text = line[len(prefix):].strip()
                break
        else:
            return None, 0

        return {
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            }
        }, 1

    def _parse_numbered_list(self, lines: List[str]) -> tuple[Dict, int]:
        """Parse numbered list - return first item."""
        line = lines[0].strip()
        match = re.match(r'^\d+\.\s(.+)$', line)

        if not match:
            return None, 0

        text = match.group(1).strip()

        return {
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            }
        }, 1

    def _parse_table(self, lines: List[str]) -> tuple[Dict, int]:
        """Parse markdown table."""
        if not lines or '|' not in lines[0]:
            return None, 0

        table_lines = []
        consumed = 0

        # Collect table lines
        for line in lines:
            if '|' not in line:
                break
            table_lines.append(line)
            consumed += 1

        if len(table_lines) < 2:  # Need at least header + separator
            return None, 0

        # Parse header
        header_row = [cell.strip() for cell in table_lines[0].split('|') if cell.strip()]

        # Skip separator line (e.g., |---|---|)
        # Check if second line is separator
        if consumed < 2 or not re.match(r'^[\s\|\-:]+$', table_lines[1]):
            return None, 0

        # Parse data rows
        data_rows = []
        for line in table_lines[2:]:
            row = [cell.strip() for cell in line.split('|') if cell.strip()]
            if row:
                data_rows.append(row)

        # Build Notion table block
        # Notion tables need table_width and table_row children
        table_width = len(header_row)

        # Create table rows (header + data rows)
        table_rows = []

        # Add header row - parse inline formatting in each cell
        header_cells = [self._parse_inline_formatting(cell) for cell in header_row]
        table_rows.append({
            "type": "table_row",
            "table_row": {
                "cells": header_cells
            }
        })

        # Add data rows - parse inline formatting in each cell
        for row in data_rows:
            # Pad row to match table width
            while len(row) < table_width:
                row.append("")
            cells = [self._parse_inline_formatting(cell) for cell in row[:table_width]]
            table_rows.append({
                "type": "table_row",
                "table_row": {
                    "cells": cells
                }
            })

        return {
            "type": "table",
            "table": {
                "table_width": table_width,
                "has_column_header": True,
                "has_row_header": False,
                "children": table_rows
            }
        }, consumed

    def _create_media_block(self, file_upload_id: str, file_type: str) -> Dict:
        """Create appropriate Notion block based on media type."""
        # Map file types to Notion block types
        if file_type == 'image':
            block_type = 'image'
        elif file_type == 'video':
            block_type = 'video'
        elif file_type == 'audio':
            block_type = 'audio'
        elif file_type == 'pdf':
            block_type = 'pdf'
        else:
            block_type = 'file'  # Generic file block

        return {
            "type": block_type,
            block_type: {
                "type": "file_upload",
                "file_upload": {"id": file_upload_id}
            }
        }

    def _parse_images(self, line: str, media_map: Dict[str, tuple]) -> List[Dict]:
        """Parse media files from line - use uploaded files or external URLs.

        media_map format: {original_ref: (file_upload_id, file_type)} or {original_ref: url}
        """
        blocks = []

        # Find all image references
        # Standard markdown: ![alt](url)
        for match in re.finditer(r'!\[([^\]]*)\]\(([^\)]+)\)', line):
            alt = match.group(1)
            url = match.group(2)

            # Check if we have a mapped file_upload_id or URL
            original_ref = match.group(0)
            if original_ref in media_map:
                mapped_value = media_map[original_ref]

                # Check if it's a tuple (file_upload_id, file_type)
                if isinstance(mapped_value, tuple):
                    file_upload_id, file_type = mapped_value
                    # Create appropriate block type based on file_type
                    blocks.append(self._create_media_block(file_upload_id, file_type))
                # Check if it's a URL string
                elif isinstance(mapped_value, str) and mapped_value.startswith(('http://', 'https://')):
                    # It's an external URL
                    blocks.append({
                        "type": "image",
                        "image": {
                            "type": "external",
                            "external": {"url": mapped_value}
                        }
                    })
                else:
                    # Fallback to callout
                    blocks.append({
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"type": "text", "text": {"content": f"📷 Media: {url} (alt: {alt})"}}],
                            "icon": {"emoji": "📷"}
                        }
                    })
            elif url.startswith(('http://', 'https://')):
                # Direct external URL
                blocks.append({
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": url}
                    }
                })
            else:
                # No mapping and not external - callout
                blocks.append({
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"type": "text", "text": {"content": f"📷 Image: {url} (alt: {alt})"}}],
                        "icon": {"emoji": "📷"}
                    }
                })

        # Wikilinks: ![[image.png]]
        for match in re.finditer(r'!\[\[([^\]]+)\]\]', line):
            original_ref = match.group(0)
            filename = match.group(1)

            # Check if we have a mapped file_upload_id or URL
            if original_ref in media_map:
                mapped_value = media_map[original_ref]

                # Check if it's a tuple (file_upload_id, file_type)
                if isinstance(mapped_value, tuple):
                    file_upload_id, file_type = mapped_value
                    blocks.append(self._create_media_block(file_upload_id, file_type))
                # Check if it's a URL string
                elif isinstance(mapped_value, str) and mapped_value.startswith(('http://', 'https://')):
                    blocks.append({
                        "type": "image",
                        "image": {
                            "type": "external",
                            "external": {"url": mapped_value}
                        }
                    })
                else:
                    # Fallback to callout
                    blocks.append({
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"type": "text", "text": {"content": f"📷 Media: {filename}"}}],
                            "icon": {"emoji": "📷"}
                        }
                    })
            else:
                # No mapping - create callout
                blocks.append({
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"type": "text", "text": {"content": f"📷 Image: {filename}"}}],
                        "icon": {"emoji": "📷"}
                    }
                })

        return blocks

    def notion_blocks_to_markdown(self, blocks: List[Dict]) -> str:
        """Convert Notion blocks to markdown."""
        logger.info("Converting {} Notion blocks to markdown", len(blocks))

        markdown_lines = []

        for block in blocks:
            block_type = block.get('type')

            if block_type and block_type.startswith('heading_'):
                level = int(block_type.split('_')[1])
                text = self._extract_notion_text(block[block_type].get('rich_text', []))
                markdown_lines.append(f"{'#' * level} {text}")
                markdown_lines.append("")

            elif block_type == 'paragraph':
                text = self._extract_notion_text(block['paragraph'].get('rich_text', []))
                markdown_lines.append(text)
                markdown_lines.append("")

            elif block_type == 'code':
                language = block['code'].get('language', '')
                code = self._extract_notion_text(block['code'].get('rich_text', []))
                markdown_lines.append(f"```{language}")
                markdown_lines.append(code)
                markdown_lines.append("```")
                markdown_lines.append("")

            elif block_type == 'bulleted_list_item':
                text = self._extract_notion_text(block['bulleted_list_item'].get('rich_text', []))
                markdown_lines.append(f"- {text}")

            elif block_type == 'numbered_list_item':
                text = self._extract_notion_text(block['numbered_list_item'].get('rich_text', []))
                markdown_lines.append(f"1. {text}")

            elif block_type == 'image':
                url = block['image'].get('external', {}).get('url', '') or \
                      block['image'].get('file', {}).get('url', '')
                markdown_lines.append(f"![]({url})")
                markdown_lines.append("")

        result = "\n".join(markdown_lines)
        logger.info("Converted to {} characters of markdown", len(result))
        return result

    def _extract_notion_text(self, rich_text: List[Dict]) -> str:
        """Extract plain text from Notion rich_text array."""
        return ''.join(item.get('text', {}).get('content', '') for item in rich_text)

    def notion_blocks_to_quip_html(self, blocks: List[Dict], media_map: Dict[str, str] = None, media_filenames: Dict[str, str] = None) -> str:
        """Convert Notion blocks to Quip HTML.

        Args:
            blocks: List of Notion block objects
            media_map: Mapping of file_upload_id to Quip blob URLs
                      Format: {file_upload_id: quip_blob_url}
            media_filenames: Mapping of file_upload_id to original filename
                           Format: {file_upload_id: filename}

        Returns:
            Quip-formatted HTML string
        """
        if media_map is None:
            media_map = {}
        if media_filenames is None:
            media_filenames = {}

        html_parts = []

        for block in blocks:
            block_type = block.get('type')

            if block_type and block_type.startswith('heading_'):
                level = int(block_type.split('_')[1])
                text = self._notion_richtext_to_html(block[block_type].get('rich_text', []))
                html_parts.append(f"<h{level}>{text}</h{level}>")

            elif block_type == 'paragraph':
                text = self._notion_richtext_to_html(block['paragraph'].get('rich_text', []))
                html_parts.append(f"<p>{text}</p>")

            elif block_type == 'code':
                code = self._extract_notion_text(block['code'].get('rich_text', []))
                # Quip uses <pre> for code blocks
                html_parts.append(f"<pre>{self._escape_html(code)}</pre>")

            elif block_type == 'bulleted_list_item':
                text = self._notion_richtext_to_html(block['bulleted_list_item'].get('rich_text', []))
                html_parts.append(f"<ul><li>{text}</li></ul>")

            elif block_type == 'numbered_list_item':
                text = self._notion_richtext_to_html(block['numbered_list_item'].get('rich_text', []))
                html_parts.append(f"<ol><li>{text}</li></ol>")

            elif block_type in ['image', 'video', 'audio', 'pdf', 'file']:
                # Get file_upload_id from block
                media_data = block.get(block_type, {})
                file_upload = media_data.get('file_upload', {})
                file_upload_id = file_upload.get('id')

                if file_upload_id and file_upload_id in media_map:
                    blob_url = media_map[file_upload_id]
                    filename = media_filenames.get(file_upload_id, "media")
                    logger.debug("Converting {} block with file_upload_id={} to HTML with blob_url={}",
                                block_type, file_upload_id[:20] + "...", blob_url)
                    if block_type == 'image':
                        # Use Quip's image format with div wrapper, alt text
                        html_parts.append(f"<div data-section-style='11' style='max-width:100%' class=''><img src=\"{blob_url}\" width='800' height='600' alt=\"{filename}\"></img></div>")
                    elif block_type == 'video':
                        # Use Quip's inline video player format (with auto-generated thumbnail)
                        # Quip generates thumbnails server-side: add -jpg suffix to blob URL
                        thumbnail_url = f"{blob_url}-jpg"
                        video_url = f"https://quip-amazon.com{blob_url}"

                        # Exact format from manually-inserted videos
                        html_parts.append(
                            f"<div style='display:flex;flex-direction:column;align-items:center;justify-content:center'>"
                            f"<div data-section-style='11' style='max-width:100%' class=''>"
                            f"<img src='{thumbnail_url}' width='800' height='600'></img>"
                            f"</div>"
                            f"<span>Video: <a href='{video_url}' target='_blank'>{filename}</a></span>"
                            f"</div>"
                        )
                        logger.debug("Using Quip inline video player format: {}", filename)
                    else:
                        # For other files, create a link
                        html_parts.append(f'<p><a href="{blob_url}">View file</a></p>')
                else:
                    # Fallback: show placeholder
                    logger.warning("No blob URL found for {} block with file_upload_id={} (media_map has {} keys)",
                                  block_type, file_upload_id, len(media_map))
                    html_parts.append(f'<p>[{block_type.upper()}]</p>')

            elif block_type == 'table':
                table_html = self._notion_table_to_html(block['table'])
                html_parts.append(table_html)

        return '\n'.join(html_parts)

    def _notion_richtext_to_html(self, rich_text: List[Dict]) -> str:
        """Convert Notion rich_text array to HTML with formatting.

        Handles bold, italic, code, strikethrough, underline, and links.
        """
        html_parts = []

        for item in rich_text:
            text_obj = item.get('text', {})
            content = text_obj.get('content', '')
            link = text_obj.get('link')

            annotations = item.get('annotations', {})

            # Apply formatting
            result = self._escape_html(content)

            if annotations.get('bold'):
                result = f"<b>{result}</b>"
            if annotations.get('italic'):
                result = f"<i>{result}</i>"
            if annotations.get('code'):
                result = f"<code>{result}</code>"
            if annotations.get('strikethrough'):
                result = f"<s>{result}</s>"
            if annotations.get('underline'):
                result = f"<u>{result}</u>"

            # Apply link if present
            if link:
                url = link.get('url', '')
                result = f'<a href="{url}">{result}</a>'

            html_parts.append(result)

        return ''.join(html_parts)

    def _notion_table_to_html(self, table_data: Dict) -> str:
        """Convert Notion table to HTML table."""
        rows = table_data.get('children', [])
        if not rows:
            return ""

        html = ['<table border="1">']

        for i, row_block in enumerate(rows):
            if row_block.get('type') != 'table_row':
                continue

            cells = row_block.get('table_row', {}).get('cells', [])
            is_header = (i == 0 and table_data.get('has_column_header'))

            tag = 'th' if is_header else 'td'
            row_html = ['<tr>']

            for cell in cells:
                cell_html = self._notion_richtext_to_html(cell)
                row_html.append(f"<{tag}>{cell_html}</{tag}>")

            row_html.append('</tr>')
            html.append(''.join(row_html))

        html.append('</table>')
        return '\n'.join(html)

    def quip_html_to_markdown(self, html: str, media_dir: Path) -> tuple[str, Dict[str, str]]:
        """Convert Quip HTML to Markdown.

        Args:
            html: Quip HTML content
            media_dir: Directory name for media files (e.g., "_DocumentName.files")

        Returns:
            Tuple of (markdown_content, blob_map)
            blob_map: {blob_id: filename} for downloaded media files
        """
        soup = BeautifulSoup(html, 'html.parser')
        markdown_lines = []
        blob_map = {}  # {blob_id: filename}

        # Find all top-level elements in the document
        # Quip wraps content in sections with ids
        body = soup.find('body') or soup

        for element in body.find_all(recursive=False):
            md_text = self._element_to_markdown(element, media_dir, blob_map)
            if md_text:
                markdown_lines.append(md_text)

        return '\n'.join(markdown_lines), blob_map

    def _element_to_markdown(self, element, media_dir: Path, blob_map: Dict[str, str]) -> str:
        """Convert a single HTML element to markdown."""
        if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(element.name[1])
            text = element.get_text().strip()
            return f"{'#' * level} {text}\n"

        elif element.name == 'p':
            text = self._extract_formatted_text(element, media_dir, blob_map)
            return f"{text}\n"

        elif element.name == 'ul':
            items = []
            for li in element.find_all('li', recursive=False):
                text = self._extract_formatted_text(li, media_dir, blob_map)
                items.append(f"- {text}")
            return '\n'.join(items) + '\n'

        elif element.name == 'ol':
            items = []
            for i, li in enumerate(element.find_all('li', recursive=False), 1):
                text = self._extract_formatted_text(li, media_dir, blob_map)
                items.append(f"{i}. {text}")
            return '\n'.join(items) + '\n'

        elif element.name == 'pre':
            code = element.get_text()
            return f"```\n{code}\n```\n"

        elif element.name == 'img':
            # Extract blob reference
            src = element.get('src', '')
            alt = element.get('alt', 'image')

            # Quip blob URLs: /blob/{thread_id}/{blob_id} or full URLs
            blob_match = re.search(r'/blob/[^/]+/([^/\?]+)', src)
            if blob_match:
                blob_id = blob_match.group(1).rstrip('-jpg')  # Remove -jpg suffix for thumbnails
                # Use blob_id to ensure unique filenames
                filename = f"image_{blob_id[:12]}.png"
                blob_map[blob_id] = filename
                return f"![]({media_dir}/{filename})\n"
            else:
                # External URL
                return f"![]({src})\n"

        elif element.name == 'div':
            # Check if it's a video container (Quip's inline video format)
            video_link = element.find('a', href=re.compile(r'/blob/'))
            if video_link:
                href = video_link.get('href', '')
                blob_match = re.search(r'/blob/[^/]+/([^/\?]+)', href)
                if blob_match:
                    blob_id = blob_match.group(1)
                    # Use blob_id to ensure unique filenames
                    filename = f"video_{blob_id[:12]}.mp4"
                    blob_map[blob_id] = filename
                    return f"![]({media_dir}/{filename})\n"

            # Otherwise, process children
            parts = []
            for child in element.children:
                if hasattr(child, 'name'):
                    md = self._element_to_markdown(child, media_dir, blob_map)
                    if md:
                        parts.append(md)
            return ''.join(parts)

        return ''

    def _extract_formatted_text(self, element, media_dir: Path, blob_map: Dict[str, str]) -> str:
        """Extract text with inline formatting (bold, italic, links, images)."""
        parts = []

        for child in element.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.name == 'b' or child.name == 'strong':
                parts.append(f"**{child.get_text()}**")
            elif child.name == 'i' or child.name == 'em':
                parts.append(f"*{child.get_text()}*")
            elif child.name == 'code':
                parts.append(f"`{child.get_text()}`")
            elif child.name == 'a':
                text = child.get_text()
                href = child.get('href', '')
                parts.append(f"[{text}]({href})")
            elif child.name == 'img':
                # Inline image
                src = child.get('src', '')
                alt = child.get('alt', 'image')
                blob_match = re.search(r'/blob/[^/]+/([^/\?]+)', src)
                if blob_match:
                    blob_id = blob_match.group(1).rstrip('-jpg')

                    # Use blob_id to ensure unique filenames
                    # Format: image_<blob_prefix>.png
                    filename = f"image_{blob_id[:12]}.png"
                    blob_map[blob_id] = filename
                    parts.append(f"![]({media_dir}/{filename})")
                else:
                    parts.append(f"![]({src})")
            else:
                # Recursively extract from other elements
                parts.append(self._extract_formatted_text(child, media_dir, blob_map))

        return ''.join(parts)

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special characters."""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))
