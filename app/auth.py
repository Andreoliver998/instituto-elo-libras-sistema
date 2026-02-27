import hmac
import os
import logging
from urllib.parse import urlencode, urlparse

from fastapi import Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from starlette.status import HTTP_303_SEE_OTHER

from .models import AdminUser

DEFAULT_ADMIN_HOME = "/admin/alunos"

logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")

def _env_admin_is_configured() -> bool:
    return bool((os.getenv("ADMIN_USER") or "").strip()) and bool((os.getenv("ADMIN_PASS") or "").strip())


def admin_db_is_configured(db: Session) -> bool:
    try:
        return db.query(AdminUser.id).first() is not None
    except OperationalError:
        return False


def admin_is_configured(db: Session | None = None) -> bool:
    if _env_admin_is_configured():
        return True
    if db is None:
        return False
    return admin_db_is_configured(db)


def is_admin_logged_in(request: Request) -> bool:
    return request.session.get("admin_auth") is True


def validate_next(next_value: str | None) -> str | None:
    value = (next_value or "").strip()
    if not value:
        return None

    if "://" in value:
        return None

    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None

    if not value.startswith("/") or value.startswith("//"):
        return None

    if not value.startswith("/admin"):
        return None

    if value.startswith("/admin/login") or value.startswith("/admin/logout"):
        return None

    return value


def safe_next(next_value: str | None) -> str:
    return validate_next(next_value) or DEFAULT_ADMIN_HOME


def verify_admin_credentials(username: str, password: str) -> bool:
    expected_user = (os.getenv("ADMIN_USER") or "").strip()
    expected_pass = (os.getenv("ADMIN_PASS") or "").strip()
    if not expected_user or not expected_pass:
        return False

    return hmac.compare_digest((username or "").strip(), expected_user) and hmac.compare_digest(
        (password or "").strip(),
        expected_pass,
    )


def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except Exception as exc:
        raise ValueError("Password hashing failed") from exc


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False


def verify_admin_credentials_db(db: Session, username: str, password: str) -> AdminUser | None:
    clean_username = (username or "").strip()
    if not clean_username or not password:
        return None

    user = (
        db.query(AdminUser)
        .filter(AdminUser.username == clean_username, AdminUser.is_active.is_(True))
        .first()
    )
    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user


def login_redirect(next_value: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/login?{urlencode({'next': safe_next(next_value)})}",
        status_code=HTTP_303_SEE_OTHER,
    )


def require_admin(request: Request, db: Session | None = None) -> RedirectResponse | None:
    if not admin_is_configured(db):
        current = request.url.path
        if request.url.query:
            current = f"{current}?{request.url.query}"
        return login_redirect(current)

    if is_admin_logged_in(request):
        return None

    current = request.url.path
    if request.url.query:
        current = f"{current}?{request.url.query}"
    return login_redirect(current)
