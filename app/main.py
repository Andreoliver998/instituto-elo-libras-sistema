import os
import secrets
from datetime import datetime
from typing import Iterable
from urllib.parse import quote, urlencode, urlparse
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .db import Base, engine, get_db
from .models import Student
from .auth import (
    admin_is_configured,
    is_admin_logged_in,
    require_admin,
    safe_next,
    validate_next,
    verify_admin_credentials,
)

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
    full_path = os.path.join("app", "static", *path.split("/"))
    try:
        version = int(os.path.getmtime(full_path))
    except OSError:
        version = 0
    return f"{url}?v={version}"

templates.env.globals["static_url"] = _static_url

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
        "status": "TEXT NOT NULL DEFAULT 'cadastrado'",
    }

    missing = [(name, ddl) for name, ddl in desired.items() if name not in existing]
    if not missing:
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE students ADD COLUMN {name} {ddl}"))

# MVP: cria tabelas automaticamente
Base.metadata.create_all(bind=engine)
_sqlite_ensure_students_columns()

CHECKOUT_URL = (os.getenv("CHECKOUT_URL") or "https://mpago.li/1KF9Yzi").strip()
ADMIN_STATUS_OPTIONS = ["cadastrado", "pago", "pendente", "concluido"]

def _is_valid_http_url(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if value == "https://SEU-LINK-DE-PAGAMENTO":
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None

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
def admin_login_form(request: Request, next: str | None = None):
    next_target = safe_next(next)
    if is_admin_logged_in(request):
        return RedirectResponse(url=next_target, status_code=303)

    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "next": next_target,
            "configured": admin_is_configured(),
            "error": None,
        },
    )


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(None),
):
    next_target = safe_next(next)

    if not admin_is_configured():
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "next": next_target,
                "configured": False,
                "error": "Acesso administrativo indisponível. Contate o suporte.",
            },
            status_code=503,
        )

    if verify_admin_credentials(username, password):
        request.session["admin_auth"] = True
        request.session["admin_user"] = (username or "").strip()
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
            "configured": True,
            "error": "Credenciais inválidas.",
        },
        status_code=401,
    )


@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


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
        {"request": request, "nome": aluno.nome},
    )

@app.get("/sucesso", response_class=HTMLResponse)
def sucesso(request: Request, nome: str | None = None):
    return templates.TemplateResponse(
        "sucesso.html",
        {
            "request": request,
            "nome": (nome or "Aluno").strip() or "Aluno",
        },
    )

@app.get("/admin/alunos", response_class=HTMLResponse)
def admin_alunos(
    request: Request,
    q: str | None = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request)
    if redirect:
        return redirect

    safe_page = max(1, page)
    safe_per_page = min(max(1, per_page), 200)
    query = db.query(Student)

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Student.nome.ilike(like), Student.whatsapp.ilike(like), Student.email.ilike(like)))

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
    redirect = require_admin(request)
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
        },
    )

@app.post("/admin/alunos/{student_id}")
def admin_aluno_editar_submit(
    request: Request,
    student_id: int,
    nome: str = Form(...),
    whatsapp: str = Form(...),
    email: str = Form(None),
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
    redirect = require_admin(request)
    if redirect:
        return redirect

    aluno = db.query(Student).filter(Student.id == student_id).first()
    if not aluno:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")

    aluno.nome = nome.strip()
    aluno.whatsapp = whatsapp.strip()
    aluno.email = _clean_optional_str(email)
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

@app.get("/admin/alunos.csv")
def admin_alunos_csv(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    redirect = require_admin(request)
    if redirect:
        return redirect

    import csv
    import io

    query = db.query(Student)
    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Student.nome.ilike(like), Student.whatsapp.ilike(like), Student.email.ilike(like)))

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
