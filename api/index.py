"""Entrada da API na Vercel (serviço "api" do vercel.json).

Fora da Vercel nada usa este arquivo: o Docker roda `uvicorn lumio_api.main:app`.
A API usa os drivers SNMP do coletor (Testar conexão e descoberta), então os
dois pacotes entram no caminho de import, como no Dockerfile da API.
"""

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
for _p in (_repo / "collector", _repo / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lumio_api.main import app  # noqa: E402

__all__ = ["app"]
