# create_admin.py
# Uso: python create_admin.py yourpassword
# Exemplo: python create_admin.py "MinhaSenhaForte123!"
# Deve ser executado com o .venv ativo e com DATABASE_URL definido no ambiente.

import sys
import os
import uuid
from datetime import datetime

try:
    from passlib.context import CryptContext
except Exception:
    raise SystemExit("passlib não encontrado. Ative o .venv e instale dependências (pip install passlib).")

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("VARIÁVEL DATABASE_URL não definida. Use:  = 'postgresql+psycopg2://...'")

if len(sys.argv) < 2:
    raise SystemExit("Uso: python create_admin.py <senha_do_admin>")

plain_password = sys.argv[1]
email = "luciano.dias888@gmail.com"

tried = []
project_create_ok = False
for candidate in ("app", "nacionalsign", "src"):
    try:
        mod = __import__(candidate)
        for fn in ("create_user", "create_superuser", "users_create"):
            if hasattr(mod, fn):
                print(f"Usando função {candidate}.{fn}()")
                getattr(mod, fn)(email=email, password=plain_password, is_superuser=True)
                project_create_ok = True
                break
        if project_create_ok:
            break
    except Exception:
        tried.append(candidate)
        continue

if project_create_ok:
    print("Usuário criado via função do projeto. Verifique no banco.")
    sys.exit(0)

try:
    from sqlalchemy import create_engine, MetaData, insert
    from sqlalchemy.exc import SQLAlchemyError
except Exception:
    raise SystemExit("SQLAlchemy não está instalado. Use: pip install sqlalchemy psycopg2-binary")

engine = create_engine(DATABASE_URL)
meta = MetaData()
meta.reflect(bind=engine, only=["users"])

if "users" not in meta.tables:
    raise SystemExit("Tabela 'users' não encontrada. Verifique DATABASE_URL e migrações.")

users_table = meta.tables["users"]
uid = str(uuid.uuid4())
now = datetime.utcnow()
password_hash = pwd_ctx.hash(plain_password)

row = {}
col_names = {c.name for c in users_table.columns}

if "id" in col_names:
    row["id"] = uid
if "email" in col_names:
    row["email"] = email
if "password_hash" in col_names:
    row["password_hash"] = password_hash
elif "password" in col_names:
    row["password"] = password_hash

for admin_field in ("is_admin", "is_superuser", "is_staff", "admin"):
    if admin_field in col_names:
        row[admin_field] = True

if "created_at" in col_names:
    row["created_at"] = now
if "updated_at" in col_names:
    row["updated_at"] = now
if "name" in col_names and "name" not in row:
    row["name"] = "Luciano Dias"
if "full_name" in col_names and "full_name" not in row:
    row["full_name"] = "Luciano Dias"

print("Colunas detectadas na tabela users:", sorted(col_names))
print("Valores que serão inseridos:", row)

confirm = input("Deseja prosseguir e inserir esse usuário no banco? [y/N]: ").strip().lower()
if confirm != "y":
    print("Operação cancelada.")
    sys.exit(0)

try:
    with engine.begin() as conn:
        stmt = insert(users_table).values(**row)
        conn.execute(stmt)
    print(f"Usuário {email} criado com sucesso (id={uid}).")
except SQLAlchemyError as e:
    print("Erro ao inserir usuário:", str(e))
    raise
