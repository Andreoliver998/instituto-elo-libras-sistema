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
# Opcional: crie um .env local (não commitar)
copy .env.example .env
uvicorn app.main:app --reload
```

Importante:
- Os arquivos em `app/templates/*.html` são templates Jinja2 (ex.: `{% extends %}`, `{{ ... }}`).
- Para ver o layout renderizado, acesse pelas rotas do FastAPI em `http://127.0.0.1:8000`.

## Configuração (.env / variáveis de ambiente)
Este projeto lê configurações via variáveis de ambiente (não commite links/credenciais reais).

Crie um arquivo `.env` baseado em `.env.example` (sem commitar) e configure as variáveis conforme necessário.

Variáveis:
- `DATABASE_URL` = conexão do banco (SQLite por padrão; PostgreSQL opcional)
- `CHECKOUT_URL` = link do checkout (Mercado Pago) — em dev você pode usar `/obrigado` para simular o fluxo
- `ADMIN_USER` = usuário do painel admin
- `ADMIN_PASS` = senha do painel admin
- `ADMIN_SECRET_KEY` = chave para assinar o cookie de sessão do admin (obrigatória em produção; recomendada em dev)
- `WHATSAPP_GROUP_URL` = link de contato/grupo do WhatsApp exibido na tela de sucesso (opcional)

Exemplo (PowerShell):
```powershell
$env:CHECKOUT_URL="/obrigado"
$env:DATABASE_URL="sqlite:///./local.db"
$env:ADMIN_USER="admin"
$env:ADMIN_PASS="senha-forte"
$env:ADMIN_SECRET_KEY="uma-chave-grande"
$env:WHATSAPP_GROUP_URL="https://wa.me/55SEU_NUMERO?text=Olá%2C%20acabei%20de%20concluir%20meu%20cadastro."
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
### Passo a passo
1) Crie um **PostgreSQL** no Render.
2) Crie um **Web Service** e conecte ao repositório do GitHub.
3) **Build command**:
   - `pip install -r requirements.txt`
4) **Start command** (recomendado, porta dinâmica do Render):
   - `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Alternativa fixa (se preferir): `uvicorn app.main:app --host 0.0.0.0 --port 10000`
5) Configure as **Environment Variables** no Render:
   - `DATABASE_URL` (PostgreSQL do Render)
   - `CHECKOUT_URL` (checkout do Mercado Pago)
   - `ADMIN_USER`
   - `ADMIN_PASS`
   - `ADMIN_SECRET_KEY`
   - `WHATSAPP_GROUP_URL` (opcional)
6) No Mercado Pago, configure a **URL de sucesso** para:
   - `https://SEUAPP.onrender.com/obrigado`

### Checklist final (antes de publicar)
- `uvicorn app.main:app --reload`
- GET `/` (home)
- GET `/obrigado`
- GET `/cadastro` (form)
- POST `/cadastro` (salva e mostra sucesso)
- GET `/admin` (splash)
- GET `/admin/login`
- Login OK → splash → GET `/admin/alunos`

## Segurança
- Credenciais do admin vêm de `ADMIN_USER` e `ADMIN_PASS` (ENV).
- Sessão do admin é assinada com `ADMIN_SECRET_KEY` (ENV).
- `.env`, bancos locais (`*.db`, `local.db`) e ambientes virtuais (`.venv/`) ficam fora do Git por `.gitignore`.
