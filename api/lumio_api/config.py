"""Configuração da API, toda vinda de variáveis de ambiente (nada de segredo no código)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"variável de ambiente {name} não definida (veja .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str                 # papel lumio_app (sujeito a RLS)
    jwt_secret: str
    secret_key: str                   # chave Fernet para a community SNMP
    service_token: str                # usado pelo coletor em /api/internal
    db_role: str | None = None        # só nos testes: SET ROLE ao conectar
    redis_url: str | None = None      # tempo real (/api/events); sem ele, o painel cai no polling
    token_ttl_minutes: int = 12 * 60
    snmp_timeout: float = 2.0
    snmp_retries: int = 1
    gemini_api_key: str | None = None  # assistente de IA; sem ela, o assistente fica desligado
    # modelos em ordem de preferência: se um estiver sobrecarregado, tenta o próximo
    ai_models: tuple[str, ...] = ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest")

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("LUMIO_JWT_SECRET precisa ter pelo menos 32 caracteres")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_required("DATABASE_URL"),
            jwt_secret=_required("LUMIO_JWT_SECRET"),
            secret_key=_required("LUMIO_SECRET_KEY"),
            service_token=_required("LUMIO_SERVICE_TOKEN"),
            db_role=os.environ.get("LUMIO_DB_ROLE") or None,
            redis_url=os.environ.get("REDIS_URL") or None,
            token_ttl_minutes=int(os.environ.get("LUMIO_TOKEN_TTL_MINUTES", 12 * 60)),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            **({"ai_models": tuple(m.strip() for m in os.environ["LUMIO_AI_MODELS"].split(",") if m.strip())}
               if os.environ.get("LUMIO_AI_MODELS") else {}),
        )
