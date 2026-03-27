"""API routes for AJAX/HTMX requests."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.categories import category_service

router = APIRouter(prefix="/api", tags=["api"])

@router.get("/categories/list")
async def list_categories():
    """Return all leaf categories for the category selector."""
    categories = category_service.get_all_leaf_categories()

    return JSONResponse({
        "categories": [
            {"path": path, "leaf": leaf}
            for path, leaf in categories
        ]
    })
