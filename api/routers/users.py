"""
api/routers/users.py — Saved searches + user-scoped favorites.

All endpoints require a valid Bearer JWT in the Authorization header.
Users can only access their own resources (user_id in path must match token).
"""

import sqlite3
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.routers.auth import decode_token
from utils.user_db import UserDB

router = APIRouter(prefix="/users", tags=["users"])
_user_db = UserDB()

_MAIN_DB = os.getenv("DB_PATH", "output/autoscout.db")


# ── Auth dependency ──────────────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(auth[7:])
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = _user_db.get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def _require_self(user_id: int, user: dict):
    if user["id"] != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Access denied")


# ── Saved searches ───────────────────────────────────────────────────────────

class SearchCriteria(BaseModel):
    query: str = ""
    zip_code: str = "85001"
    radius_miles: int = 500
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    max_mileage: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None


class CreateSearchRequest(BaseModel):
    name: str
    criteria: SearchCriteria


@router.get("/{user_id}/searches")
def list_searches(user_id: int, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    return _user_db.get_searches(user_id)


@router.post("/{user_id}/searches", status_code=201)
def create_search(user_id: int, body: CreateSearchRequest, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    return _user_db.create_search(user_id, body.name, body.criteria.model_dump())


@router.post("/{user_id}/searches/preview")
def preview_search(user_id: int, body: SearchCriteria, user: dict = Depends(current_user)):
    """Filter current listings using ad-hoc criteria (no saved search needed)."""
    _require_self(user_id, user)
    c = body.model_dump()
    rows = []
    if os.path.exists(_MAIN_DB):
        conn = sqlite3.connect(_MAIN_DB)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM listings ORDER BY total_score DESC LIMIT 500"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()

    results = []
    for row in rows:
        d = dict(row)
        if c.get("make") and (d.get("make") or "").lower() != c["make"].lower():
            continue
        if c.get("model") and (d.get("model") or "").lower() != c["model"].lower():
            continue
        if c.get("min_year") and (d.get("year") or 0) < c["min_year"]:
            continue
        if c.get("max_year") and (d.get("year") or 9999) > c["max_year"]:
            continue
        if c.get("min_price") and (d.get("asking_price") or 0) < c["min_price"]:
            continue
        if c.get("max_price") and (d.get("asking_price") or 999999) > c["max_price"]:
            continue
        if c.get("max_mileage") and (d.get("mileage") or 0) > c["max_mileage"]:
            continue
        if c.get("query"):
            title = (d.get("title") or "").lower()
            if c["query"].lower() not in title:
                continue
        results.append(d)

    return {"count": len(results), "results": results}


@router.post("/{user_id}/searches/{search_id}/execute")
def execute_search(user_id: int, search_id: int, user: dict = Depends(current_user)):
    """Filter current listings in the main DB using the saved search criteria."""
    _require_self(user_id, user)
    saved = _user_db.get_search(search_id)
    if not saved or saved["user_id"] != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Search not found")

    c = saved["criteria"]
    rows = []
    if os.path.exists(_MAIN_DB):
        conn = sqlite3.connect(_MAIN_DB)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM listings ORDER BY total_score DESC LIMIT 500"
            ).fetchall()
        except sqlite3.OperationalError:
            # listings table doesn't exist yet (pipeline never run)
            rows = []
        finally:
            conn.close()

    results = []
    for row in rows:
        d = dict(row)
        if c.get("make") and (d.get("make") or "").lower() != c["make"].lower():
            continue
        if c.get("model") and (d.get("model") or "").lower() != c["model"].lower():
            continue
        if c.get("min_year") and (d.get("year") or 0) < c["min_year"]:
            continue
        if c.get("max_year") and (d.get("year") or 9999) > c["max_year"]:
            continue
        if c.get("min_price") and (d.get("asking_price") or 0) < c["min_price"]:
            continue
        if c.get("max_price") and (d.get("asking_price") or 999999) > c["max_price"]:
            continue
        if c.get("max_mileage") and (d.get("mileage") or 0) > c["max_mileage"]:
            continue
        if c.get("query"):
            title = (d.get("title") or "").lower()
            if c["query"].lower() not in title:
                continue
        results.append(d)

    _user_db.save_search_results(search_id, results)
    return {"search_id": search_id, "count": len(results), "results": results}


@router.patch("/{user_id}/searches/{search_id}")
def update_search(user_id: int, search_id: int, body: CreateSearchRequest, user: dict = Depends(current_user)):
    """Update the name and/or criteria of an existing saved search."""
    _require_self(user_id, user)
    updated = _user_db.update_search(search_id, user_id, body.name, body.criteria.model_dump())
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Search not found")
    return updated


@router.delete("/{user_id}/searches/{search_id}", status_code=204)
def delete_search(user_id: int, search_id: int, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    if not _user_db.delete_search(search_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Search not found")


@router.delete("/{user_id}/searches")
def delete_all_searches(user_id: int, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    count = _user_db.delete_all_searches(user_id)
    return {"deleted": count}


# ── User favorites ───────────────────────────────────────────────────────────

class AddFavoriteRequest(BaseModel):
    listing_data: dict


@router.get("/{user_id}/favorites")
def get_favorites(user_id: int, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    return _user_db.get_favorites(user_id)


@router.post("/{user_id}/favorites", status_code=201)
def add_favorite(user_id: int, body: AddFavoriteRequest, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    listing_id = body.listing_data.get("listing_id")
    if not listing_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="listing_data must include listing_id")
    return _user_db.add_favorite(user_id, listing_id, body.listing_data)


@router.delete("/{user_id}/favorites/{listing_id}", status_code=204)
def remove_favorite(user_id: int, listing_id: str, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    if not _user_db.remove_favorite(user_id, listing_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Favorite not found")


# ── Profile ───────────────────────────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    email: Optional[str] = None
    notify_carvana: Optional[bool] = None


@router.get("/{user_id}")
def get_profile(user_id: int, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    return user  # already safe (no password), includes role + notify_carvana


@router.patch("/{user_id}")
def update_profile(user_id: int, body: UpdateProfileRequest, user: dict = Depends(current_user)):
    _require_self(user_id, user)
    updated = _user_db.update_user(user_id, email=body.email, notify_carvana=body.notify_carvana)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return updated
