"""Rules page — comprehensive documentation of JAIGP journal processes."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters

router = APIRouter(tags=["rules"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    """Display the journal rules and processes."""
    user = request.session.get("user")
    return templates.TemplateResponse("rules.html", {"request": request, "user": user})
