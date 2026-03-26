"""
api/routers/auth.py — Register + login endpoints returning JWT tokens.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt

from fastapi import APIRouter, HTTPException, status
from jose import jwt
from pydantic import BaseModel

from utils.user_db import UserDB

router = APIRouter(prefix="/auth", tags=["auth"])
_db = UserDB()


def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode(), hashed.encode())

JWT_SECRET = os.getenv("JWT_SECRET", "autoscout-dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def make_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 6 characters")
    if _db.get_user_by_email(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")
    hashed = _hash(body.password)
    user = _db.create_user(body.email, hashed)
    token = make_token(user["id"], user["email"])
    return {"token": token, "user": user}


@router.post("/login")
async def login(body: LoginRequest):
    user = _db.get_user_by_email(body.email)
    if not user or not _verify(body.password, user["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    safe_user = {k: v for k, v in user.items() if k != "hashed_password"}
    token = make_token(user["id"], user["email"])
    return {"token": token, "user": safe_user}
