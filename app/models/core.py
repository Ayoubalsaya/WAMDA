from sqlalchemy import Boolean, CheckConstraint, Index, Integer, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Currency(Base):
    """§3-1 — لا تُثبّت عدد العملات في الكود."""

    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(Text, primary_key=True)  # 'LYD','USD','CNY', ...
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_pivot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("decimals BETWEEN 0 AND 6", name="ck_currencies_decimals"),
        Index("ux_currencies_single_pivot", "is_pivot", unique=True, postgresql_where=text("is_pivot")),
    )


class Location(Base):
    """§3-1 — الأولية: TRIPOLI · BENGHAZI · LIBYA_BANK · TURKEY · CHINA. لا تُثبّت في الكود."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
