"""Local dashboard app factory. Bind to 127.0.0.1 only (spec §16, §24)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from opportunity_radar import __version__
from opportunity_radar.web.routes import router

_WEB_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(str(_WEB_DIR / "templates")),
    autoescape=select_autoescape(default=True, default_for_string=True),
)
templates = Jinja2Templates(env=_env)


def create_app() -> FastAPI:
    app = FastAPI(title="Opportunity Radar", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
    app.include_router(router)
    return app
