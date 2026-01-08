#!/usr/bin/env python3

import sys
import os

# Adicionar o diretório backend ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine
from sqlalchemy import text

def add_archived_enum():
    """Adiciona o valor ARCHIVED ao enum documentstatus no PostgreSQL."""
    print("🔧 ADICIONANDO VALOR ARCHIVED AO ENUM DO POSTGRESQL\n")
    
    try:
        with engine.begin() as conn:
            # Primeiro vamos ver os valores atuais
            print("1️⃣ Verificando valores atuais do enum...")
            result = conn.execute(text("SELECT unnest(enum_range(NULL::documentstatus)) as status_value"))
            current_values = [row[0] for row in result.fetchall()]
            print(f"✅ Valores atuais do enum: {current_values}")
            
            if 'ARCHIVED' not in current_values:
                print("\n2️⃣ Adicionando valor ARCHIVED ao enum...")
                conn.execute(text("ALTER TYPE documentstatus ADD VALUE 'ARCHIVED'"))
                print("✅ Valor ARCHIVED adicionado com sucesso!")
            else:
                print("ℹ️  Valor ARCHIVED já existe no enum")
                
            # Verificar novamente
            print("\n3️⃣ Verificando valores finais...")
            result = conn.execute(text("SELECT unnest(enum_range(NULL::documentstatus)) as status_value"))
            updated_values = [row[0] for row in result.fetchall()]
            print(f"✅ Valores atualizados do enum: {updated_values}")
            
            if 'ARCHIVED' in updated_values:
                print("\n🎉 Sucesso! O valor ARCHIVED foi adicionado ao enum.")
                return True
            else:
                print("\n❌ Falha: O valor ARCHIVED não foi adicionado.")
                return False
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = add_archived_enum()
    sys.exit(0 if success else 1)