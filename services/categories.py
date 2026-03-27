"""Academic discipline categorization service."""
import json
from pathlib import Path
from typing import List, Dict, Tuple

class CategoryService:
    """Service for managing hierarchical academic categories."""

    def __init__(self):
        self.categories_file = Path(__file__).parent.parent / "data" / "academic_disciplines.json"
        self._categories = None

    def load_categories(self) -> Dict:
        """Load categories from JSON file."""
        if self._categories is None:
            with open(self.categories_file, 'r', encoding='utf-8') as f:
                self._categories = json.load(f)
        return self._categories

    def get_all_leaf_categories(self) -> List[Tuple[str, str]]:
        """
        Get all leaf (deepest) categories with their full paths.
        Returns: List of (full_path, leaf_name) tuples.
        """
        categories = self.load_categories()
        leaf_categories = []

        def traverse(node, path=[]):
            if isinstance(node, dict):
                for key, value in node.items():
                    current_path = path + [key]
                    if isinstance(value, list):
                        # This key has a list of leaf categories
                        for leaf in value:
                            full_path = " > ".join(current_path + [leaf])
                            leaf_categories.append((full_path, leaf))
                    elif isinstance(value, dict):
                        # Recurse into nested dict
                        traverse(value, current_path)
                    else:
                        # Single leaf category
                        full_path = " > ".join(current_path)
                        leaf_categories.append((full_path, key))
            elif isinstance(node, list):
                # Direct list of leaves at this level
                for leaf in node:
                    full_path = " > ".join(path + [leaf])
                    leaf_categories.append((full_path, leaf))

        traverse(categories)
        return sorted(leaf_categories, key=lambda x: x[0])

    def get_hierarchical_structure(self) -> Dict:
        """Get the full hierarchical structure for display."""
        return self.load_categories()

    def get_category_level(self, full_path: str) -> int:
        """Get the level/depth of a category path."""
        return len(full_path.split(" > "))

    def search_categories(self, query: str, limit: int = 20) -> List[Tuple[str, str]]:
        """
        Search categories by keyword.
        Returns: List of (full_path, leaf_name) tuples matching the query.
        """
        query = query.lower()
        all_categories = self.get_all_leaf_categories()

        # Find matches
        matches = [
            (path, leaf) for path, leaf in all_categories
            if query in path.lower() or query in leaf.lower()
        ]

        return matches[:limit]

    def get_categories_by_discipline(self, discipline: str) -> List[Tuple[str, str]]:
        """
        Get all categories under a specific top-level discipline.
        """
        all_categories = self.get_all_leaf_categories()
        return [
            (path, leaf) for path, leaf in all_categories
            if path.startswith(discipline)
        ]


# Create singleton instance
category_service = CategoryService()
