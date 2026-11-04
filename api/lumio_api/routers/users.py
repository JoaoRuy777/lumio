"""Usuários do provedor: o administrador cria, lista e remove.

Tudo roda com o tenant do token (RLS): um provedor não vê nem mexe nos
usuários de outro. O e-mail é único na Lumio inteira (é ele que faz o login).
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Response, status

from ..deps import Admin, TenantDb, User
from ..schemas import UserIn, UserList, UserOut
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["usuários"])

COLUMNS = "id, name, email, role, created_at"


@router.get("", response_model=UserList, summary="Usuários do provedor")
async def list_users(user: User, db: TenantDb) -> UserList:
    rows = await db.fetch(f"SELECT {COLUMNS} FROM users ORDER BY created_at")
    return UserList(items=[UserOut(**r) for r in rows])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             summary="Cria um usuário no provedor (administrador: tudo; operador: vê tudo, não altera cadastros)")
async def create_user(body: UserIn, user: Admin, db: TenantDb) -> UserOut:
    try:
        async with db.transaction():            # savepoint: o erro não derruba a transação da requisição
            row = await db.fetchrow(
                f"INSERT INTO users (tenant_id, email, name, password_hash, role) "
                f"VALUES ($1, $2, $3, $4, $5) RETURNING {COLUMNS}",
                user.tenant_id, body.email, body.name.strip(), hash_password(body.password), body.role)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já cadastrado")
    return UserOut(**row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um usuário do provedor")
async def delete_user(user_id: UUID, user: Admin, db: TenantDb) -> Response:
    if user_id == user.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "você não pode remover o próprio usuário")
    if await db.execute("DELETE FROM users WHERE id = $1", user_id) == "DELETE 0":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "usuário não encontrado")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
