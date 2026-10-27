from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CATEGORIES = ("agenda", "reception", "confirmations", "communications", "system")
EVENTS = (
    "new_appointment",
    "appointment_cancelled",
    "appointment_rescheduled",
    "appointment_changed",
    "appointment_upcoming",
    "appointment_confirmation_pending",
    "patient_will_not_attend",
    "patient_arrived",
    "patient_waiting",
    "patient_waiting_too_long",
    "walk_in_patient",
    "patient_confirmed",
    "reschedule_requested",
    "reminder_unanswered",
    "reminder_failed",
    "integration_message_received",
    "important_operation_failed",
    "integration_unavailable",
    "manager_announcement",
)

DEFAULT_SETTINGS = {
    "enabled": True,
    "sound": False,
    "show_in_app": True,
    "keep_important": True,
    "quiet_hours_enabled": False,
    "quiet_start": "18:00",
    "quiet_end": "08:00",
    "upcoming_reminder_minutes": 30,
    "repeat_limit": 1,
    "group_similar": True,
    "categories": {category: True for category in CATEGORIES},
    "events": {event: True for event in EVENTS},
    "priorities": {
        event: "important" if event == "important_operation_failed" else "informative"
        for event in EVENTS
    },
    "channels": {
        event: {
            "in_app": True,
            "browser": False,
            "email": False,
            "whatsapp": False,
            "sms": False,
        }
        for event in EVENTS
    },
}


class NotificationChannelPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_app: bool = True
    browser: bool = False
    email: bool = False
    whatsapp: bool = False
    sms: bool = False


class NotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    sound: bool = False
    show_in_app: bool = True
    keep_important: bool = True
    quiet_hours_enabled: bool = False
    quiet_start: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    quiet_end: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    upcoming_reminder_minutes: Literal[15, 30, 60] = 30
    repeat_limit: int = Field(default=1, ge=0, le=5)
    group_similar: bool = True
    categories: dict[str, bool] = Field(
        default_factory=lambda: DEFAULT_SETTINGS["categories"].copy()
    )
    events: dict[str, bool] = Field(
        default_factory=lambda: DEFAULT_SETTINGS["events"].copy()
    )
    priorities: dict[str, Literal["informative", "important", "urgent"]] = Field(
        default_factory=lambda: DEFAULT_SETTINGS["priorities"].copy()
    )
    channels: dict[str, NotificationChannelPreferences] = Field(
        default_factory=lambda: {
            event: NotificationChannelPreferences()
            for event in EVENTS
        }
    )

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def validate_time(cls, value: str) -> str:
        hour, minute = (int(part) for part in value.split(":"))
        if hour > 23 or minute > 59:
            raise ValueError("Informe um horário válido.")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: dict[str, bool]) -> dict[str, bool]:
        if set(value) != set(CATEGORIES):
            raise ValueError("A configuração deve incluir todas as categorias válidas.")
        return value

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: dict[str, bool]) -> dict[str, bool]:
        if set(value) != set(EVENTS):
            raise ValueError("A configuração deve incluir todos os eventos válidos.")
        return value

    @field_validator("priorities")
    @classmethod
    def validate_priorities(
        cls, value: dict[str, Literal["informative", "important", "urgent"]]
    ) -> dict[str, Literal["informative", "important", "urgent"]]:
        if set(value) != set(EVENTS):
            raise ValueError("A configuração deve incluir a prioridade de cada evento.")
        return value

    @field_validator("channels")
    @classmethod
    def validate_channels(
        cls, value: dict[str, NotificationChannelPreferences]
    ) -> dict[str, NotificationChannelPreferences]:
        if set(value) != set(EVENTS):
            raise ValueError("A configuração deve incluir os canais de cada evento.")
        if any(
            channel.email or channel.whatsapp or channel.sms
            for channel in value.values()
        ):
            raise ValueError("Os canais externos ainda não estão integrados.")
        return value


class NotificationPreferencesResponse(BaseModel):
    preferences: NotificationPreferences
    capabilities: dict[str, bool | list[str]]
