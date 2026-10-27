from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


UserRole = Literal["dentist", "receptionist"]
UserStatus = Literal["active", "inactive", "pending", "expired"]


class ManagedUserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    role: UserRole

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe um nome com pelo menos 2 caracteres.")
        return normalized


class ManagedUserUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe um nome com pelo menos 2 caracteres.")
        return normalized


class ManagedUserItem(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    active: bool
    status: UserStatus
    created_at: datetime
    invitation_expires_at: datetime | None = None


class ManagedUserMetrics(BaseModel):
    total: int
    active: int
    inactive: int
    dentists: int
    receptionists: int
    pending_invitations: int


class ManagedUserList(BaseModel):
    items: list[ManagedUserItem]
    total: int
    offset: int
    limit: int
    metrics: ManagedUserMetrics


class UserInvitationCreated(BaseModel):
    user: ManagedUserItem
    setup_token: str
    expires_at: datetime


class AcceptUserInvitation(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not any(character.islower() for character in value):
            raise ValueError("A senha deve conter ao menos uma letra minúscula.")
        if not any(character.isupper() for character in value):
            raise ValueError("A senha deve conter ao menos uma letra maiúscula.")
        if not any(character.isdigit() for character in value):
            raise ValueError("A senha deve conter ao menos um número.")
        return value


class UserManagementAuditItem(BaseModel):
    id: int
    actor_name: str
    action: str
    summary: str
    created_at: datetime


class ManagedUserDetails(BaseModel):
    user: ManagedUserItem
    audit: list[UserManagementAuditItem]
