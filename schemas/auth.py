from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthenticatedUser(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    clinic_id: int
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe um nome com pelo menos 2 caracteres.")
        return normalized


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if not any(character.islower() for character in value):
            raise ValueError("A nova senha deve conter ao menos uma letra minúscula.")
        if not any(character.isupper() for character in value):
            raise ValueError("A nova senha deve conter ao menos uma letra maiúscula.")
        if not any(character.isdigit() for character in value):
            raise ValueError("A nova senha deve conter ao menos um número.")
        return value


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthenticatedUser


class UserPreferencesPayload(BaseModel):
    theme: Literal["system", "light", "dark"] = "system"
    fontScale: Literal[100, 112, 125, 137] = 100
    density: Literal["comfortable", "compact"] = "comfortable"
    accent: Literal["blue", "teal", "coral"] = "blue"
    highContrast: bool = False
    reducedMotion: bool = False
    visibleFocus: bool = True
    underlineLinks: bool = False
    expandedSpacing: bool = False
    pageSize: Literal[10, 20, 50] = 10
    homePage: str = Field(min_length=1, max_length=64)
    confirmActions: bool = True
    dateFormat: Literal["dd/MM/yyyy"] = "dd/MM/yyyy"
    timeFormat: Literal["24h"] = "24h"

    model_config = ConfigDict(extra="forbid")


class UserPreferencesResponse(BaseModel):
    preferences: UserPreferencesPayload
    customized: bool
