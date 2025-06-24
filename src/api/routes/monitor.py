from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
from . import templates
from raptor_common.utils import LogManager

logger = LogManager().get_logger(__name__)
router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/")
async def monitor(request: Request):
    try:
        return templates.TemplateResponse(
            "monitor.html",
            {
                "request": request,
                "error": None
            }
        )
    except Exception as e:
        logger.error(f"Error in Analysis route: {e}")
        return templates.TemplateResponse(
            "analysis.html",
            {
                "error": str(e)
            }
        )
