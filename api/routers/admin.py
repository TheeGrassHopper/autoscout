"""
api/routers/admin.py — Admin-only endpoints for user management.

All endpoints require role='admin' in the JWT user. Non-admins receive 403.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional

from api.routers.auth import decode_token
from api.routers.users import current_user
from utils.user_db import UserDB

router = APIRouter(prefix="/admin", tags=["admin"])
_user_db = UserDB()


# ── Admin auth dependency ─────────────────────────────────────────────────────

def admin_user(request: Request) -> dict:
    user = current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ── User management ───────────────────────────────────────────────────────────

@router.get("/users")
def list_users(admin: dict = Depends(admin_user)):
    return _user_db.list_users()


@router.get("/users/{user_id}")
def get_user(user_id: int, admin: dict = Depends(admin_user)):
    user = _user_db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


class AdminUpdateUserRequest(BaseModel):
    role: Optional[str] = None
    notify_carvana: Optional[bool] = None
    email: Optional[str] = None


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: AdminUpdateUserRequest, admin: dict = Depends(admin_user)):
    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="role must be 'user' or 'admin'")
        _user_db.set_user_role(user_id, body.role)
    updated = _user_db.update_user(user_id, email=body.email, notify_carvana=body.notify_carvana)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return updated


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, admin: dict = Depends(admin_user)):
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    if not _user_db.delete_user(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")


@router.get("/users/{user_id}/searches")
def get_user_searches(user_id: int, admin: dict = Depends(admin_user)):
    return _user_db.get_searches(user_id)


@router.get("/users/{user_id}/favorites")
def get_user_favorites(user_id: int, admin: dict = Depends(admin_user)):
    return _user_db.get_favorites(user_id)
