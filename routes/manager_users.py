import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.senha_hash import criar_hash_senha
from database import get_db
from dependencies.autenticacao import require_roles
from models import Appointment, User, UserInvitation, UserManagementAudit
from schemas.manager_users import (
    AcceptUserInvitation,
    ManagedUserCreate,
    ManagedUserDetails,
    ManagedUserItem,
    ManagedUserList,
    ManagedUserMetrics,
    ManagedUserUpdate,
    UserInvitationCreated,
    UserManagementAuditItem,
)

router = APIRouter(prefix="/api/manager/users", tags=["Gestão de equipe"])
INVITATION_TTL = timedelta(hours=48)
MANAGED_ROLES = ("dentist", "receptionist")
VISIBLE_ROLES = ("manager", *MANAGED_ROLES)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def latest_invitation_status(now: datetime):
    pending = (
        select(UserInvitation.id)
        .where(
            UserInvitation.user_id == User.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .exists()
    )
    expired = (
        select(UserInvitation.id)
        .where(
            UserInvitation.user_id == User.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at <= now,
        )
        .exists()
    )
    status_expression = case(
        (User.active.is_(True), "active"),
        (pending, "pending"),
        (expired, "expired"),
        else_="inactive",
    )
    expiry = (
        select(UserInvitation.expires_at)
        .where(
            UserInvitation.user_id == User.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
        )
        .order_by(UserInvitation.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    return status_expression, expiry


def user_item(user: User, user_status: str, invitation_expiry=None) -> ManagedUserItem:
    return ManagedUserItem(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        active=user.active,
        status=user_status,
        created_at=user.created_at,
        invitation_expires_at=invitation_expiry,
    )


def write_audit(
    db: Session,
    clinic_id: int,
    actor_id: int,
    target_id: int,
    action: str,
    summary: str,
) -> None:
    db.add(
        UserManagementAudit(
            clinic_id=clinic_id,
            actor_user_id=actor_id,
            target_user_id=target_id,
            action=action,
            summary=summary,
        )
    )


@router.get("", response_model=ManagedUserList)
def list_managed_users(
    q: str | None = Query(default=None, max_length=160),
    role: str | None = Query(default=None, pattern="^(manager|dentist|receptionist)$"),
    account_status: str | None = Query(
        default=None, alias="status", pattern="^(active|inactive|pending|expired)$"
    ),
    sort_by: str = Query(
        default="created_at", pattern="^(name|role|created_at|status)$"
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedUserList:
    now = datetime.now(timezone.utc)
    status_expression, expiry_expression = latest_invitation_status(now)
    query = db.query(User, status_expression, expiry_expression).filter(
        User.clinic_id == manager.clinic_id,
        User.role.in_(VISIBLE_ROLES),
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        search_filter = func.lower(User.name).like(term.lower()) | func.lower(
            User.email
        ).like(term.lower())
        if q.strip().isdigit():
            search_filter = search_filter | (User.id == int(q.strip()))
        query = query.filter(search_filter)
    if role:
        query = query.filter(User.role == role)
    if account_status:
        query = query.filter(status_expression == account_status)

    total = query.count()
    sort_column = {
        "name": User.name,
        "role": User.role,
        "created_at": User.created_at,
        "status": status_expression,
    }[sort_by]
    sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    rows = query.order_by(sort_column, User.id.asc()).offset(offset).limit(limit).all()

    metrics_query = db.query(User, status_expression).filter(
        User.clinic_id == manager.clinic_id,
        User.role.in_(VISIBLE_ROLES),
    )
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        search_filter = func.lower(User.name).like(term) | func.lower(User.email).like(term)
        if q.strip().isdigit():
            search_filter = search_filter | (User.id == int(q.strip()))
        metrics_query = metrics_query.filter(search_filter)
    if role:
        metrics_query = metrics_query.filter(User.role == role)
    if account_status:
        metrics_query = metrics_query.filter(status_expression == account_status)
    metric_rows = metrics_query.all()
    statuses = [row[1] for row in metric_rows]
    metrics = ManagedUserMetrics(
        total=len(metric_rows),
        active=statuses.count("active"),
        inactive=statuses.count("inactive") + statuses.count("expired"),
        dentists=sum(user.role == "dentist" for user, _ in metric_rows),
        receptionists=sum(user.role == "receptionist" for user, _ in metric_rows),
        pending_invitations=statuses.count("pending"),
    )
    return ManagedUserList(
        items=[user_item(user, user_status, expiry) for user, user_status, expiry in rows],
        total=total,
        offset=offset,
        limit=limit,
        metrics=metrics,
    )


@router.get("/{user_id}", response_model=ManagedUserDetails)
def get_managed_user(
    user_id: int,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedUserDetails:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.clinic_id == manager.clinic_id,
            User.role.in_(VISIBLE_ROLES),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta clínica.")
    now = datetime.now(timezone.utc)
    status_expression, expiry_expression = latest_invitation_status(now)
    user_status, expiry = (
        db.query(status_expression, expiry_expression)
        .filter(User.id == user.id)
        .one()
    )
    audit_rows = (
        db.query(UserManagementAudit, User.name)
        .join(User, User.id == UserManagementAudit.actor_user_id)
        .filter(
            UserManagementAudit.clinic_id == manager.clinic_id,
            UserManagementAudit.target_user_id == user.id,
        )
        .order_by(UserManagementAudit.created_at.desc())
        .limit(20)
        .all()
    )
    return ManagedUserDetails(
        user=user_item(user, user_status, expiry),
        audit=[
            UserManagementAuditItem(
                id=audit.id,
                actor_name=actor_name,
                action=audit.action,
                summary=audit.summary,
                created_at=audit.created_at,
            )
            for audit, actor_name in audit_rows
        ],
    )


@router.post("", response_model=UserInvitationCreated, status_code=status.HTTP_201_CREATED)
def create_managed_user(
    payload: ManagedUserCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> UserInvitationCreated:
    email = str(payload.email).strip().lower()
    duplicate = db.query(User.id).filter(func.lower(User.email) == email).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Este e-mail já está vinculado a uma conta.")

    setup_token = secrets.token_urlsafe(36)
    user = User(
        clinic_id=manager.clinic_id,
        name=payload.name,
        email=email,
        password_hash=criar_hash_senha(secrets.token_urlsafe(48)),
        role=payload.role,
        active=False,
    )
    db.add(user)
    db.flush()
    now = datetime.now(timezone.utc)
    expires_at = now + INVITATION_TTL
    db.add(
        UserInvitation(
            user_id=user.id,
            token_hash=token_digest(setup_token),
            invited_by=manager.id,
            expires_at=expires_at,
        )
    )
    write_audit(
        db,
        manager.clinic_id,
        manager.id,
        user.id,
        "invitation_created",
        f"Convite de primeiro acesso criado para o perfil {payload.role}.",
    )
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Este e-mail já está vinculado a uma conta.") from error
    return UserInvitationCreated(
        user=user_item(user, "pending", expires_at),
        setup_token=setup_token,
        expires_at=expires_at,
    )


@router.patch("/{user_id}", response_model=ManagedUserItem)
def update_managed_user(
    user_id: int,
    payload: ManagedUserUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedUserItem:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.clinic_id == manager.clinic_id,
            User.role.in_(MANAGED_ROLES),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta clínica.")
    if user.name == payload.name:
        now = datetime.now(timezone.utc)
        status_expression, expiry_expression = latest_invitation_status(now)
        user_status, expiry = db.query(status_expression, expiry_expression).filter(User.id == user.id).one()
        return user_item(user, user_status, expiry)
    user.name = payload.name
    write_audit(
        db,
        manager.clinic_id,
        manager.id,
        user.id,
        "profile_updated",
        "Nome do usuário atualizado pelo gestor.",
    )
    db.commit()
    db.refresh(user)
    now = datetime.now(timezone.utc)
    status_expression, expiry_expression = latest_invitation_status(now)
    user_status, expiry = db.query(status_expression, expiry_expression).filter(User.id == user.id).one()
    return user_item(user, user_status, expiry)


@router.patch("/{user_id}/status", response_model=ManagedUserItem)
def change_managed_user_status(
    user_id: int,
    active: bool = Query(...),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedUserItem:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.clinic_id == manager.clinic_id,
            User.role.in_(MANAGED_ROLES),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado nesta clínica.")
    if user.active == active:
        raise HTTPException(status_code=409, detail="A conta já está nessa situação.")
    if not active and user.role == "dentist":
        today = datetime.now().date()
        upcoming_appointment = (
            db.query(Appointment.id)
            .filter(
                Appointment.clinic_id == manager.clinic_id,
                Appointment.dentist_id == user.id,
                Appointment.appointment_date >= today,
                Appointment.status.notin_(("Cancelada", "Concluída", "Não compareceu")),
            )
            .first()
        )
        if upcoming_appointment:
            raise HTTPException(
                status_code=409,
                detail="Este profissional possui consultas futuras na agenda. Reorganize-as antes de desativar a conta.",
            )
    user.active = active
    write_audit(
        db,
        manager.clinic_id,
        manager.id,
        user.id,
        "account_activated" if active else "account_deactivated",
        "Acesso à conta ativado pelo gestor." if active else "Acesso à conta desativado pelo gestor.",
    )
    db.commit()
    db.refresh(user)
    return user_item(user, "active" if active else "inactive")


@router.post("/{user_id}/invitation/resend", response_model=UserInvitationCreated)
def resend_user_invitation(
    user_id: int,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> UserInvitationCreated:
    user = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.clinic_id == manager.clinic_id,
            User.role.in_(MANAGED_ROLES),
            User.active.is_(False),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Convite pendente não encontrado nesta clínica.")
    now = datetime.now(timezone.utc)
    pending = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.user_id == user.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=409, detail="O convite ainda está válido; aguarde a expiração antes de reenviar.")
    for previous in db.query(UserInvitation).filter(
        UserInvitation.user_id == user.id,
        UserInvitation.accepted_at.is_(None),
        UserInvitation.revoked_at.is_(None),
    ):
        previous.revoked_at = now

    setup_token = secrets.token_urlsafe(36)
    expires_at = now + INVITATION_TTL
    db.add(
        UserInvitation(
            user_id=user.id,
            token_hash=token_digest(setup_token),
            invited_by=manager.id,
            expires_at=expires_at,
        )
    )
    write_audit(
        db,
        manager.clinic_id,
        manager.id,
        user.id,
        "invitation_resent",
        "Convite de primeiro acesso renovado pelo gestor.",
    )
    db.commit()
    return UserInvitationCreated(
        user=user_item(user, "pending", expires_at),
        setup_token=setup_token,
        expires_at=expires_at,
    )


@router.post("/invitation/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_user_invitation(
    payload: AcceptUserInvitation,
    db: Session = Depends(get_db),
) -> None:
    now = datetime.now(timezone.utc)
    invitation = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.token_hash == token_digest(payload.token),
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .first()
    )
    if invitation is None:
        raise HTTPException(
            status_code=400,
            detail="Este link de primeiro acesso é inválido, expirado ou já foi utilizado. Solicite um novo à clínica.",
        )
    user = db.query(User).filter(User.id == invitation.user_id, User.active.is_(False)).first()
    if user is None:
        raise HTTPException(status_code=400, detail="Esta conta não pode aceitar o convite.")
    claimed = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.id == invitation.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .update({UserInvitation.accepted_at: now}, synchronize_session=False)
    )
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="Este link de primeiro acesso já foi utilizado.")
    user.password_hash = criar_hash_senha(payload.password)
    user.active = True
    write_audit(
        db,
        user.clinic_id,
        user.id,
        user.id,
        "invitation_accepted",
        "Primeiro acesso concluído pelo próprio usuário.",
    )
    db.commit()
