"""
api/routers/auth.py — Register, login, forgot/reset password endpoints.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt

from fastapi import APIRouter, HTTPException, status
from jose import jwt
from pydantic import BaseModel

from utils.user_db import UserDB
from utils.email import send_email, password_reset_html

logger = logging.getLogger(__name__)

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


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordRequest):
    """
    Always returns 202 regardless of whether the email exists
    (prevents user enumeration).
    """
    user = _db.get_user_by_email(body.email)
    if user:
        reset_token = _db.create_reset_token(user["id"])
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"
        logger.info("Password reset token for %s: %s", body.email, reset_token)
        send_email(
            to=user["email"],
            subject="AutoScout AI — Reset your password",
            body=(
                f"Hi,\n\n"
                f"You requested a password reset for your AutoScout AI account.\n\n"
                f"Click the link below to set a new password (expires in 1 hour):\n\n"
                f"{reset_link}\n\n"
                f"If you did not request this, you can safely ignore this email.\n\n"
                f"— AutoScout AI"
            ),
            html=password_reset_html(reset_link),
        )
    return {"detail": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 6 characters")
    new_hash = _hash(body.password)
    ok = _db.consume_reset_token(body.token, new_hash)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Reset link is invalid or has expired")
    return {"detail": "Password updated. You can now sign in."}
