import hmac
import os
from urllib.parse import urlencode, urlparse

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

DEFAULT_ADMIN_HOME = "/admin/alunos"


def admin_is_configured() -> bool:
    return bool((os.getenv("ADMIN_USER") or "").strip()) and bool((os.getenv("ADMIN_PASS") or "").strip())


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


def login_redirect(next_value: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/login?{urlencode({'next': safe_next(next_value)})}",
        status_code=HTTP_303_SEE_OTHER,
    )


def require_admin(request: Request) -> RedirectResponse | None:
    if not admin_is_configured():
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
