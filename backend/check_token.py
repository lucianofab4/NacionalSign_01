import sys
import hashlib
from sqlalchemy.orm import Session

# Ajusta o sys.path para garantir que o Python encontre o pacote app
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db.session import engine
from app.models.workflow import SignatureRequest

if len(sys.argv) < 2:
    print("Uso: python check_token.py <TOKEN>")
    sys.exit(1)

token = sys.argv[1]
token_hash = hashlib.sha256(token.encode()).hexdigest()

with Session(engine) as session:
    req = session.query(SignatureRequest).filter_by(token_hash=token_hash).first()
    if req:
        print("Token encontrado!")
        print("Expira em:", req.token_expires_at)
        print("ID:", req.id)
        print("Status:", getattr(req, 'status', 'N/A'))
    else:
        print("Token NÃO encontrado no banco de dados.")
