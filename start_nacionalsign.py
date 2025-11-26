#!/usr/bin/env python3
"""
Utilitário para iniciar o NacionalSign (backend e frontend) a partir de um único comando.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
BACKEND_VENV = BACKEND_DIR / ".venv"


def _file_exists(path: Path) -> bool:
    if not path.exists():
        print(f"[x] Caminho não encontrado: {path}")
        return False
    return True


def run_command(cmd: list[str], cwd: Path, env: Optional[dict[str, str]] = None) -> None:
    print(f"[>] Executando: {' '.join(cmd)} (cwd={cwd})")
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def _venv_python() -> Path:
    if os.name == "nt":
        return BACKEND_VENV / "Scripts" / "python.exe"
    return BACKEND_VENV / "bin" / "python"


def ensure_backend_venv() -> None:
    if not _file_exists(BACKEND_DIR):
        return

    if not BACKEND_VENV.exists():
        print("[i] Criando ambiente virtual do backend (.venv)…")
        run_command([sys.executable, "-m", "venv", str(BACKEND_VENV)], cwd=BACKEND_DIR)


def ensure_backend_dependencies() -> None:
    ensure_backend_venv()
    requirements = BACKEND_DIR / "requirements.txt"
    if not requirements.exists():
        print("[!] Arquivo requirements.txt não encontrado – pulando verificação do backend.")
        return

    print("[i] Verificando dependências do backend…")
    run_command([str(_venv_python()), "-m", "pip", "install", "-r", str(requirements)], cwd=BACKEND_DIR)


def ensure_frontend_dependencies() -> None:
    if not _file_exists(FRONTEND_DIR):
        return

    node_modules = FRONTEND_DIR / "node_modules"
    if node_modules.exists():
        return

    print("[i] Instalando dependências do frontend…")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise RuntimeError("npm não encontrado. Instale Node.js/NPM antes de continuar.")
    run_command([npm, "install"], cwd=FRONTEND_DIR)


def start_backend() -> subprocess.Popen[bytes]:
    if not _file_exists(BACKEND_DIR):
        raise FileNotFoundError("Diretório backend não encontrado.")

    ensure_backend_dependencies()

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(BACKEND_DIR))

    cmd = [
        str(_venv_python()),
        "-m",
        "uvicorn",
        "app.main:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    print("[i] Iniciando backend (FastAPI em http://127.0.0.1:8000)…")
    return subprocess.Popen(cmd, cwd=str(BACKEND_DIR), env=env)


def start_frontend() -> subprocess.Popen[bytes]:
    if not _file_exists(FRONTEND_DIR):
        raise FileNotFoundError("Diretório frontend não encontrado.")

    ensure_frontend_dependencies()

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise RuntimeError("npm não encontrado. Instale Node.js/NPM antes de continuar.")

    print("[i] Iniciando frontend (Vite em http://localhost:5173)…")
    cmd = [npm, "run", "dev", "--", "--host"]
    return subprocess.Popen(cmd, cwd=str(FRONTEND_DIR))


def start_both() -> None:
    backend_proc: Optional[subprocess.Popen[bytes]] = None
    frontend_proc: Optional[subprocess.Popen[bytes]] = None

    try:
        backend_proc = start_backend()
        time.sleep(2)

        webbrowser.open("http://localhost:5173", new=2)
        frontend_proc = start_frontend()

        print("\n[i] Backend em http://127.0.0.1:8000")
        print("[i] Frontend em http://localhost:5173")
        print("[i] Pressione Ctrl+C para encerrar ambos.")

        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                raise RuntimeError("Backend finalizado inesperadamente.")
            if frontend_proc.poll() is not None:
                raise RuntimeError("Frontend finalizado inesperadamente.")

    except KeyboardInterrupt:
        print("\n[i] Encerrando serviços…")
    finally:
        for proc in (frontend_proc, backend_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def show_menu() -> str:
    print("==============================================")
    print("NacionalSign - Starter")
    print("==============================================")
    print("1. Iniciar apenas Backend (API)")
    print("2. Iniciar apenas Frontend (Vite)")
    print("3. Iniciar Backend + Frontend (recomendado)")
    print("4. Verificar dependências")
    print("5. Sair")
    return input(">> Escolha uma opção (1-5): ").strip()


def main() -> None:
    while True:
        choice = show_menu()
        if choice == "1":
            print()
            try:
                start_backend().wait()
            except KeyboardInterrupt:
                print("\n[i] Backend interrompido.")
        elif choice == "2":
            print()
            try:
                start_frontend().wait()
            except KeyboardInterrupt:
                print("\n[i] Frontend interrompido.")
        elif choice == "3":
            print()
            start_both()
        elif choice == "4":
            ensure_backend_dependencies()
            ensure_frontend_dependencies()
        elif choice == "5":
            print("Até logo!")
            return
        else:
            print("Opção inválida.\n")


if __name__ == "__main__":
    main()
