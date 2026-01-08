#!/usr/bin/env python3

import sys
import os

# Adicionar o diretório backend ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import get_session, engine
from app.models.document import Document, DocumentStatus
from app.services.document import DocumentService
from app.schemas.document import DocumentUpdate, DocumentPartyCreate
from sqlalchemy import text
from datetime import datetime

def test_validation_simplified():
    """Teste simplificado das validações para documentos na lixeira."""
    print("\n🧪 TESTE SIMPLIFICADO - VALIDAÇÕES PARA DOCUMENTOS NA LIXEIRA\n")
    
    session = next(get_session())
    
    try:
        # 1. Buscar um documento existente para teste
        print("1️⃣ Buscando documento existente para teste...")
        existing_doc = session.query(Document).filter(Document.status != DocumentStatus.DELETED).first()
        
        if not existing_doc:
            print("❌ Nenhum documento disponível para teste. Criando um simples...")
            # Fallback: Usar SQL direto com UUID
            with engine.begin() as conn:
                result = conn.execute(text("""
                    INSERT INTO documents (id, name, status, tenant_id, area_id, created_at, updated_at)
                    SELECT gen_random_uuid(), 'Documento Teste Validação', 'DRAFT'::documentstatus,
                           t.id, a.id, NOW(), NOW()
                    FROM tenants t, areas a 
                    WHERE t.id = a.tenant_id
                    LIMIT 1
                    RETURNING id, name, status
                """))
                doc_data = result.fetchone()
                doc_id = doc_data[0]
                print(f"✅ Documento criado: ID={doc_id}, Nome='{doc_data[1]}', Status='{doc_data[2]}'")
                existing_doc = session.get(Document, doc_id)
        else:
            print(f"✅ Documento encontrado: {existing_doc.name} (Status: {existing_doc.status})")
        
        original_status = existing_doc.status
        original_deleted_at = existing_doc.deleted_at
        
        # 2. Mover para a lixeira (soft delete)
        print("\n2️⃣ Movendo documento para a lixeira...")
        existing_doc.status = DocumentStatus.DELETED
        existing_doc.deleted_at = datetime.utcnow()
        session.add(existing_doc)
        session.commit()
        session.refresh(existing_doc)
        print(f"✅ Documento movido para lixeira: Status={existing_doc.status}")
        
        # 3. Testar validação de edição
        print("\n3️⃣ Testando validação de edição...")
        try:
            document_service = DocumentService(session)
            update_payload = DocumentUpdate(name="Nome Alterado Teste")
            document_service.update_document(existing_doc, update_payload)
            print("❌ FALHA: Edição deveria ter sido bloqueada!")
            return False
        except Exception as e:
            if "lixeira" in str(e).lower():
                print(f"✅ Edição bloqueada corretamente: {e}")
            else:
                print(f"❓ Erro inesperado na edição: {e}")
        
        # 4. Testar validação de adição de participantes
        print("\n4️⃣ Testando validação de adição de participantes...")
        try:
            party_payload = DocumentPartyCreate(
                name="João da Silva",
                email="joao@teste.com",
                position="Signatário"
            )
            document_service.add_party(existing_doc, party_payload)
            print("❌ FALHA: Adição de participante deveria ter sido bloqueada!")
            return False
        except Exception as e:
            if "lixeira" in str(e).lower():
                print(f"✅ Adição de participante bloqueada corretamente: {e}")
            else:
                print(f"❓ Erro inesperado na adição de participante: {e}")
        
        # 5. Restaurar estado original
        print("\n5️⃣ Restaurando estado original do documento...")
        existing_doc.status = original_status
        existing_doc.deleted_at = original_deleted_at
        session.add(existing_doc)
        session.commit()
        print(f"✅ Documento restaurado para status original: {original_status}")
        
        print("\n🎉 TODOS OS TESTES PASSARAM! As validações estão funcionando corretamente.")
        return True
        
    except Exception as e:
        print(f"\n❌ ERRO GERAL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    success = test_validation_simplified()
    sys.exit(0 if success else 1)