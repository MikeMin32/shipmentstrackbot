"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TelegramUserOut(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None


class NamedEntityOut(BaseModel):
    id: int | None
    name: str
    archived: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    total: int | None = None
    active: int | None = None
    unassigned: bool | None = None


class NamedEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned


class NamedEntityUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned


class ShipmentCreate(BaseModel):
    account_id: int
    country: str = Field(min_length=1, max_length=40)
    clone: str = Field(min_length=1, max_length=80)
    client_team_id: int | None = None
    box_weight: float | None = None
    status: str | None = None
    label_creation_date: str | None = None
    scanned_in_date: str | None = None
    expected_delivery_date: str | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("country", "clone")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field is required")
        return cleaned

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ShipmentUpdate(BaseModel):
    account_id: int | None = None
    country: str | None = Field(default=None, max_length=40)
    clone: str | None = Field(default=None, max_length=80)
    client_team_id: int | None = None
    clear_client_team: bool = False
    box_weight: float | None = None
    clear_box_weight: bool = False
    label_creation_date: str | None = None
    scanned_in_date: str | None = None
    expected_delivery_date: str | None = None
    clear_label_creation_date: bool = False
    clear_scanned_in_date: bool = False
    clear_expected_delivery_date: bool = False
    note: str | None = Field(default=None, max_length=500)
    clear_note: bool = False

    @field_validator("country", "clone")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be empty")
        return cleaned


class StatusUpdate(BaseModel):
    status: str


class ReminderUpsert(BaseModel):
    remind_at: str = Field(description="ISO 8601 UTC datetime, e.g. 2026-09-04T15:00:00Z")


class PaginatedShipments(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
