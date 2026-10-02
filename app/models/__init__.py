"""يجمع كل النماذج تحت Base.metadata الواحدة — لازم لـ alembic autogenerate."""

from app.models.base import Base
from app.models.core import ClientCurrencyLocation, Currency, Location
from app.models.accounts import Account, AccountNumberAssignment, AccountNumberCounter
from app.models.partners import (
    Client,
    ClientCreditLimit,
    ClientPortalInvite,
    Partner,
)
from app.models.journal import EntryComment, JournalEntry, JournalLine
from app.models.swift import SwiftMovement
from app.models.lots import CurrencyLot, LotConsumption
from app.models.opening import OpeningBalance, OpeningReconciliation
from app.models.system import (
    AccountBalance,
    AuditLog,
    Counter,
    EditRequest,
    FoundingPeriod,
    IdempotencyKey,
    OutageWindow,
    PartnerStatement,
    PartnerStatementLine,
    Period,
    Session,
    Setting,
    User,
    UserBackupCode,
)

__all__ = [
    "Base",
    "ClientCurrencyLocation",
    "Currency",
    "Location",
    "Account",
    "AccountNumberAssignment",
    "AccountNumberCounter",
    "Client",
    "ClientCreditLimit",
    "ClientPortalInvite",
    "Partner",
    "EntryComment",
    "JournalEntry",
    "JournalLine",
    "SwiftMovement",
    "CurrencyLot",
    "LotConsumption",
    "OpeningBalance",
    "OpeningReconciliation",
    "AccountBalance",
    "AuditLog",
    "Counter",
    "EditRequest",
    "FoundingPeriod",
    "IdempotencyKey",
    "OutageWindow",
    "PartnerStatement",
    "PartnerStatementLine",
    "Period",
    "Session",
    "Setting",
    "User",
    "UserBackupCode",
]
