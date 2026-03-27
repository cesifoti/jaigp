"""PDF to HTML and Markdown converter service."""
import fitz  # PyMuPDF
import re
import os
from pathlib import Path
from typing import Tuple, List, Dict
from collections import Counter


class PDFConverter:
    """Convert PDF files to HTML and Markdown formats."""

    def extract_images_from_pdf(self, pdf_path: str, output_dir: str) -> List[Dict]:
        """
        Extract images from PDF and save them to output directory.
        Returns list of dicts with image info including page number and position.
        """
        try:
            doc = fitz.open(pdf_path)
            image_files = []

            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)

            image_count = 0
            for page_num, page in enumerate(doc):
                # Get images on this page with positioning
                image_list = page.get_images()

                for img_index, img in enumerate(image_list):
                    xref = img[0]  # XREF number

                    try:
                        # Extract image
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        # Get image position on page
                        img_rect = None
                        for img_info in page.get_image_info(xrefs=True):
                            if img_info["xref"] == xref:
                                img_rect = img_info["bbox"]
                                break

                        # Generate filename
                        image_count += 1
                        image_filename = f"figure_{image_count}.{image_ext}"
                        image_path = os.path.join(output_dir, image_filename)

                        # Save image
                        with open(image_path, "wb") as img_file:
                            img_file.write(image_bytes)

                        # Store metadata
                        image_files.append({
                            'filename': image_filename,
                            'page': page_num,
                            'position': img_rect[1] if img_rect else 0,  # y-coordinate
                            'number': image_count
                        })

                    except Exception as e:
                        print(f"Could not extract image {img_index} from page {page_num}: {e}")
                        continue

            doc.close()
            print(f"Extracted {len(image_files)} images from PDF")
            return image_files

        except Exception as e:
            print(f"Error extracting images from PDF: {e}")
            return []

    def detect_table_regions(self, page) -> List[tuple]:
        """
        Detect table regions by looking for table captions and structured content.
        Returns list of bounding boxes for detected tables.
        """
        table_regions = []
        text_blocks = page.get_text("dict")["blocks"]

        # Look for table captions (e.g., "Table 1:", "Table 2.", etc.)
        table_pattern = re.compile(r'\b[Tt]able\s+\d+', re.IGNORECASE)

        for i, block in enumerate(text_blocks):
            if "lines" not in block:
                continue

            # Get text from this block
            block_text = ""
            for line in block["lines"]:
                for span in line["spans"]:
                    block_text += span["text"] + " "

            # Check if this looks like a table caption
            if table_pattern.search(block_text):
                # Found a table caption - try to find the table boundaries
                caption_bbox = block["bbox"]

                # Look ahead for the table content
                # Tables usually have multiple columns and rows after the caption
                table_bottom = caption_bbox[3]
                table_left = caption_bbox[0]
                table_right = caption_bbox[2]

                # Scan subsequent blocks to find table extent
                for j in range(i + 1, min(i + 30, len(text_blocks))):  # Look ahead max 30 blocks
                    next_block = text_blocks[j]
                    if "lines" not in next_block:
                        continue

                    next_bbox = next_block["bbox"]

                    # Check if this block is part of the table
                    # (similar horizontal alignment and contains numbers/structured data)
                    next_text = ""
                    for line in next_block["lines"]:
                        for span in line["spans"]:
                            next_text += span["text"] + " "

                    # Stop if we hit another table or section heading
                    if table_pattern.search(next_text) or re.match(r'^[A-Z\s]{10,}$', next_text.strip()):
                        break

                    # Extend table boundaries
                    if next_bbox[1] > table_bottom + 50:  # Too far below, probably not part of table
                        break

                    table_bottom = max(table_bottom, next_bbox[3])
                    table_left = min(table_left, next_bbox[0])
                    table_right = max(table_right, next_bbox[2])

                # Add margin around detected table
                margin = 20
                table_bbox = (
                    max(0, table_left - margin),
                    max(0, caption_bbox[1] - margin),
                    min(page.rect.width, table_right + margin),
                    min(page.rect.height, table_bottom + margin)
                )

                # Only add if it looks substantial enough
                height = table_bbox[3] - table_bbox[1]
                if height > 50:  # At least 50 points tall
                    table_regions.append(table_bbox)

        return table_regions

    def extract_tables_as_images(self, pdf_path: str, output_dir: str) -> List[Dict]:
        """
        Extract tables from PDF as images for perfect rendering.
        Uses both automatic detection and caption-based detection.
        Returns list of dicts with table image info including page and position.
        """
        try:
            doc = fitz.open(pdf_path)
            table_images = []
            table_count = 0

            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)

            for page_num, page in enumerate(doc):
                try:
                    # Method 1: Try automatic table detection first
                    tables = page.find_tables()
                    detected_bboxes = []

                    if tables and tables.tables:
                        for table in tables:
                            if table.bbox:
                                detected_bboxes.append(table.bbox)

                    # Method 2: Caption-based detection
                    caption_bboxes = self.detect_table_regions(page)
                    detected_bboxes.extend(caption_bboxes)

                    # Process all detected tables
                    for bbox in detected_bboxes:
                        table_count += 1

                        # Expand bbox slightly for better capture
                        bbox = list(bbox)
                        margin = 10
                        bbox[0] = max(0, bbox[0] - margin)
                        bbox[1] = max(0, bbox[1] - margin)
                        bbox[2] = min(page.rect.width, bbox[2] + margin)
                        bbox[3] = min(page.rect.height, bbox[3] + margin)

                        # Create a rect from bbox
                        table_rect = fitz.Rect(bbox)

                        # Render the table region as image at high resolution
                        mat = fitz.Matrix(3, 3)  # 3x zoom for better quality
                        pix = page.get_pixmap(matrix=mat, clip=table_rect)

                        # Save as PNG
                        table_filename = f"table_{table_count}.png"
                        table_path = os.path.join(output_dir, table_filename)
                        pix.save(table_path)

                        # Store metadata
                        table_images.append({
                            'filename': table_filename,
                            'page': page_num,
                            'position': bbox[1],  # y-coordinate
                            'number': table_count,
                            'bbox': bbox
                        })

                        print(f"Extracted table {table_count} from page {page_num + 1}")

                except Exception as e:
                    print(f"Error extracting tables from page {page_num}: {e}")
                    continue

            doc.close()
            print(f"Extracted {len(table_images)} table(s) as images")
            return table_images

        except Exception as e:
            print(f"Error extracting table images from PDF: {e}")
            return []


    def detect_headers_footers(self, pdf_path: str) -> Tuple[List[str], List[str]]:
        """
        Detect repeated headers and footers across pages.
        Returns: (list_of_header_patterns, list_of_footer_patterns)
        """
        try:
            doc = fitz.open(pdf_path)

            # Collect text from top and bottom of each page
            top_texts = []
            bottom_texts = []

            for page in doc:
                blocks = page.get_text("blocks")
                if not blocks:
                    continue

                # Sort blocks by y-coordinate
                sorted_blocks = sorted(blocks, key=lambda b: b[1])

                # Get top blocks (within top 10% of page)
                page_height = page.rect.height
                top_threshold = page_height * 0.1
                bottom_threshold = page_height * 0.9

                for block in sorted_blocks:
                    y0 = block[1]
                    y1 = block[3]
                    text = block[4].strip()

                    if y0 < top_threshold and text:
                        top_texts.append(text)
                    elif y1 > bottom_threshold and text:
                        bottom_texts.append(text)

            doc.close()

            # Find patterns that appear on multiple pages (at least 3 times)
            min_occurrences = 3

            header_patterns = []
            for text, count in Counter(top_texts).items():
                if count >= min_occurrences:
                    # Filter out very short texts (likely noise)
                    if len(text) > 5 and len(text) < 200:
                        header_patterns.append(text)

            footer_patterns = []
            for text, count in Counter(bottom_texts).items():
                if count >= min_occurrences:
                    if len(text) > 5 and len(text) < 200:
                        footer_patterns.append(text)

            # Also add common page number patterns
            page_number_patterns = [
                r'^\d+$',  # Just a number
                r'^Page \d+$',
                r'^\d+ \| ',
                r'^\d+\s*$',
            ]

            print(f"Detected {len(header_patterns)} header patterns and {len(footer_patterns)} footer patterns")
            return header_patterns, footer_patterns

        except Exception as e:
            print(f"Error detecting headers/footers: {e}")
            return [], []

    def extract_content_with_positions(self, pdf_path: str, output_dir: str) -> List[Dict]:
        """
        Extract all content (text, images, tables) with their positions.
        Returns list of content blocks in document order.
        """
        try:
            doc = fitz.open(pdf_path)

            # First pass: detect headers and footers
            header_patterns, footer_patterns = self.detect_headers_footers(pdf_path)

            # Extract images
            images_info = self.extract_images_from_pdf(pdf_path, output_dir)
            images_by_page = {}
            for img in images_info:
                page = img['page']
                if page not in images_by_page:
                    images_by_page[page] = []
                images_by_page[page].append(img)

            # Extract tables as images
            tables_info = self.extract_tables_as_images(pdf_path, output_dir)
            tables_by_page = {}
            for tbl in tables_info:
                page = tbl['page']
                if page not in tables_by_page:
                    tables_by_page[page] = []
                tables_by_page[page].append(tbl)

            # Now extract all content in order
            all_content = []

            for page_num, page in enumerate(doc):
                page_height = page.rect.height
                top_threshold = page_height * 0.1
                bottom_threshold = page_height * 0.9

                # Get all text blocks
                blocks = page.get_text("blocks")

                # Combine text blocks, images, and tables for this page
                page_items = []

                # Add text blocks
                for block in blocks:
                    if len(block) >= 5:
                        y0 = block[1]
                        y1 = block[3]
                        text = block[4].strip()

                        if not text:
                            continue

                        # Skip headers/footers
                        if text in header_patterns or text in footer_patterns:
                            continue

                        # Skip page numbers in header/footer regions
                        if re.match(r'^\d+$', text) and len(text) <= 3:
                            if y0 < top_threshold or y1 > bottom_threshold:
                                continue

                        # Skip very short texts in header/footer regions
                        if len(text) < 10 and (y0 < top_threshold or y1 > bottom_threshold):
                            continue

                        page_items.append({
                            'type': 'text',
                            'content': text,
                            'position': y0,
                            'page': page_num
                        })

                # Add images for this page
                if page_num in images_by_page:
                    for img in images_by_page[page_num]:
                        page_items.append({
                            'type': 'image',
                            'content': img,
                            'position': img['position'],
                            'page': page_num
                        })

                # Add table images for this page
                if page_num in tables_by_page:
                    for table in tables_by_page[page_num]:
                        page_items.append({
                            'type': 'table',
                            'content': table,
                            'position': table['position'],
                            'page': page_num
                        })

                # Sort by position on page
                page_items.sort(key=lambda x: x['position'])

                # Add to all content
                all_content.extend(page_items)

            doc.close()
            return all_content

        except Exception as e:
            print(f"Error extracting content with positions: {e}")
            return []

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from PDF file as continuous document.
        Removes page breaks, headers, footers, and tries to maintain paragraph structure.
        """
        try:
            doc = fitz.open(pdf_path)

            # First pass: detect headers and footers
            header_patterns, footer_patterns = self.detect_headers_footers(pdf_path)

            all_text = []

            for page in doc:
                # Extract text blocks with positioning info
                blocks = page.get_text("blocks")

                page_height = page.rect.height
                top_threshold = page_height * 0.1
                bottom_threshold = page_height * 0.9

                for block in blocks:
                    # block format: (x0, y0, x1, y1, "text", block_no, block_type)
                    if len(block) >= 5:
                        y0 = block[1]
                        y1 = block[3]
                        text = block[4].strip()

                        if not text:
                            continue

                        # Skip if it's a header or footer pattern
                        if text in header_patterns or text in footer_patterns:
                            continue

                        # Skip if it's just a page number
                        if re.match(r'^\d+$', text) and len(text) <= 3:
                            if y0 < top_threshold or y1 > bottom_threshold:
                                continue

                        # Skip very short texts in header/footer regions
                        if len(text) < 10 and (y0 < top_threshold or y1 > bottom_threshold):
                            continue

                        all_text.append(text)

            doc.close()

            # Join all text with double newlines between blocks
            full_text = "\n\n".join(all_text)

            # Clean up multiple consecutive newlines
            full_text = re.sub(r'\n{3,}', '\n\n', full_text)

            return full_text

        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""

    def process_footnotes_to_endnotes(self, text: str) -> Tuple[str, List[str]]:
        """
        Attempt to identify footnotes and convert them to endnotes.
        Returns: (main_text, list_of_endnotes)
        """
        # This is a simple heuristic - footnotes often appear as superscript numbers
        # followed by text at the bottom of pages
        # For now, we'll just collect them and return them separately

        # Pattern for footnote markers (1, 2, 3, etc. or *, †, ‡)
        footnote_pattern = r'(\d+)\s*[.:]\s*'

        endnotes = []
        lines = text.split('\n')
        main_lines = []
        collecting_footnote = False
        current_footnote = []

        for line in lines:
            # Simple heuristic: if line starts with a number followed by period/colon
            # and is relatively short, it might be a footnote
            match = re.match(footnote_pattern, line.strip())
            if match and len(line) < 200:
                if current_footnote:
                    endnotes.append(' '.join(current_footnote))
                current_footnote = [line.strip()]
                collecting_footnote = True
            elif collecting_footnote and line.strip():
                current_footnote.append(line.strip())
            else:
                if current_footnote:
                    endnotes.append(' '.join(current_footnote))
                    current_footnote = []
                    collecting_footnote = False
                main_lines.append(line)

        # Add any remaining footnote
        if current_footnote:
            endnotes.append(' '.join(current_footnote))

        main_text = '\n'.join(main_lines)
        return main_text, endnotes

    def pdf_to_markdown(self, pdf_path: str, paper_title: str, paper_abstract: str) -> str:
        """Convert PDF to Markdown format with inline figures and tables."""
        # Create directory for images
        pdf_dir = os.path.dirname(pdf_path)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        image_dir = os.path.join(pdf_dir, f"{pdf_basename}_images")

        # Extract all content with positions
        content_blocks = self.extract_content_with_positions(pdf_path, image_dir)

        if not content_blocks:
            return f"# {paper_title}\n\n## Abstract\n\n{paper_abstract}\n\n*PDF content could not be extracted.*"

        # Build markdown content
        markdown = f"""# {paper_title}

## Abstract

{paper_abstract}

---

## Full Text

"""

        current_paragraph = []
        figure_counter = 0
        table_counter = 0

        for block in content_blocks:
            if block['type'] == 'text':
                current_paragraph.append(block['content'])

            elif block['type'] == 'image':
                # Flush paragraph
                if current_paragraph:
                    markdown += '\n\n'.join(current_paragraph) + '\n\n'
                    current_paragraph = []

                # Insert image reference
                figure_counter += 1
                img_info = block['content']
                markdown += f"\n![Figure {figure_counter}]({pdf_basename}_images/{img_info['filename']})\n"
                markdown += f"*Figure {figure_counter}*\n\n"

            elif block['type'] == 'table':
                # Flush paragraph
                if current_paragraph:
                    markdown += '\n\n'.join(current_paragraph) + '\n\n'
                    current_paragraph = []

                # Insert table as image reference
                table_counter += 1
                table_info = block['content']
                markdown += f"\n![Table {table_counter}]({pdf_basename}_images/{table_info['filename']})\n"
                markdown += f"*Table {table_counter}*\n\n"

        # Flush remaining paragraph
        if current_paragraph:
            markdown += '\n\n'.join(current_paragraph) + '\n\n'

        markdown += "\n---\n\n*This document was automatically generated from the PDF version.*\n"

        return markdown

    def pdf_to_html(self, pdf_path: str, paper_title: str, paper_abstract: str, extract_images: bool = True) -> str:
        """Convert PDF to HTML format as standalone document with inline figures and tables."""
        # Create directory for images
        pdf_dir = os.path.dirname(pdf_path)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        image_dir = os.path.join(pdf_dir, f"{pdf_basename}_images")

        # Extract all content with positions
        content_blocks = self.extract_content_with_positions(pdf_path, image_dir)

        if not content_blocks:
            content_html = "<p><em>PDF content could not be extracted.</em></p>"
            endnotes_html = ""
        else:
            # Build HTML content with inline figures and tables
            content_html = ""
            current_paragraph = []
            figure_counter = 0
            table_counter = 0

            for block in content_blocks:
                if block['type'] == 'text':
                    # Accumulate text into paragraphs
                    current_paragraph.append(block['content'])

                elif block['type'] == 'image':
                    # Flush current paragraph
                    if current_paragraph:
                        text = '\n\n'.join(current_paragraph)
                        paragraphs = text.split('\n\n')
                        for p in paragraphs:
                            if p.strip():
                                content_html += f'<p>{self._escape_html(p)}</p>\n'
                        current_paragraph = []

                    # Insert image
                    figure_counter += 1
                    img_info = block['content']
                    img_rel_path = f"{pdf_basename}_images/{img_info['filename']}"
                    content_html += f'''
                    <figure class="inline-figure">
                        <img src="{img_rel_path}" alt="Figure {figure_counter}" loading="lazy">
                        <figcaption>Figure {figure_counter}</figcaption>
                    </figure>
                    '''

                elif block['type'] == 'table':
                    # Flush current paragraph
                    if current_paragraph:
                        text = '\n\n'.join(current_paragraph)
                        paragraphs = text.split('\n\n')
                        for p in paragraphs:
                            if p.strip():
                                content_html += f'<p>{self._escape_html(p)}</p>\n'
                        current_paragraph = []

                    # Insert table as image (preserves perfect PDF rendering)
                    table_counter += 1
                    table_info = block['content']
                    table_rel_path = f"{pdf_basename}_images/{table_info['filename']}"
                    content_html += f'''
                    <figure class="inline-table">
                        <img src="{table_rel_path}" alt="Table {table_counter}" loading="lazy">
                        <figcaption>Table {table_counter}</figcaption>
                    </figure>
                    '''

            # Flush any remaining paragraph
            if current_paragraph:
                text = '\n\n'.join(current_paragraph)
                paragraphs = text.split('\n\n')
                for p in paragraphs:
                    if p.strip():
                        content_html += f'<p>{self._escape_html(p)}</p>\n'

            # Note: Footnotes handling removed since we're processing blocks directly
            endnotes_html = ""

        # Build HTML document
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self._escape_html(paper_title)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
            line-height: 1.8;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
            color: #1e293b;
            background: #ffffff;
        }}
        h1 {{
            font-size: 2.5em;
            font-weight: 800;
            margin-bottom: 0.5em;
            color: #0f172a;
            line-height: 1.2;
        }}
        h2 {{
            font-size: 1.8em;
            font-weight: 700;
            margin-top: 2em;
            margin-bottom: 0.75em;
            color: #1e293b;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 0.3em;
        }}
        .abstract {{
            background: #f1f5f9;
            padding: 24px;
            border-left: 4px solid #2563eb;
            margin: 24px 0;
            border-radius: 4px;
        }}
        .abstract h2 {{
            margin-top: 0;
            border: none;
            font-size: 1.3em;
        }}
        hr {{
            border: none;
            border-top: 2px solid #e2e8f0;
            margin: 48px 0;
        }}
        p {{
            margin: 1.2em 0;
            text-align: justify;
            hyphens: auto;
        }}
        .endnotes {{
            font-size: 0.9em;
            color: #475569;
            padding-left: 2em;
        }}
        .endnotes li {{
            margin-bottom: 0.75em;
        }}
        /* Inline figures */
        .inline-figure {{
            margin: 2.5rem auto;
            max-width: 100%;
            text-align: center;
            page-break-inside: avoid;
        }}
        .inline-figure img {{
            max-width: 100%;
            height: auto;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .inline-figure figcaption {{
            margin-top: 0.75rem;
            font-size: 0.9em;
            color: #475569;
            font-weight: 600;
            font-style: italic;
        }}
        /* Inline tables (as images) */
        .inline-table {{
            margin: 2.5rem auto;
            max-width: 100%;
            text-align: center;
            page-break-inside: avoid;
        }}
        .inline-table img {{
            max-width: 100%;
            height: auto;
            border: 1px solid #cbd5e1;
            background: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .inline-table figcaption {{
            margin-top: 0.75rem;
            font-size: 0.9em;
            color: #475569;
            font-weight: 600;
            font-style: italic;
        }}
        .footer {{
            margin-top: 48px;
            padding-top: 24px;
            border-top: 1px solid #e2e8f0;
            color: #64748b;
            font-size: 0.9em;
            font-style: italic;
            text-align: center;
        }}
        @media print {{
            body {{ padding: 20px; }}
        }}
        @media (max-width: 640px) {{
            .figures-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <h1>{self._escape_html(paper_title)}</h1>

    <div class="abstract">
        <h2>Abstract</h2>
        <p>{self._escape_html(paper_abstract)}</p>
    </div>

    <hr>

    <h2>Full Text</h2>
    {content_html}

    <div class="footer">
        This document was automatically generated from the PDF version.
    </div>
</body>
</html>
"""
        return html

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

    def save_converted_formats(self, pdf_path: str, base_path: str,
                               paper_title: str, paper_abstract: str) -> Tuple[bool, bool]:
        """
        Convert PDF to HTML and Markdown and save them.

        Args:
            pdf_path: Path to the PDF file
            base_path: Base path without extension (e.g., /path/to/paper-1-v1)
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper

        Returns:
            Tuple of (html_success, markdown_success)
        """
        html_success = False
        markdown_success = False

        try:
            # Generate HTML
            html_content = self.pdf_to_html(pdf_path, paper_title, paper_abstract)
            html_path = f"{base_path}.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            html_success = True
            print(f"✓ Generated HTML: {html_path}")
        except Exception as e:
            print(f"✗ Failed to generate HTML: {e}")

        try:
            # Generate Markdown
            markdown_content = self.pdf_to_markdown(pdf_path, paper_title, paper_abstract)
            markdown_path = f"{base_path}.md"
            with open(markdown_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            markdown_success = True
            print(f"✓ Generated Markdown: {markdown_path}")
        except Exception as e:
            print(f"✗ Failed to generate Markdown: {e}")

        return html_success, markdown_success


# Create singleton instance
pdf_converter = PDFConverter()
