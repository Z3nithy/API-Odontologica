from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from jose import JWTError, jwt
from .config import SECRET_KEY, ALGORITHM

TEMPO_EXPIRACAO = 60  # minutos


def criar_token_acesso(usuario_id: int) -> str:
    expiracao = datetime.now(timezone.utc) + timedelta(minutes=TEMPO_EXPIRACAO)

    payload = {
        "sub": str(usuario_id),
        "exp": expiracao
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


def verificar_token_acesso(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        usuario_id = payload.get("sub")

        if usuario_id is None:
            raise HTTPException(status_code=401, detail="Token sem usuário")

        return int(usuario_id)

    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")