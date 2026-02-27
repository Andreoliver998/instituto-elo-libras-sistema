import os
import secrets
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import quote, urlencode, urlparse
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError

from .db import Base, engine, get_db
from .models import AdminAuditLog, AdminUser, Student
from .auth import (
    admin_is_configured,
    admin_db_is_configured,
    is_admin_logged_in,
    hash_password,
    verify_password,
    require_admin,
    safe_next,
    validate_next,
    verify_admin_credentials,
    verify_admin_credentials_db,
)

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _is_prod_env() -> bool:
    for key in ("ENV", "ENVIRONMENT", "PYTHON_ENV", "FASTAPI_ENV"):
        value = (os.getenv(key) or "").strip().lower()
        if value in {"prod", "production"}:
            return True
    if (os.getenv("RENDER_EXTERNAL_URL") or "").strip():
        return True
    return False


admin_secret_key = (os.getenv("ADMIN_SECRET_KEY") or "").strip() or secrets.token_urlsafe(32)
app.add_middleware(
    SessionMiddleware,
    secret_key=admin_secret_key,
    session_cookie="admin_session",
    path="/admin",
    max_age=43200,
    same_site="lax",
    https_only=_is_prod_env(),
)

def _static_url(request: Request, path: str) -> str:
    url = str(request.url_for("static", path=path))
    try:
        posix_path = PurePosixPath(path)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            raise ValueError("Invalid static path")

        full_path = BASE_DIR / "static" / Path(*posix_path.parts)
        version = int(full_path.stat().st_mtime) if full_path.is_file() else 0
    except (OSError, ValueError):
        version = 0
    return f"{url}?v={version}"

templates.env.globals["static_url"] = _static_url


def _date_br(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value)


templates.env.filters["date_br"] = _date_br


def _cpf_br(value) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 11:
        return str(value)
    return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"


templates.env.filters["cpf_br"] = _cpf_br

def _sqlite_ensure_students_columns() -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "students" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("students")}
    desired: dict[str, str] = {
        "logradouro": "TEXT",
        "numero": "TEXT",
        "complemento": "TEXT",
        "bairro": "TEXT",
        "cidade": "TEXT",
        "uf": "TEXT",
        "cep": "TEXT",
        "cpf": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'cadastrado'",
    }

    missing = [(name, ddl) for name, ddl in desired.items() if name not in existing]
    if not missing:
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE students ADD COLUMN {name} {ddl}"))


def _sqlite_ensure_admin_users_columns() -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "admin_users" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("admin_users")}
    desired: dict[str, str] = {
        "updated_at": "DATETIME",
    }

    missing = [(name, ddl) for name, ddl in desired.items() if name not in existing]
    if not missing:
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            try:
                conn.execute(text(f"ALTER TABLE admin_users ADD COLUMN {name} {ddl}"))
            except Exception:
                return

        try:
            conn.execute(text("UPDATE admin_users SET updated_at = created_at WHERE updated_at IS NULL"))
        except Exception:
            return

# MVP: cria tabelas automaticamente
Base.metadata.create_all(bind=engine)
_sqlite_ensure_students_columns()
_sqlite_ensure_admin_users_columns()

CHECKOUT_URL = (os.getenv("CHECKOUT_URL") or "/obrigado").strip()
WHATSAPP_GROUP_URL = (os.getenv("WHATSAPP_GROUP_URL") or "").strip()
ADMIN_STATUS_OPTIONS = ["cadastrado", "pago", "pendente", "concluido"]

def _is_valid_http_url(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if value == "https://SEU-LINK-DE-PAGAMENTO":
        return False
    if value.startswith("//"):
        return False
    # Permite caminho relativo para facilitar dev/local (ex.: CHECKOUT_URL=/obrigado).
    if value.startswith("/"):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None

def _clean_cpf(value: str | None) -> str | None:
    cleaned = _clean_optional_str(value)
    if not cleaned:
        return None

    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) != 11:
        return None
    return digits

def _clean_uf(value: str | None) -> str | None:
    cleaned = _clean_optional_str(value)
    if not cleaned:
        return None
    cleaned = cleaned.upper()
    if len(cleaned) != 2:
        return None
    return cleaned

def _clean_status(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in ADMIN_STATUS_OPTIONS:
        return cleaned
    return "cadastrado"

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(
    request: Request,
    next: str | None = None,
    msg: str | None = None,
    db: Session = Depends(get_db),
):
    next_target = safe_next(next)
    configured = admin_is_configured(db)
    if is_admin_logged_in(request):
        return RedirectResponse(url=next_target, status_code=303)

    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "next": next_target,
            "configured": configured,
            "msg": (msg or "").strip(),
            "error": None,
        },
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(None),
    db: Session = Depends(get_db),
):
    next_target = safe_next(next)
    configured = admin_is_configured(db)

    if not configured:
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "next": next_target,
                "configured": False,
                "msg": None,
                "error": "Acesso administrativo indisponível. Realize a configuração inicial.",
            },
            status_code=503,
        )

    db_user = verify_admin_credentials_db(db, username, password) if admin_db_is_configured(db) else None
    env_ok = verify_admin_credentials(username, password)
    if db_user or env_ok:
        request.session["admin_auth"] = True
        request.session["admin_user"] = (db_user.username if db_user else (username or "")).strip()
        request.session["admin_role"] = (db_user.role if db_user else "owner")
        destination = validate_next(next) or "/admin/alunos"
        return RedirectResponse(
            url=f"/admin?{urlencode({'next': destination})}",
            status_code=303,
        )

    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "next": next_target,
            "configured": configured,
            "msg": None,
            "error": "Credenciais inválidas.",
        },
        status_code=401,
    )


@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@app.get("/admin/minha-senha", response_class=HTMLResponse)
def admin_change_password_form(
    request: Request,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "admin_change_password.html",
        {
            "request": request,
            "error": None,
        },
    )


@app.post("/admin/minha-senha", response_class=HTMLResponse)
def admin_change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    username = (request.session.get("admin_user") or "").strip()
    if not username:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=303)

    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/admin/login", status_code=303)

    if not verify_password(current_password or "", user.password_hash or ""):
        return templates.TemplateResponse(
            "admin_change_password.html",
            {"request": request, "error": "Senha atual incorreta."},
            status_code=400,
        )

    if len(new_password or "") < 8:
        return templates.TemplateResponse(
            "admin_change_password.html",
            {"request": request, "error": "A nova senha deve ter no mínimo 8 caracteres."},
            status_code=400,
        )

    if (new_password or "") != (confirm_password or ""):
        return templates.TemplateResponse(
            "admin_change_password.html",
            {"request": request, "error": "As senhas não coincidem."},
            status_code=400,
        )

    try:
        user.password_hash = hash_password(new_password)
        user.updated_at = datetime.utcnow()
        db.add(user)
        db.commit()
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "admin_change_password.html",
            {"request": request, "error": "Não foi possível atualizar sua senha. Tente novamente."},
            status_code=500,
        )

    request.session.clear()
    return RedirectResponse(url="/admin/login?msg=password_updated", status_code=303)


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_splash(request: Request, next: str | None = None):
    validated = validate_next(next)
    if validated:
        next_url = validated
    else:
        next_url = "/admin/alunos" if is_admin_logged_in(request) else "/admin/login"
    return templates.TemplateResponse(
        "admin_splash.html",
        {
            "request": request,
            "next_url": next_url,
        },
    )

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    checkout_value = (CHECKOUT_URL or "").strip()
    checkout_enabled = _is_valid_http_url(checkout_value)
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "checkout_url": checkout_value if checkout_enabled else "",
            "checkout_enabled": checkout_enabled,
        },
    )

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    filename = "INSTITUTO ELO LIBRAS Ensino de LIBRAS Online2.0.0.png"
    return RedirectResponse(
        url=f"/static/assets/{quote(filename)}",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/app/templates/{template_name}.html", include_in_schema=False)
def template_path_redirect(template_name: str):
    redirects = {
        "home": "/",
        "obrigado": "/obrigado",
        "cadastro": "/cadastro",
    }
    target = redirects.get(template_name)
    if not target:
        return RedirectResponse(url="/")
    return RedirectResponse(url=target)

@app.get("/obrigado", response_class=HTMLResponse)
def obrigado(request: Request):
    # Configure esta URL como "URL de sucesso" no Mercado Pago
    return templates.TemplateResponse("obrigado.html", {"request": request, "cadastro_url": "/cadastro"})

@app.get("/cadastro", response_class=HTMLResponse)
def cadastro_form(request: Request):
    return templates.TemplateResponse("cadastro.html", {"request": request})

@app.post("/cadastro", response_class=HTMLResponse)
def cadastro_submit(
    request: Request,
    nome: str = Form(...),
    whatsapp: str = Form(...),
    email: str = Form(None),
    origem: str = Form(None),
    email_pagamento: str = Form(None),
    cpf: str = Form(None),
    cep: str = Form(None),
    uf: str = Form(None),
    cidade: str = Form(None),
    bairro: str = Form(None),
    logradouro: str = Form(None),
    numero: str = Form(None),
    complemento: str = Form(None),
    db: Session = Depends(get_db),
):
    aluno = Student(
        nome=nome.strip(),
        whatsapp=whatsapp.strip(),
        email=_clean_optional_str(email),
        origem=_clean_optional_str(origem),
        email_pagamento=_clean_optional_str(email_pagamento),
        cpf=_clean_cpf(cpf),
        cep=_clean_optional_str(cep),
        uf=_clean_uf(uf),
        cidade=_clean_optional_str(cidade),
        bairro=_clean_optional_str(bairro),
        logradouro=_clean_optional_str(logradouro),
        numero=_clean_optional_str(numero),
        complemento=_clean_optional_str(complemento),
    )
    db.add(aluno)
    db.commit()
    db.refresh(aluno)

    return templates.TemplateResponse(
        "sucesso.html",
        {"request": request, "nome": aluno.nome, "whatsapp_group_url": WHATSAPP_GROUP_URL},
    )

@app.get("/sucesso", response_class=HTMLResponse)
def sucesso(request: Request, nome: str | None = None):
    return templates.TemplateResponse(
        "sucesso.html",
        {
            "request": request,
            "nome": (nome or "Aluno").strip() or "Aluno",
            "whatsapp_group_url": WHATSAPP_GROUP_URL,
        },
    )

@app.get("/admin/alunos", response_class=HTMLResponse)
def admin_alunos(
    request: Request,
    q: str | None = None,
    msg: str | None = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    safe_page = max(1, page)
    safe_per_page = min(max(1, per_page), 200)
    query = db.query(Student)

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Student.nome.ilike(like),
                Student.whatsapp.ilike(like),
                Student.email.ilike(like),
                Student.cpf.ilike(like),
            )
        )

    total = query.count()
    alunos = (
        query.order_by(Student.created_at.desc())
        .offset((safe_page - 1) * safe_per_page)
        .limit(safe_per_page)
        .all()
    )

    total_pages = max(1, (total + safe_per_page - 1) // safe_per_page)
    return templates.TemplateResponse(
        "admin_alunos.html",
        {
            "request": request,
            "alunos": alunos,
            "q": search,
            "msg": (msg or "").strip(),
            "page": safe_page,
            "per_page": safe_per_page,
            "total": total,
            "total_pages": total_pages,
            "status_options": ADMIN_STATUS_OPTIONS,
        },
    )

@app.get("/admin/alunos/{student_id}", response_class=HTMLResponse)
def admin_aluno_editar_form(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    aluno = db.query(Student).filter(Student.id == student_id).first()
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")

    return templates.TemplateResponse(
        "admin_aluno_edit.html",
        {
            "request": request,
            "aluno": aluno,
            "status_options": ADMIN_STATUS_OPTIONS,
            "danger_error": None,
        },
    )

@app.post("/admin/alunos/{student_id}")
def admin_aluno_editar_submit(
    request: Request,
    student_id: int,
    nome: str = Form(...),
    whatsapp: str = Form(...),
    email: str = Form(None),
    cpf: str = Form(None),
    origem: str = Form(None),
    status: str = Form("cadastrado"),
    cep: str = Form(None),
    uf: str = Form(None),
    cidade: str = Form(None),
    bairro: str = Form(None),
    logradouro: str = Form(None),
    numero: str = Form(None),
    complemento: str = Form(None),
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    aluno = db.query(Student).filter(Student.id == student_id).first()
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")

    aluno.nome = nome.strip()
    aluno.whatsapp = whatsapp.strip()
    aluno.email = _clean_optional_str(email)
    aluno.cpf = _clean_cpf(cpf)
    aluno.origem = _clean_optional_str(origem)
    aluno.status = _clean_status(status)
    aluno.cep = _clean_optional_str(cep)
    aluno.uf = _clean_uf(uf)
    aluno.cidade = _clean_optional_str(cidade)
    aluno.bairro = _clean_optional_str(bairro)
    aluno.logradouro = _clean_optional_str(logradouro)
    aluno.numero = _clean_optional_str(numero)
    aluno.complemento = _clean_optional_str(complemento)

    db.add(aluno)
    db.commit()

    return RedirectResponse(url=f"/admin/alunos/{student_id}", status_code=303)


@app.post("/admin/alunos/{student_id}/delete", response_class=HTMLResponse)
def admin_aluno_delete(
    request: Request,
    student_id: int,
    confirm_text: str = Form(...),
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    aluno = db.query(Student).filter(Student.id == student_id).first()
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")

    if confirm_text != "EXCLUIR":
        return templates.TemplateResponse(
            "admin_aluno_edit.html",
            {
                "request": request,
                "aluno": aluno,
                "status_options": ADMIN_STATUS_OPTIONS,
                "danger_error": "Digite EXCLUIR exatamente para confirmar.",
            },
            status_code=400,
        )

    admin_user = request.session.get("admin_user")
    ip = request.client.host if request.client else None

    log = AdminAuditLog(
        action="DELETE_STUDENT",
        admin_user=(admin_user or "").strip() or None,
        student_id=aluno.id,
        student_name=(aluno.nome or "").strip() or None,
        student_whatsapp=(aluno.whatsapp or "").strip() or None,
        ip=(ip or "").strip() or None,
    )

    try:
        db.add(log)
        db.delete(aluno)
        db.commit()
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "admin_aluno_edit.html",
            {
                "request": request,
                "aluno": aluno,
                "status_options": ADMIN_STATUS_OPTIONS,
                "danger_error": "Não foi possível concluir a exclusão. Tente novamente.",
            },
            status_code=500,
        )

    return RedirectResponse(url="/admin/alunos?msg=deleted", status_code=303)


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(
    request: Request,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    logs = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(50).all()
    return templates.TemplateResponse(
        "admin_logs.html",
        {
            "request": request,
            "logs": logs,
        },
    )

@app.get("/admin/alunos.csv")
def admin_alunos_csv(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request, db)
    if redirect:
        return redirect

    import csv
    import io

    query = db.query(Student)
    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Student.nome.ilike(like),
                Student.whatsapp.ilike(like),
                Student.email.ilike(like),
                Student.cpf.ilike(like),
            )
        )

    alunos = query.order_by(Student.created_at.desc()).all()

    def iter_rows(items: Iterable[Student]):
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "id",
                "nome",
                "whatsapp",
                "email",
                "cpf",
                "origem",
                "status",
                "email_pagamento",
                "cep",
                "uf",
                "cidade",
                "bairro",
                "logradouro",
                "numero",
                "complemento",
                "created_at",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for aluno in items:
            created = ""
            if isinstance(aluno.created_at, datetime):
                created = aluno.created_at.isoformat()
            writer.writerow(
                [
                    aluno.id,
                    aluno.nome,
                    aluno.whatsapp,
                    aluno.email or "",
                    aluno.cpf or "",
                    aluno.origem or "",
                    getattr(aluno, "status", "") or "",
                    aluno.email_pagamento or "",
                    aluno.cep or "",
                    aluno.uf or "",
                    aluno.cidade or "",
                    aluno.bairro or "",
                    aluno.logradouro or "",
                    aluno.numero or "",
                    aluno.complemento or "",
                    created,
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    from fastapi.responses import StreamingResponse

    filename = "alunos.csv"
    if search:
        filename = "alunos_filtrados.csv"
    return StreamingResponse(
        iter_rows(alunos),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
def setup_owner_form(request: Request, db: Session = Depends(get_db)):
    try:
        already_configured = db.query(AdminUser.id).first() is not None
    except OperationalError:
        Base.metadata.create_all(bind=engine)
        already_configured = db.query(AdminUser.id).first() is not None

    if already_configured:
        raise HTTPException(status_code=404, detail="Not Found")

    return templates.TemplateResponse(
        "setup_owner.html",
        {
            "request": request,
            "error": None,
            "username": "",
        },
    )


@app.post("/setup", response_class=HTMLResponse, include_in_schema=False)
def setup_owner_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        already_configured = db.query(AdminUser.id).first() is not None
    except OperationalError:
        Base.metadata.create_all(bind=engine)
        already_configured = db.query(AdminUser.id).first() is not None

    if already_configured:
        raise HTTPException(status_code=404, detail="Not Found")

    raw_username = username or ""
    clean_username = raw_username.strip()
    if not clean_username:
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "Informe um usuário.", "username": ""},
            status_code=400,
        )

    if clean_username != raw_username:
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "Remova espaços no início e no fim do usuário.", "username": clean_username},
            status_code=400,
        )

    if len(clean_username) < 3:
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "O usuário deve ter pelo menos 3 caracteres.", "username": clean_username},
            status_code=400,
        )

    if len(password or "") < 8:
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "A senha deve ter pelo menos 8 caracteres.", "username": clean_username},
            status_code=400,
        )

    if len(password or "") > 256:
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "A senha é muito longa. Use até 256 caracteres.", "username": clean_username},
            status_code=400,
        )

    if (confirm_password or "") != (password or ""):
        return templates.TemplateResponse(
            "setup_owner.html",
            {"request": request, "error": "A confirmação de senha não confere.", "username": clean_username},
            status_code=400,
        )

    try:
        password_hash = hash_password(password)
    except ValueError:
        return templates.TemplateResponse(
            "setup_owner.html",
            {
                "request": request,
                "error": "Não foi possível concluir a configuração. Tente novamente.",
                "username": clean_username,
            },
            status_code=500,
        )

    owner = AdminUser(username=clean_username, password_hash=password_hash, role="owner", is_active=True)

    try:
        db.add(owner)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=404, detail="Not Found")
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "setup_owner.html",
            {
                "request": request,
                "error": "Não foi possível concluir a configuração. Tente novamente.",
                "username": clean_username,
            },
            status_code=500,
        )

    return RedirectResponse(url="/admin/login?msg=setup_done", status_code=303)
