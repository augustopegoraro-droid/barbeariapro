# file: app/schemas/site_visibility.py
"""Contratos da configuração de visibilidade do site público (Fase 6,
`/admin/security/site-visibility`). O site público em si ainda não existe —
isto é só a configuração, pronta para quando o produto tiver a página."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class VisibilitySelection(BaseModel):
    mode: Literal["all", "custom"] = "all"
    ids: list[int] = Field(default_factory=list)


class BannerSettings(BaseModel):
    enabled: bool = False
    image_url: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None


class PublicInfoSettings(BaseModel):
    address: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    instagram: Optional[str] = None
    website: Optional[str] = None


class SiteVisibilityOut(BaseModel):
    services: VisibilitySelection
    professionals: VisibilitySelection
    show_hours: bool
    show_reviews: bool
    show_promotions: bool
    banner: BannerSettings
    public_info: PublicInfoSettings
    updated_by_email: Optional[str] = None
    updated_at: datetime


class SiteVisibilityUpdateIn(BaseModel):
    services: VisibilitySelection
    professionals: VisibilitySelection
    show_hours: bool
    show_reviews: bool
    show_promotions: bool
    banner: BannerSettings
    public_info: PublicInfoSettings
