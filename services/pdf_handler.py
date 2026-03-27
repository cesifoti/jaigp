"""PDF file processing and validation service."""
from fastapi import UploadFile, HTTPException
from pypdf import PdfReader
import io
import config
from typing import Dict, Any, Optional

# Maximum page height in points before we consider it oversized.
# US Letter is 792pt tall; A4 is 842pt. Anything over 2000pt (about 28in)
# is almost certainly a "single-page" export that browsers can't render.
MAX_PAGE_HEIGHT_PTS = 2000

class PDFHandler:
    """Service for PDF file validation and processing."""

    def __init__(self):
        self.max_size = config.MAX_FILE_SIZE_BYTES
        self.allowed_types = config.ALLOWED_PDF_TYPES

    async def validate_pdf(self, file: UploadFile) -> bytes:
        """
        Validate PDF file (size, type, structure).
        Auto-repaginates oversized single-page PDFs (e.g. from "Just One Page PDF").
        Returns file content as bytes if valid.
        """
        # Check content type
        if file.content_type not in self.allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Only PDF files are allowed. Got: {file.content_type}"
            )

        # Read file content
        content = await file.read()

        # Check file size
        if len(content) > self.max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE_MB}MB"
            )

        # Validate PDF structure
        try:
            pdf_reader = PdfReader(io.BytesIO(content))
            num_pages = len(pdf_reader.pages)

            if num_pages == 0:
                raise HTTPException(
                    status_code=400,
                    detail="PDF file is empty or corrupted"
                )

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid PDF file: {str(e)}"
            )

        # Check for oversized pages and auto-repaginate if needed
        content = self._repaginate_if_oversized(content)

        # Reset file pointer for potential re-reading
        await file.seek(0)

        return content

    def _repaginate_if_oversized(self, content: bytes) -> bytes:
        """Check if any page exceeds MAX_PAGE_HEIGHT_PTS and repaginate.

        Some tools (e.g. "Just One Page PDF" Chrome extension) produce PDFs
        where the entire document is a single page tens of thousands of points
        tall. Browser PDF viewers can't render these — the text is invisible
        even though it's selectable. This method detects that and splits the
        content into standard Letter-sized pages.
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=content, filetype="pdf")
            needs_repagination = False

            for page in doc:
                if page.rect.height > MAX_PAGE_HEIGHT_PTS:
                    needs_repagination = True
                    break

            if not needs_repagination:
                doc.close()
                return content

            # Repaginate: split oversized pages into Letter-sized pages
            TARGET_W = 612.0  # US Letter width in points
            TARGET_H = 792.0  # US Letter height in points

            dst = fitz.open()

            for page_idx in range(len(doc)):
                src_page = doc[page_idx]
                src_w = src_page.rect.width
                src_h = src_page.rect.height

                if src_h <= MAX_PAGE_HEIGHT_PTS:
                    # Normal page — copy as-is
                    dst.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                    continue

                # Oversized page — slice into Letter-height strips
                scale = TARGET_W / src_w
                strip_h = TARGET_H / scale  # height of one strip in source coords
                num_strips = int(src_h / strip_h) + 1

                for i in range(num_strips):
                    y_start = i * strip_h
                    y_end = min(y_start + strip_h, src_h)
                    if y_start >= src_h:
                        break

                    clip = fitz.Rect(0, y_start, src_w, y_end)
                    new_page = dst.new_page(width=TARGET_W, height=TARGET_H)
                    new_page.show_pdf_page(
                        fitz.Rect(0, 0, TARGET_W, TARGET_H),
                        doc, page_idx, clip=clip,
                    )

            # Remove trailing blank pages
            while len(dst) > 1:
                last_pix = dst[-1].get_pixmap(dpi=36)
                white_ratio = last_pix.samples.count(255) / len(last_pix.samples)
                if white_ratio > 0.999:
                    dst.delete_page(-1)
                else:
                    break

            result = dst.tobytes()
            page_count = len(dst)
            dst.close()
            doc.close()

            print(f"PDF repaginated: oversized page detected, split into {page_count} Letter pages")
            return result

        except ImportError:
            # PyMuPDF not available — skip repagination silently
            return content
        except Exception as e:
            # Don't fail the upload if repagination fails — return original
            print(f"WARNING: PDF repagination failed: {e}")
            return content

    async def get_pdf_metadata(self, content: bytes) -> Dict[str, Any]:
        """Extract metadata from PDF file."""
        try:
            pdf_reader = PdfReader(io.BytesIO(content))

            metadata = {
                "num_pages": len(pdf_reader.pages),
                "metadata": {}
            }

            # Extract PDF metadata
            if pdf_reader.metadata:
                metadata["metadata"] = {
                    "title": pdf_reader.metadata.get("/Title", ""),
                    "author": pdf_reader.metadata.get("/Author", ""),
                    "subject": pdf_reader.metadata.get("/Subject", ""),
                    "creator": pdf_reader.metadata.get("/Creator", ""),
                }

            return metadata

        except Exception as e:
            print(f"Error extracting PDF metadata: {e}")
            return {"num_pages": 0, "metadata": {}}

    def get_extension_from_filename(self, filename: str) -> str:
        """Extract file extension from filename."""
        if '.' in filename:
            return '.' + filename.rsplit('.', 1)[1].lower()
        return ''

    async def validate_image(self, file: UploadFile) -> bytes:
        """
        Validate image file (size, type).
        Returns file content as bytes if valid.
        """
        # Check content type
        if file.content_type not in config.ALLOWED_IMAGE_TYPES:
            allowed = ", ".join([t.split('/')[-1] for t in config.ALLOWED_IMAGE_TYPES])
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image type. Allowed: {allowed}. Got: {file.content_type}"
            )

        # Read file content
        content = await file.read()

        # Check file size
        if len(content) > self.max_size:
            raise HTTPException(
                status_code=400,
                detail=f"Image too large. Maximum size is {config.MAX_FILE_SIZE_MB}MB"
            )

        # Validate image using Pillow
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            img.verify()  # Verify it's a valid image

            # Optional: Check minimum dimensions
            # if img.width < 800 or img.height < 600:
            #     raise HTTPException(
            #         status_code=400,
            #         detail="Image too small. Minimum size is 800x600"
            #     )

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image file: {str(e)}"
            )

        # Reset file pointer
        await file.seek(0)

        return content

# Create singleton instance
pdf_handler = PDFHandler()
