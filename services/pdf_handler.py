"""PDF file processing and validation service."""
from fastapi import UploadFile, HTTPException
from pypdf import PdfReader
import io
import config
from typing import Dict, Any, Optional

class PDFHandler:
    """Service for PDF file validation and processing."""

    def __init__(self):
        self.max_size = config.MAX_FILE_SIZE_BYTES
        self.allowed_types = config.ALLOWED_PDF_TYPES

    async def validate_pdf(self, file: UploadFile) -> bytes:
        """
        Validate PDF file (size, type, structure).
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

        # Reset file pointer for potential re-reading
        await file.seek(0)

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
