from sqlmodel import Session, select
from app.db.session import engine
from app.models.user import User

with Session(engine) as s:
    users = s.exec(select(User)).all()
    for u in users:
        print(f"ID: {u.id} | Email: {u.email} | Ativo: {u.is_active}")
