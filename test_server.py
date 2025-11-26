#!/usr/bin/env python3
"""
Script simples para testar se o servidor NacionalSign está funcionando
"""

import sys
import os
import requests
import time

def test_server():
    """Testa se o servidor está rodando"""
    try:
        # Tenta conectar no servidor
        response = requests.get("http://127.0.0.1:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Servidor está rodando!")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            return True
        else:
            print(f"❌ Servidor retornou status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Não foi possível conectar ao servidor")
        print("   Verifique se o servidor está rodando na porta 8000")
        return False
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False

def start_server():
    """Inicia o servidor"""
    print("🚀 Iniciando servidor NacionalSign...")
    
    # Muda para o diretório backend
    backend_dir = os.path.join(os.path.dirname(__file__), "backend")
    if not os.path.exists(backend_dir):
        print(f"❌ Diretório backend não encontrado: {backend_dir}")
        return False
    
    os.chdir(backend_dir)
    print(f"📁 Diretório atual: {os.getcwd()}")
    
    # Tenta importar e rodar o app
    try:
        from app.main import app
        import uvicorn
        
        print("✅ App importado com sucesso!")
        print("🌐 Iniciando servidor em http://127.0.0.1:8000")
        
        # Inicia o servidor
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
        
    except ImportError as e:
        print(f"❌ Erro ao importar app: {e}")
        print("   Verifique se todas as dependências estão instaladas")
        return False
    except Exception as e:
        print(f"❌ Erro ao iniciar servidor: {e}")
        return False

if __name__ == "__main__":
    print("🔍 NacionalSign - Teste de Servidor")
    print("=" * 50)
    
    # Primeiro tenta testar se já está rodando
    if test_server():
        print("\n🎉 Servidor já está rodando!")
        print("🌐 Acesse: http://127.0.0.1:8000")
        print("📚 Documentação: http://127.0.0.1:8000/docs")
    else:
        print("\n🚀 Tentando iniciar o servidor...")
        start_server()
