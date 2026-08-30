from __future__ import annotations
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as StarletteHTTPException
from api.routes import moderation
from api.auth import get_http_session

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    session = await get_http_session()
    if session and not session.closed:
        await session.close()

api_app = FastAPI(title="Dopamine Bot API", lifespan=lifespan)

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dopaminestudios.in",
        "https://www.dopaminestudios.in",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@api_app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
    )

@api_app.exception_handler(sqlite3.Error)
async def sqlite_exception_handler(request: Request, exc: sqlite3.Error):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "message": "Database error occurred."},
    )

@api_app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "message": "An internal server error occurred."},
    )

api_app.include_router(moderation.router)

@api_app.get("/health")
async def health_check():
    return {"status": "healthy"}
