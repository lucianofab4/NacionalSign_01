from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações globais do NacionalSign.
    Lê automaticamente variáveis do arquivo .env.
    """

    # Configuração base
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Projeto
    project_name: str = "NacionalSign API"
    api_v1_str: str = "/api/v1"
    debug: bool = False

    # Segurança / JWT
    secret_key: str = "changeme"
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int = 10080
    algorithm: str = "HS256"

    # Banco de dados
    database_url: str = "sqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

    # Armazenamento S3 / MinIO
    s3_endpoint_url: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_bucket_documents: str = "nacionalsign-documents"

    # CORS
    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Autenticação 2FA
    two_factor_issuer: str = "NacionalSign"

    # E-mail (SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = "documentoseltronico@gmail.com"
    smtp_password: Optional[str] = "muop viro wjyf pwqo"
    smtp_sender: Optional[str] = "Documentos Eletrônicos <documentoseltronico@gmail.com>"
    smtp_starttls: bool = True

    # URLs públicas (links enviados por e-mail)
    public_base_url: str = "http://localhost:8000"
    public_app_url: str = "http://localhost:5173"

    # Integração com Twilio (opcional)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None
    twilio_messaging_service_sid: Optional[str] = None

    # ICP-Brasil / Certificados Digitais
    icp_timestamp_url: Optional[str] = None
    icp_timestamp_api_key: Optional[str] = None
    icp_timestamp_username: Optional[str] = None
    icp_timestamp_password: Optional[str] = None
    icp_certificate_path: Optional[str] = None
    icp_certificate_password: Optional[str] = None
    icp_signature_reason: str = "Documento assinado com NacionalSign"
    icp_signature_location: Optional[str] = "Brasil"

    # Faturamento / Pagamentos
    billing_default_gateway: str = "pagseguro"
    billing_trial_days: int = 0
    pagseguro_token: Optional[str] = None
    pagseguro_app_id: Optional[str] = None
    stripe_api_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None
    billing_use_wallet: bool = False
    billing_max_retries: int = 3

    # Agente de assinatura local (certificados digitais)
    signing_agent_base_url: str = "http://127.0.0.1:9250"
    signing_agent_timeout_seconds: float = 15.0
    signing_agent_download_url: Optional[str] = None

    # Tokens públicos (links de assinatura)
    public_token_ttl_hours: int = 24
    public_token_grace_hours: int = 720  # tempo extra após expiração (para validação manual)

    # Frontend integrado
    serve_frontend: bool = True
    frontend_dir: str = "../frontend/dist"
    auto_build_frontend: bool = True

    # Armazenamento local
    nacionalsign_storage: str = "_storage"
    customer_admin_emails: List[str] = ["luciano.dias888@gmail.com"]

    def resolved_public_app_url(self) -> str:
        """Resolve a URL pública base (usada nos e-mails e nos links de assinatura)."""
        base = (self.public_app_url or "").strip()
        if base:
            return base.rstrip("/")
        fallback = (self.public_base_url or "").rstrip("/")
        if fallback and self.serve_frontend:
            return f"{fallback}/app"
        return fallback


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância de configurações globais (cacheada)."""
    return Settings()


settings = get_settings()
