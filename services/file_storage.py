"""Date-based file storage service."""
from pathlib import Path
from datetime import datetime
import aiofiles
import secrets
import config
from typing import Tuple, Optional
from services.pdf_converter import pdf_converter

class FileStorageService:
    """Service for managing date-based file storage."""

    def __init__(self):
        self.base_dir = config.PAPERS_DIR

    def get_date_path(self, date: datetime = None) -> Path:
        """Generate date-based directory path (YYYY/Month/DD)."""
        if date is None:
            date = datetime.utcnow()

        year = str(date.year)
        month = date.strftime("%B")  # Full month name (e.g., "February")
        day = str(date.day).zfill(2)  # Zero-padded day (e.g., "14")

        return self.base_dir / year / month / day

    def ensure_date_directory(self, date: datetime = None) -> Path:
        """Create date-based directory if it doesn't exist."""
        date_path = self.get_date_path(date)
        date_path.mkdir(parents=True, exist_ok=True)
        return date_path

    def generate_filename(self, paper_id: int, version: int, extension: str) -> str:
        """Generate standardized filename for paper PDF."""
        # Format: paper-{id}-v{version}.pdf
        return f"paper-{paper_id}-v{version}{extension}"

    def generate_image_filename(self, paper_id: int, extension: str) -> str:
        """Generate standardized filename for paper cover image."""
        # Format: paper-{id}-image.{ext}
        return f"paper-{paper_id}-image{extension}"

    async def save_pdf(
        self,
        file_content: bytes,
        paper_id: int,
        version: int,
        date: datetime = None,
        paper_title: str = "",
        paper_abstract: str = ""
    ) -> Tuple[str, Path]:
        """
        Save PDF file to date-based directory and generate HTML/Markdown versions.
        Returns: (filename, full_path)
        """
        # Ensure directory exists
        date_dir = self.ensure_date_directory(date)

        # Generate filename
        filename = self.generate_filename(paper_id, version, ".pdf")
        file_path = date_dir / filename

        # Save PDF file
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Generate HTML and Markdown versions
        if paper_title and paper_abstract:
            base_path = str(file_path).rsplit('.', 1)[0]  # Remove .pdf extension
            try:
                pdf_converter.save_converted_formats(
                    str(file_path),
                    base_path,
                    paper_title,
                    paper_abstract
                )
            except Exception as e:
                print(f"Warning: Could not generate HTML/Markdown versions: {e}")

        return filename, file_path

    async def save_image(
        self,
        file_content: bytes,
        paper_id: int,
        extension: str,
        date: datetime = None
    ) -> Tuple[str, Path]:
        """
        Save cover image to date-based directory and generate thumbnail.
        Returns: (filename, full_path)
        """
        # Ensure directory exists
        date_dir = self.ensure_date_directory(date)

        # Generate filename
        filename = self.generate_image_filename(paper_id, extension)
        file_path = date_dir / filename

        # Save file
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Generate thumbnail for homepage (async in background)
        try:
            from services.image_processor import image_processor
            thumbnail_path = image_processor.generate_thumbnail(file_path)
            print(f"✓ Generated thumbnail: {thumbnail_path.name}")
        except Exception as e:
            print(f"Warning: Failed to generate thumbnail for {filename}: {e}")
            # Don't fail the upload if thumbnail generation fails

        return filename, file_path

    def get_file_path(self, filename: str, date: datetime) -> Path:
        """Get full path to a file based on filename and date."""
        date_dir = self.get_date_path(date)
        return date_dir / filename

    async def read_file(self, file_path: Path) -> Optional[bytes]:
        """Read file from storage."""
        try:
            if not file_path.exists():
                return None

            async with aiofiles.open(file_path, 'rb') as f:
                return await f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return None

    def delete_file(self, file_path: Path) -> bool:
        """Delete file from storage."""
        try:
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
            return False

    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes."""
        try:
            if file_path.exists():
                return file_path.stat().st_size
            return 0
        except Exception:
            return 0

# Create singleton instance
file_storage = FileStorageService()
