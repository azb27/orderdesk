"""Sessions and roles. A signed, http-only cookie holds the user id; roles are checked on the server.

CSRF: the cookie is SameSite=Lax, and every state-changing /api request must carry the X-Orderdesk header,
which a cross-site form can't send.
"""

from __future__ import annotations

import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from orderdesk.db.models import User
from orderdesk.db.session import get_session

COOKIE = "od_session"
MAX_AGE = 12 * 3600
_ph = PasswordHasher()
_secret = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)  # unset: sessions end on restart
_signer = URLSafeTimedSerializer(_secret, salt="orderdesk-session")


def login(s: Session, response: Response, email: str, password: str) -> User:
    user = s.scalar(select(User).where(User.email == email.strip().lower()))
    try:
        if user is None:
            _ph.verify(_ph.hash("x"), password + "!")  # same work either way: no user-enumeration by timing
            raise VerifyMismatchError
        _ph.verify(user.password_hash, password)
    except VerifyMismatchError:
        raise HTTPException(401, "wrong email or password") from None
    response.set_cookie(COOKIE, _signer.dumps({"uid": user.id}), max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=os.environ.get("COOKIE_SECURE") == "1")  # fmt: skip
    return user


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE)


def current_user(request: Request, s: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "sign in first")
    try:
        uid = _signer.loads(token, max_age=MAX_AGE)["uid"]
    except (BadSignature, SignatureExpired, KeyError):
        raise HTTPException(401, "session expired; sign in again") from None
    user = s.get(User, uid)
    if user is None:
        raise HTTPException(401, "sign in first")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Orderdesk") != "1":
        raise HTTPException(403, "missing X-Orderdesk header")
    return user


def supervisor(user: User = Depends(current_user)) -> User:
    if user.role != "supervisor":
        raise HTTPException(403, "supervisors only")
    return user
