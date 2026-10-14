from fastapi import APIRouter

from app.api import auth, cases, classification, findings, misc, users, ws

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(cases.router)
api_router.include_router(findings.router)
api_router.include_router(misc.router)
api_router.include_router(classification.router)
api_router.include_router(ws.router)
