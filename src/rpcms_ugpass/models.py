from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Mou(Base):
    __tablename__ = "mou"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reference: Mapped[str] = mapped_column(String(128), unique=True)
    programme_id: Mapped[str] = mapped_column(String(128))
    amp_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    signatories: Mapped[list["Signatory"]] = relationship(
        back_populates="mou", order_by="Signatory.order", cascade="all, delete-orphan")
    seals: Mapped[list["Seal"]] = relationship(back_populates="mou", cascade="all, delete-orphan")


class Signatory(Base):
    __tablename__ = "signatory"
    __table_args__ = (UniqueConstraint("mou_id", "order"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mou_id: Mapped[str] = mapped_column(ForeignKey("mou.id"))
    name: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(128))
    organisation: Mapped[str] = mapped_column(String(256))
    order: Mapped[int] = mapped_column(Integer)
    seal_required: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="WAITING")
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    certificate_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mou: Mapped[Mou] = relationship(back_populates="signatories")


class Seal(Base):
    __tablename__ = "seal"
    __table_args__ = (UniqueConstraint("mou_id", "organisation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mou_id: Mapped[str] = mapped_column(ForeignKey("mou.id"))
    organisation: Mapped[str] = mapped_column(String(256))
    seal_ref: Mapped[str] = mapped_column(String(128))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    mou: Mapped[Mou] = relationship(back_populates="seals")
