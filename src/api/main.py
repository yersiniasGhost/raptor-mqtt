from pathlib import Path
import subprocess
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from raptor_common.utils import LogManager
lm = LogManager("vmc-ui.log")
logger = lm.get_logger("VMC")
lm.configure_library_loggers()
from routes import (monitor, messenger)


@asynccontextmanager
async def lifespan(fastapp: FastAPI):
    # Startup
    yield
    # Shutdown

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Valexy MQTT Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
logger.info("Created FastAPI VMM app")

# Initialize templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include routers
app.include_router(monitor.router)
app.include_router(messenger.router)
logger.info(f"Loaded templates and routes.")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
