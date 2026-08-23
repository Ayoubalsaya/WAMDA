"""شاشة المستخدمين (§٧-١٤ / §٩) — هنا الطبقة الخلفية فقط لهذه المرحلة؛
الواجهة الفعلية مرحلة لاحقة (٩/١٠). المسار الصحيح الوحيد لإنشاء أي مدير
بعد الأول — بما فيه المدير الاحتياطي (§٩) — بمدير مسجَّل الدخول فعلياً.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine.clock import system_clock
from app.models import User
from app.schemas.auth import CreateUserRequest, CreateUserResponse
from app.security import user_management
from app.security.deps import require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_user(
    payload: CreateUserRequest,
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> CreateUserResponse:
    now = system_clock()
    try:
        user = user_management.create_user(
            db,
            created_by=current_user,
            username=payload.username,
            full_name=payload.full_name,
            role=payload.role,
            initial_password=payload.initial_password,
            now=now,
            security_question=payload.security_question,
            security_answer=payload.security_answer,
        )
    except user_management.UsernameTakenError as exc:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except user_management.InvalidRoleError as exc:
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    db.commit()
    return CreateUserResponse(id=user.id, username=user.username, role=user.role)
