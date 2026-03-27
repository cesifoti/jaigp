"""Image processing service for thumbnail generation and optimization."""
from PIL import Image
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ImageProcessor:
    """Handle image processing tasks like thumbnail generation."""

    def generate_thumbnail(self, source_path: Path, max_width: int = 600, quality: int = 85) -> Path:
        """
        Generate optimized thumbnail for homepage cards.

        Args:
            source_path: Path to source image
            max_width: Maximum width in pixels (default 600px for homepage cards)
            quality: JPEG quality 1-100 (default 85)

        Returns:
            Path to generated thumbnail
        """
        try:
            # Open image
            img = Image.open(source_path)

            # Convert RGBA to RGB if needed (for PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Calculate aspect-preserving dimensions
            aspect = img.height / img.width
            new_width = min(max_width, img.width)
            new_height = int(new_width * aspect)

            # Resize with high-quality resampling
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Generate thumbnail filename
            thumb_path = source_path.parent / f"{source_path.stem}_thumb.jpg"

            # Save as optimized JPEG
            img.save(thumb_path, 'JPEG', quality=quality, optimize=True)

            logger.info(f"Generated thumbnail: {thumb_path} ({new_width}x{new_height})")
            return thumb_path

        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {source_path}: {e}")
            raise

    def get_image_dimensions(self, image_path: Path) -> tuple:
        """Get image dimensions without loading full image."""
        try:
            img = Image.open(image_path)
            return img.size
        except Exception as e:
            logger.error(f"Failed to get dimensions for {image_path}: {e}")
            return (0, 0)

# Create singleton instance
image_processor = ImageProcessor()
