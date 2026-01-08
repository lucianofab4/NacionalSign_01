#!/usr/bin/env python3
"""
Script de limpeza automática de documentos deletados.
Remove permanentemente documentos que estão na lixeira há mais de 30 dias.

Uso:
  python cleanup_deleted_documents.py [--days 30] [--dry-run]

Configurar como cron job (exemplo para rodar diariamente às 2h):
  0 2 * * * cd /path/to/backend && python cleanup_deleted_documents.py >> cleanup.log 2>&1
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

# Adicionar o diretório backend ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine
from sqlmodel import Session
from app.services.document import DocumentService


def main():
    parser = argparse.ArgumentParser(description='Limpar documentos deletados permanentemente')
    parser.add_argument('--days', type=int, default=30, help='Dias para manter na lixeira (default: 30)')
    parser.add_argument('--dry-run', action='store_true', help='Apenas mostrar o que seria excluído sem excluir')
    parser.add_argument('--verbose', '-v', action='store_true', help='Logs detalhados')
    
    args = parser.parse_args()
    
    # Configurar logging se verbose
    if args.verbose:
        import logging
        logging.basicConfig(level=logging.INFO)
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    try:
        print("-" * 60)
        print(f"🧹 Iniciando limpeza de documentos deletados...")
        print(f"📅 Data limite: {args.days} dias atrás")
        print(f"🔧 Modo: {'Dry-run (teste)' if args.dry_run else 'Execução real'}")
        print("-" * 60)
        
        with Session(engine) as session:
            document_service = DocumentService(session)
            
            if args.dry_run:
                # Modo dry-run: apenas contar
                from app.models.document import Document, DocumentStatus
                from sqlmodel import select
                
                cutoff_date = datetime.utcnow() - timedelta(days=args.days)
                expired_documents = session.exec(
                    select(Document)
                    .where(Document.status == DocumentStatus.DELETED)
                    .where(Document.deleted_at < cutoff_date)
                ).all()
                
                print(f"📋 Documentos que seriam excluídos: {len(expired_documents)}")
                for doc in expired_documents[:10]:  # Mostrar apenas os primeiros 10
                    print(f"  - {doc.name} (ID: {doc.id}, deletado em: {doc.deleted_at})")
                
                if len(expired_documents) > 10:
                    print(f"  ... e mais {len(expired_documents) - 10} documentos")
                    
            else:
                # Execução real
                deleted_count = document_service.cleanup_deleted_documents(days=args.days)
                print(f"✅ Documentos excluídos permanentemente: {deleted_count}")
                
        print("-" * 60)
        print(f"✨ Limpeza concluída com sucesso!")
        
    except Exception as e:
        print(f"❌ ERRO durante a limpeza: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()