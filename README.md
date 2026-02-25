# Instituto Elo Libras – Sistema de Inscrição

## Descrição
Sistema de inscrição online com:
- Pagamento via Mercado Pago (checkout)
- Cadastro de alunos (FastAPI + Jinja2)
- Painel administrativo com login por sessão (cookie)
- Banco de dados via SQLAlchemy (SQLite local por padrão, compatível com PostgreSQL)
- Splash de carregamento no admin (`/admin`)

Fluxo do aluno (público):
1) Paga no Mercado Pago
2) É redirecionado para `/obrigado`
3) Conclui o cadastro em `/cadastro`
4) Após salvar, recebe o contato final via WhatsApp

## Tecnologias
- FastAPI
- Jinja2
- SQLAlchemy
- PostgreSQL (opcional) / SQLite (dev)
- Uvicorn

## Estrutura do projeto
```
root/
  app/
    main.py
    models.py
    db.py
    templates/
    static/
  requirements.txt
  README.md
  .gitignore
  .env.example
```

## Instalação local (Windows)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Importante:
- Os arquivos em `app/templates/*.html` são templates Jinja2 (ex.: `{% extends %}`, `{{ ... }}`).
- Para ver o layout renderizado, acesse pelas rotas do FastAPI em `http://127.0.0.1:8000`.

## Configuração (.env / variáveis de ambiente)
Este projeto lê configurações via variáveis de ambiente (não há credenciais hardcoded).

Crie um arquivo `.env` baseado em `.env.example` (sem commitar) e configure as variáveis conforme necessário.

Variáveis:
- `DATABASE_URL` = conexão do banco (SQLite por padrão; PostgreSQL opcional)
- `CHECKOUT_URL` = link do checkout (Mercado Pago)
- `ADMIN_USER` = usuário do painel admin
- `ADMIN_PASS` = senha do painel admin
- `ADMIN_SECRET_KEY` = chave para assinar o cookie de sessão do admin (obrigatória em produção; recomendada em dev)

Exemplo (PowerShell):
```powershell
$env:CHECKOUT_URL="https://mpago.li/SEU-LINK"
$env:DATABASE_URL="sqlite:///./local.db"
$env:ADMIN_USER="admin"
$env:ADMIN_PASS="senha-forte"
$env:ADMIN_SECRET_KEY="uma-chave-grande"
uvicorn app.main:app --reload
```

Observação: se você preferir usar `.env` automaticamente, pode usar uma ferramenta/launcher que exporte essas variáveis antes de executar o Uvicorn.

## Rotas principais
Aluno (público):
- `/` (home)
- `/obrigado`
- `/cadastro` (GET/POST)
- `/sucesso`

Admin (restrito):
- `/admin` (splash/loading)
- `/admin/login` (login)
- `/admin/alunos` (painel)
- `/admin/alunos/{id}` (editar aluno)
- `/admin/alunos.csv` (exportação CSV)

## Deploy (Render)
Start command recomendado:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

Configurar as env vars no provedor:
- `DATABASE_URL` (PostgreSQL)
- `CHECKOUT_URL`
- `ADMIN_USER`
- `ADMIN_PASS`
- `ADMIN_SECRET_KEY`

## Segurança
- Credenciais do admin vêm de `ADMIN_USER` e `ADMIN_PASS` (ENV).
- Sessão do admin é assinada com `ADMIN_SECRET_KEY` (ENV).
- `.env`, bancos locais (`*.db`, `local.db`) e ambientes virtuais (`.venv/`) ficam fora do Git por `.gitignore`.

