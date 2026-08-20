import enum

from sqlalchemy import Enum as PgEnum


class AccountType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class AccountForm(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    CORRESPONDENT = "CORRESPONDENT"
    CLEARING = "CLEARING"


class EntryStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class OperationType(str, enum.Enum):
    RECEIPT = "RECEIPT"
    PAYMENT = "PAYMENT"
    EXCHANGE = "EXCHANGE"
    CASH_TRANSFER = "CASH_TRANSFER"
    LOCAL_MOVE = "LOCAL_MOVE"
    SWIFT_OUT = "SWIFT_OUT"
    SWIFT_IN = "SWIFT_IN"
    SWIFT_RETURN = "SWIFT_RETURN"
    REMIT_OUT = "REMIT_OUT"
    EXPENSE = "EXPENSE"
    OPENING = "OPENING"
    ADJUSTMENT = "ADJUSTMENT"


class SwiftStatus(str, enum.Enum):
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    RETURNED = "RETURNED"


class LotStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OpeningSourceType(str, enum.Enum):
    VERIFIED = "VERIFIED"
    RECONSTRUCTED = "RECONSTRUCTED"
    KNOWN_BALANCE = "KNOWN_BALANCE"
    ADJUSTMENT = "ADJUSTMENT"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReconciliationStatus(str, enum.Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class EditRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SessionSubjectType(str, enum.Enum):
    USER = "USER"
    CLIENT = "CLIENT"


# §5-8 — ENUM Postgres حقيقي لكل مجموعة مغلقة، إلا user_role (CHECK نصّي — انظر
# system.py). كائن واحد لكل نوع يُستورَد أينما استُخدم كي لا يُصدر
# CREATE TYPE مرتين على نفس الاسم عند إنشاء الجداول من نفس الـ metadata.
def _values(e):
    return [m.value for m in e]


account_type_enum = PgEnum(AccountType, name="account_type", values_callable=_values)
account_form_enum = PgEnum(AccountForm, name="account_form", values_callable=_values)
entry_status_enum = PgEnum(EntryStatus, name="entry_status", values_callable=_values)
operation_type_enum = PgEnum(OperationType, name="operation_type", values_callable=_values)
swift_status_enum = PgEnum(SwiftStatus, name="swift_status", values_callable=_values)
lot_status_enum = PgEnum(LotStatus, name="lot_status", values_callable=_values)
opening_source_type_enum = PgEnum(
    OpeningSourceType, name="opening_source_type", values_callable=_values
)
confidence_level_enum = PgEnum(ConfidenceLevel, name="confidence_level", values_callable=_values)
reconciliation_status_enum = PgEnum(
    ReconciliationStatus, name="reconciliation_status", values_callable=_values
)
edit_request_status_enum = PgEnum(
    EditRequestStatus, name="edit_request_status", values_callable=_values
)
session_subject_type_enum = PgEnum(
    SessionSubjectType, name="session_subject_type", values_callable=_values
)
