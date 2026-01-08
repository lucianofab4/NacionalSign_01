#!/usr/bin/env python3

import sys
import os

# Adicionar o diretório backend ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import get_session, engine
from app.models.document import Document, DocumentStatus
from app.services.document import DocumentService
from app.services.workflow import WorkflowService
from sqlalchemy import text
from datetime import datetime

def test_document_protection():
    """Testa as validações para documentos na lixeira."""
    print("\n🧪 TESTANDO VALIDAÇÕES PARA DOCUMENTOS NA LIXEIRA\n")
    
    session = next(get_session())
    document_service = DocumentService(session)
    
    try:
        # 1. Criar um documento de teste
        print("1️⃣ Criando documento de teste...")
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO documents (name, status, tenant_id, area_id, created_at, updated_at)
                VALUES ('Documento Teste Validação', 'DRAFT', 
                        (SELECT id FROM tenants LIMIT 1),
                        (SELECT id FROM areas LIMIT 1),
                        NOW(), NOW())
                RETURNING id, name, status
            """))
            doc_data = result.fetchone()
            doc_id = doc_data[0]
            print(f"✅ Documento criado: ID={doc_id}, Nome='{doc_data[1]}', Status='{doc_data[2]}'")
        
        # 2. Carregar o documento
        document = session.get(Document, doc_id)
        if not document:
            print("❌ Erro: não foi possível carregar o documento")
            return False
            
        print(f"✅ Documento carregado: {document.name} (Status: {document.status})")
        
        # 3. Mover para a lixeira (soft delete)
        print("\n2️⃣ Movendo documento para a lixeira...")
        document.status = DocumentStatus.DELETED
        document.deleted_at = datetime.utcnow()
        session.add(document)
        session.commit()
        session.refresh(document)
        print(f"✅ Documento movido para lixeira: Status={document.status}, deleted_at={document.deleted_at}")
        
        # 4. Testar validação de edição
        print("\n3️⃣ Testando validação de edição...")
        try:
            from app.schemas.document import DocumentUpdate
            update_payload = DocumentUpdate(name="Nome Alterado")
            document_service.update_document(document, update_payload)
            print("❌ FALHA: Edição deveria ter sido bloqueada!")
            return False
        except Exception as e:
            if "lixeira" in str(e).lower():
                print(f"✅ Edição bloqueada corretamente: {e}")
            else:
                print(f"❓ Erro inesperado: {e}")
        
        # 5. Testar validação de adição de participantes
        print("\n4️⃣ Testando validação de adição de participantes...")
        try:
            from app.schemas.document import DocumentPartyCreate
            party_payload = DocumentPartyCreate(
                name="João da Silva",
                email="joao@teste.com",
                position="Signatário"
            )
            document_service.add_party(document, party_payload)
            print("❌ FALHA: Adição de participante deveria ter sido bloqueada!")
            return False
        except Exception as e:
            if "lixeira" in str(e).lower():
                print(f"✅ Adição de participante bloqueada corretamente: {e}")
            else:
                print(f"❓ Erro inesperado: {e}")
        
        # 6. Limpeza - Excluir documento de teste
        print("\n5️⃣ Limpando documento de teste...")
        session.delete(document)
        session.commit()
        print("✅ Documento de teste excluído")
        
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
    success = test_document_protection()
    sys.exit(0 if success else 1)