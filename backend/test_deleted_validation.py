#!/usr/bin/env python3

import sys
import os

# Adicionar o diretório backend ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine
from app.models.document import DocumentStatus
from sqlalchemy import text

def test_deleted_enum():
    """Testa se o enum DELETED está disponível no PostgreSQL."""
    print("Testando enum DELETED no PostgreSQL...")
    
    try:
        with engine.begin() as conn:
            # Testar se o valor DELETED existe no enum
            result = conn.execute(text("SELECT 'DELETED'::documentstatus"))
            value = result.fetchone()[0]
            print(f"✅ Status DELETED disponível: {value}")
            
            # Listar todos os valores do enum
            result = conn.execute(text("""
                SELECT unnest(enum_range(NULL::documentstatus)) as status_value
            """))
            statuses = [row[0] for row in result.fetchall()]
            print(f"✅ Todos os status disponíveis: {statuses}")
            
            return True
    except Exception as e:
        print(f"❌ Erro ao testar enum DELETED: {e}")
        return False

if __name__ == "__main__":
    test_deleted_enum()