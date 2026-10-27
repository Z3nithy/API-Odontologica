from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.jwt import criar_token_acesso
from core.senha_hash import criar_hash_senha, verificar_senha
from database import get_db
from dependencies.autenticacao import get_usuario_atual
from models import User, UserPreference
from schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    UserPreferencesPayload,
    UserPreferencesResponse,
    UserProfileUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])

RECEPTION_HOME_PAGES = {
    "reception-dashboard",
    "reception-agenda",
    "reception-patients",
    "reception-checkin",
    "reception-confirmations",
    "reception-history",
    "reception-notification-settings",
    "reception-general-settings",
}


def _default_preferences(user: User) -> UserPreferencesPayload:
    home_page = {
        "manager": "manager-dashboard",
        "dentist": "dentist-dashboard",
        "receptionist": "reception-dashboard",
    }.get(user.role, "reception-dashboard")
    return UserPreferencesPayload(homePage=home_page)


def _validate_home_page(preferences: UserPreferencesPayload, user: User) -> None:
    allowed = {
        "manager": {"manager-dashboard"},
        "dentist": {"dentist-dashboard"},
        "receptionist": RECEPTION_HOME_PAGES,
    }.get(user.role, set())
    if preferences.homePage not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A página inicial selecionada não está disponível para este perfil.",
        )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == str(payload.email).lower()).first()
    if not user or not user.active or not verificar_senha(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha inválidos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return LoginResponse(
        access_token=criar_token_acesso(user.id),
        user=AuthenticatedUser.model_validate(user),
    )


@router.get("/me", response_model=AuthenticatedUser)
def get_profile(user: User = Depends(get_usuario_atual)) -> User:
    return user


@router.get("/me/preferences", response_model=UserPreferencesResponse)
def get_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_usuario_atual),
) -> UserPreferencesResponse:
    stored = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if stored is None:
        return UserPreferencesResponse(
            preferences=_default_preferences(user),
            customized=False,
        )
    preferences = UserPreferencesPayload.model_validate(stored.settings)
    _validate_home_page(preferences, user)
    return UserPreferencesResponse(preferences=preferences, customized=True)


@router.put("/me/preferences", response_model=UserPreferencesResponse)
def save_preferences(
    payload: UserPreferencesPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_usuario_atual),
) -> UserPreferencesResponse:
    _validate_home_page(payload, user)
    stored = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if stored is None:
        stored = UserPreference(user_id=user.id, settings=payload.model_dump(mode="json"))
        db.add(stored)
    else:
        stored.settings = payload.model_dump(mode="json")
    try:
        db.commit()
        db.refresh(stored)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível salvar as preferências da conta.",
        ) from error
    return UserPreferencesResponse(preferences=payload, customized=True)


@router.delete("/me/preferences", response_model=UserPreferencesResponse)
def reset_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_usuario_atual),
) -> UserPreferencesResponse:
    stored = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if stored is not None:
        db.delete(stored)
        db.commit()
    return UserPreferencesResponse(preferences=_default_preferences(user), customized=False)


@router.patch("/me", response_model=AuthenticatedUser)
def update_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_usuario_atual),
) -> User:
    user.name = payload.name
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível atualizar os dados da conta.",
        ) from error
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_usuario_atual),
) -> None:
    if not verificar_senha(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A senha atual não confere.",
        )
    if verificar_senha(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escolha uma senha diferente da atual.",
        )

    user.password_hash = criar_hash_senha(payload.new_password)
    db.commit()
