from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from PIL import Image
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .config import BASE_DIR, CORS_ORIGINS, MAX_UPLOAD_MB, UPLOAD_DIR
from .database import Base, engine, get_db
from .models import (
    CheckinPhoto,
    Child,
    Family,
    FamilyUser,
    ReadingCheckin,
    ReadingPlan,
    RewardRedemption,
    User,
)
from .security import create_session_token, hash_password, read_session_token, verify_password


app = FastAPI(title="Reading Check-in API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


class RegisterIn(BaseModel):
    phone: str
    password: str = Field(min_length=6)
    familyName: str = Field(min_length=1, max_length=80)
    parentName: str = Field(min_length=1, max_length=40)
    defaultChildName: str = Field(min_length=1, max_length=40)


class LoginIn(BaseModel):
    phone: str
    password: str


class ResetPasswordIn(BaseModel):
    phone: str
    newPassword: str = Field(min_length=6)


class ChangePasswordIn(BaseModel):
    oldPassword: str
    newPassword: str = Field(min_length=6)


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    birthDate: date | None = None
    isDefault: bool = False


class PlanIn(BaseModel):
    childId: str
    title: str = Field(min_length=1, max_length=120)
    bookName: str | None = None
    targetCheckins: int = 21
    rewardPerCheckin: Decimal = Decimal("0")
    startDate: date | None = None
    endDate: date | None = None
    note: str | None = None


class RedemptionIn(BaseModel):
    childId: str
    redemptionDate: date
    amount: Decimal
    note: str | None = None


class PlanUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    bookName: str | None = None
    targetCheckins: int | None = None
    rewardPerCheckin: Decimal | None = None
    startDate: date | None = None
    endDate: date | None = None
    note: str | None = None
    status: str | None = None


class ChildUpdateIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    birthDate: date | None = None


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def money(value: Decimal | int | float | None) -> str:
    return f"{Decimal(value or 0):.2f}"


def set_auth_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        "reading_session",
        create_session_token(uuid.UUID(user_id)),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def current_context(request: Request, db: Session) -> tuple[User, Family]:
    token = request.cookies.get("reading_session")
    user_id = read_session_token(token or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = db.get(User, user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="登录已失效")
    family_user = db.scalar(select(FamilyUser).where(FamilyUser.user_id == user.id).limit(1))
    if not family_user:
        raise HTTPException(status_code=403, detail="账号未绑定家庭")
    family = db.get(Family, family_user.family_id)
    if not family or family.status != "active":
        raise HTTPException(status_code=403, detail="家庭不可用")
    return user, family


def require_context(request: Request, db: Annotated[Session, Depends(get_db)]) -> tuple[User, Family]:
    return current_context(request, db)


def child_or_404(db: Session, family_id: str, child_id: str) -> Child:
    child = db.get(Child, child_id)
    if not child or child.family_id != family_id or child.status != "active":
        raise HTTPException(status_code=404, detail="孩子不存在")
    return child


def plan_or_404(db: Session, family_id: str, plan_id: str) -> ReadingPlan:
    plan = db.get(ReadingPlan, plan_id)
    if not plan or plan.family_id != family_id:
        raise HTTPException(status_code=404, detail="计划不存在")
    return plan


def child_to_dict(child: Child) -> dict:
    return {
        "id": child.id,
        "name": child.name,
        "birthDate": child.birth_date.isoformat() if child.birth_date else None,
        "avatarUrl": child.avatar_url,
        "isDefault": child.is_default,
        "createdAt": child.created_at.isoformat() if child.created_at else None,
    }


def plan_to_dict(plan: ReadingPlan, checkin_count: int = 0) -> dict:
    return {
        "id": plan.id,
        "childId": plan.child_id,
        "title": plan.title,
        "bookName": plan.book_name,
        "targetCheckins": plan.target_checkins,
        "rewardPerCheckin": money(plan.reward_per_checkin),
        "startDate": plan.start_date.isoformat() if plan.start_date else None,
        "endDate": plan.end_date.isoformat() if plan.end_date else None,
        "status": plan.status,
        "note": plan.note,
        "checkinCount": checkin_count,
    }


def checkin_to_dict(db: Session, item: ReadingCheckin) -> dict:
    photos = db.scalars(select(CheckinPhoto).where(CheckinPhoto.checkin_id == item.id)).all()
    return {
        "id": item.id,
        "childId": item.child_id,
        "planId": item.plan_id,
        "checkinDate": item.checkin_date.isoformat(),
        "minutes": item.minutes,
        "rewardAmount": money(item.reward_amount),
        "note": item.note,
        "photos": [{"id": p.id, "url": p.file_url} for p in photos],
        "createdAt": item.created_at.isoformat() if item.created_at else None,
    }


def reward_stats(db: Session, family_id: str, child_id: str) -> dict:
    earned = db.scalar(
        select(func.coalesce(func.sum(ReadingCheckin.reward_amount), 0)).where(
            ReadingCheckin.family_id == family_id,
            ReadingCheckin.child_id == child_id,
        )
    )
    redeemed = db.scalar(
        select(func.coalesce(func.sum(RewardRedemption.amount), 0)).where(
            RewardRedemption.family_id == family_id,
            RewardRedemption.child_id == child_id,
        )
    )
    count = db.scalar(
        select(func.count(RewardRedemption.id)).where(
            RewardRedemption.family_id == family_id,
            RewardRedemption.child_id == child_id,
        )
    )
    return {
        "earnedAmount": money(earned),
        "redeemedAmount": money(redeemed),
        "balanceAmount": money(Decimal(earned or 0) - Decimal(redeemed or 0)),
        "redemptionCount": count or 0,
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(BASE_DIR / "reading-checkin.html")


@app.get("/reading-checkin.html")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "reading-checkin.html")


@app.post("/api/auth/register")
def register(payload: RegisterIn, response: Response, db: Annotated[Session, Depends(get_db)]) -> dict:
    phone = normalize_phone(payload.phone)
    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(status_code=409, detail="手机号已注册")
    family = Family(name=payload.familyName.strip())
    user = User(phone=phone, display_name=payload.parentName.strip(), password_hash=hash_password(payload.password))
    db.add_all([family, user])
    db.flush()
    db.add(FamilyUser(family_id=family.id, user_id=user.id, role="parent", is_primary=True))
    db.add(Child(family_id=family.id, name=payload.defaultChildName.strip(), is_default=True))
    db.commit()
    set_auth_cookie(response, user.id)
    return me_payload(db, user, family)


@app.post("/api/auth/login")
def login(payload: LoginIn, response: Response, db: Annotated[Session, Depends(get_db)]) -> dict:
    phone = normalize_phone(payload.phone)
    user = db.scalar(select(User).where(User.phone == phone))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="手机号或密码不正确")
    family_user = db.scalar(select(FamilyUser).where(FamilyUser.user_id == user.id).limit(1))
    if not family_user:
        raise HTTPException(status_code=403, detail="账号未绑定家庭")
    family = db.get(Family, family_user.family_id)
    set_auth_cookie(response, user.id)
    return me_payload(db, user, family)


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("reading_session", path="/")
    return {"ok": True}


@app.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordIn, db: Annotated[Session, Depends(get_db)]) -> dict:
    phone = normalize_phone(payload.phone)
    user = db.scalar(select(User).where(User.phone == phone))
    if not user:
        raise HTTPException(status_code=404, detail="该手机号未注册")
    user.password_hash = hash_password(payload.newPassword)
    db.commit()
    return {"ok": True, "message": "密码重置成功，请使用新密码登录"}


@app.post("/api/auth/change-password")
def change_password(
    payload: ChangePasswordIn,
    ctx: Annotated[tuple[User, Family], Depends(require_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    user, _ = ctx
    if not verify_password(payload.oldPassword, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.newPassword)
    db.commit()
    return {"ok": True, "message": "密码修改成功"}


def me_payload(db: Session, user: User, family: Family) -> dict:
    default_child = db.scalar(
        select(Child).where(Child.family_id == family.id, Child.status == "active", Child.is_default.is_(True)).limit(1)
    )
    return {
        "user": {"id": user.id, "phone": user.phone, "displayName": user.display_name},
        "family": {"id": family.id, "name": family.name},
        "defaultChildId": default_child.id if default_child else None,
    }


@app.get("/api/me")
def me(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    user, family = ctx
    return me_payload(db, user, family)


@app.get("/api/children")
def list_children(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    _, family = ctx
    children = db.scalars(select(Child).where(Child.family_id == family.id, Child.status == "active").order_by(Child.created_at)).all()
    return [child_to_dict(item) for item in children]


@app.post("/api/children")
def create_child(payload: ChildIn, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    if payload.isDefault:
        db.query(Child).filter(Child.family_id == family.id).update({Child.is_default: False})
    child = Child(family_id=family.id, name=payload.name.strip(), birth_date=payload.birthDate, is_default=payload.isDefault)
    db.add(child)
    db.flush()
    if not payload.isDefault and db.scalar(select(func.count(Child.id)).where(Child.family_id == family.id)) == 1:
        child.is_default = True
    db.commit()
    db.refresh(child)
    return child_to_dict(child)


@app.post("/api/children/{child_id}/default")
def set_default_child(child_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    child = child_or_404(db, family.id, child_id)
    db.query(Child).filter(Child.family_id == family.id).update({Child.is_default: False})
    child.is_default = True
    db.commit()
    return {"ok": True}


@app.patch("/api/children/{child_id}")
def update_child(child_id: str, payload: ChildUpdateIn, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    child = child_or_404(db, family.id, child_id)
    if payload.name is not None:
        child.name = payload.name.strip()
    if payload.birthDate is not None:
        child.birth_date = payload.birthDate
    db.commit()
    db.refresh(child)
    return child_to_dict(child)


@app.delete("/api/children/{child_id}")
def delete_child(child_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    child = child_or_404(db, family.id, child_id)
    # 检查是否有关联的活跃计划
    active_plan_count = db.scalar(
        select(func.count(ReadingPlan.id)).where(
            ReadingPlan.child_id == child_id,
            ReadingPlan.status == "active",
        )
    ) or 0
    if active_plan_count > 0:
        raise HTTPException(status_code=400, detail=f"该孩子还有 {active_plan_count} 个进行中的计划，请先完成或删除计划")
    child.status = "deleted"
    child.is_default = False
    db.commit()
    return {"ok": True}


@app.get("/api/plans")
def list_plans(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)], childId: str | None = None) -> list[dict]:
    _, family = ctx
    stmt: Select[tuple[ReadingPlan]] = select(ReadingPlan).where(ReadingPlan.family_id == family.id, ReadingPlan.status != "deleted")
    if childId:
        child_or_404(db, family.id, childId)
        stmt = stmt.where(ReadingPlan.child_id == childId)
    plans = db.scalars(stmt.order_by(ReadingPlan.created_at.desc())).all()
    result = []
    for plan in plans:
        count = db.scalar(select(func.count(ReadingCheckin.id)).where(ReadingCheckin.plan_id == plan.id)) or 0
        result.append(plan_to_dict(plan, count))
    return result


@app.post("/api/plans")
def create_plan(payload: PlanIn, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    user, family = ctx
    child_or_404(db, family.id, payload.childId)
    plan = ReadingPlan(
        family_id=family.id,
        child_id=payload.childId,
        title=payload.title.strip(),
        book_name=(payload.bookName or "").strip() or None,
        target_checkins=payload.targetCheckins,
        reward_per_checkin=payload.rewardPerCheckin,
        start_date=payload.startDate,
        end_date=payload.endDate,
        note=(payload.note or "").strip() or None,
        created_by=user.id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan_to_dict(plan)


@app.post("/api/plans/{plan_id}/complete")
def toggle_plan(plan_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    plan = plan_or_404(db, family.id, plan_id)
    plan.status = "active" if plan.status == "completed" else "completed"
    db.commit()
    return plan_to_dict(plan)


@app.patch("/api/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanUpdateIn, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    plan = plan_or_404(db, family.id, plan_id)
    if payload.title is not None:
        plan.title = payload.title.strip()
    if payload.bookName is not None:
        plan.book_name = payload.bookName.strip() or None
    if payload.targetCheckins is not None:
        plan.target_checkins = payload.targetCheckins
    if payload.rewardPerCheckin is not None:
        plan.reward_per_checkin = payload.rewardPerCheckin
    if payload.startDate is not None:
        plan.start_date = payload.startDate
    if payload.endDate is not None:
        plan.end_date = payload.endDate
    if payload.note is not None:
        plan.note = payload.note.strip() or None
    if payload.status is not None:
        plan.status = payload.status
    db.commit()
    db.refresh(plan)
    count = db.scalar(select(func.count(ReadingCheckin.id)).where(ReadingCheckin.plan_id == plan.id)) or 0
    return plan_to_dict(plan, count)


@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    plan = plan_or_404(db, family.id, plan_id)
    plan.status = "deleted"
    db.commit()
    return {"ok": True}


@app.get("/api/checkins")
def list_checkins(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)], childId: str | None = None, planId: str | None = None) -> list[dict]:
    _, family = ctx
    stmt = select(ReadingCheckin).where(ReadingCheckin.family_id == family.id)
    if childId:
        child_or_404(db, family.id, childId)
        stmt = stmt.where(ReadingCheckin.child_id == childId)
    if planId:
        plan_or_404(db, family.id, planId)
        stmt = stmt.where(ReadingCheckin.plan_id == planId)
    items = db.scalars(stmt.order_by(ReadingCheckin.checkin_date.desc(), ReadingCheckin.created_at.desc())).all()
    return [checkin_to_dict(db, item) for item in items]


@app.post("/api/checkins")
def create_checkin(
    ctx: Annotated[tuple[User, Family], Depends(require_context)],
    db: Annotated[Session, Depends(get_db)],
    childId: str = Form(...),
    planId: str = Form(...),
    checkinDate: date = Form(...),
    minutes: int = Form(0),
    rewardAmount: Decimal = Form(0),
    note: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
) -> dict:
    user, family = ctx
    child_or_404(db, family.id, childId)
    plan = plan_or_404(db, family.id, planId)
    if plan.child_id != childId:
        raise HTTPException(status_code=400, detail="计划不属于所选孩子")
    item = ReadingCheckin(
        family_id=family.id,
        child_id=childId,
        plan_id=planId,
        checkin_date=checkinDate,
        minutes=minutes,
        reward_amount=rewardAmount,
        note=note.strip() or None,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    for upload in photos[:4]:
        saved = save_upload(family.id, item.id, upload)
        db.add(CheckinPhoto(family_id=family.id, checkin_id=item.id, **saved))
    db.commit()
    db.refresh(item)
    return checkin_to_dict(db, item)


def save_upload(family_id: str, checkin_id: str, upload: UploadFile) -> dict:
    """保存图片并压缩到 100KB 以内"""
    if upload.content_type and not upload.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只能上传图片")

    # 读取原始数据
    raw = upload.file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"单张图片不能超过 {MAX_UPLOAD_MB}MB")

    folder = UPLOAD_DIR / family_id / checkin_id
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"  # 统一保存为 JPG
    target = folder / filename

    # 压缩图片
    MAX_SIZE_KB = 100
    MAX_DIMENSION = 1920
    try:
        img = Image.open(io.BytesIO(raw))
        # 处理 RGBA/透明通道
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        # 缩小尺寸
        w, h = img.size
        if max(w, h) > MAX_DIMENSION:
            ratio = MAX_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        # 二分查找合适的 quality
        low, high = 20, 92
        best_data = None
        while low <= high:
            mid = (low + high) // 2
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=mid, optimize=True)
            size = buf.tell()
            if size <= MAX_SIZE_KB * 1024:
                best_data = buf.getvalue()
                low = mid + 1  # 尝试更高质量
            else:
                high = mid - 1
        # 如果最低质量仍超限，用最低质量保存
        if best_data is None:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=15, optimize=True)
            best_data = buf.getvalue()

        target.write_bytes(best_data)
        size = len(best_data)
    except Exception as e:
        # 压缩失败，保存原图
        target.write_bytes(raw)
        size = len(raw)

    rel = f"{family_id}/{checkin_id}/{filename}"
    return {
        "file_url": f"/uploads/{rel}",
        "object_key": rel,
        "mime_type": "image/jpeg",
        "file_size": size,
    }


@app.delete("/api/checkins/{checkin_id}")
def delete_checkin(checkin_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    item = db.get(ReadingCheckin, checkin_id)
    if not item or item.family_id != family.id:
        raise HTTPException(status_code=404, detail="打卡记录不存在")
    # 删除关联照片记录（文件保留在磁盘，定期清理）
    db.query(CheckinPhoto).filter(CheckinPhoto.checkin_id == checkin_id).delete()
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/api/rewards/children")
def rewards_by_child(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> list[dict]:
    _, family = ctx
    children = db.scalars(select(Child).where(Child.family_id == family.id, Child.status == "active").order_by(Child.created_at)).all()
    result = []
    for child in children:
        result.append({"childId": child.id, "childName": child.name, **reward_stats(db, family.id, child.id)})
    return result


@app.get("/api/redemptions")
def list_redemptions(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)], childId: str | None = None) -> list[dict]:
    _, family = ctx
    stmt = select(RewardRedemption).where(RewardRedemption.family_id == family.id)
    if childId:
        child_or_404(db, family.id, childId)
        stmt = stmt.where(RewardRedemption.child_id == childId)
    rows = db.scalars(stmt.order_by(RewardRedemption.redemption_date.desc(), RewardRedemption.created_at.desc())).all()
    return [
        {
            "id": row.id,
            "childId": row.child_id,
            "redemptionDate": row.redemption_date.isoformat(),
            "amount": money(row.amount),
            "note": row.note,
        }
        for row in rows
    ]


@app.post("/api/redemptions")
def create_redemption(payload: RedemptionIn, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    user, family = ctx
    child_or_404(db, family.id, payload.childId)
    stats = reward_stats(db, family.id, payload.childId)
    if payload.amount > Decimal(stats["balanceAmount"]):
        raise HTTPException(status_code=400, detail="兑换金额不能超过该孩子可兑换余额")
    row = RewardRedemption(
        family_id=family.id,
        child_id=payload.childId,
        redemption_date=payload.redemptionDate,
        amount=payload.amount,
        note=(payload.note or "").strip() or None,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "childId": row.child_id,
        "redemptionDate": row.redemption_date.isoformat(),
        "amount": money(row.amount),
        "note": row.note,
    }


@app.delete("/api/redemptions/{redemption_id}")
def delete_redemption(redemption_id: str, ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    row = db.get(RewardRedemption, redemption_id)
    if not row or row.family_id != family.id:
        raise HTTPException(status_code=404, detail="兑换记录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(ctx: Annotated[tuple[User, Family], Depends(require_context)], db: Annotated[Session, Depends(get_db)]) -> dict:
    _, family = ctx
    today = date.today()
    active_plan_count = db.scalar(select(func.count(ReadingPlan.id)).where(ReadingPlan.family_id == family.id, ReadingPlan.status == "active")) or 0
    total_checkin_count = db.scalar(select(func.count(ReadingCheckin.id)).where(ReadingCheckin.family_id == family.id)) or 0
    today_checkin_count = db.scalar(select(func.count(ReadingCheckin.id)).where(ReadingCheckin.family_id == family.id, ReadingCheckin.checkin_date == today)) or 0
    default_child = db.scalar(select(Child).where(Child.family_id == family.id, Child.is_default.is_(True), Child.status == "active").limit(1))
    balance = "0.00"
    if default_child:
        balance = reward_stats(db, family.id, default_child.id)["balanceAmount"]
    recent = db.scalars(select(ReadingCheckin).where(ReadingCheckin.family_id == family.id).order_by(ReadingCheckin.created_at.desc()).limit(6)).all()
    return {
        "activePlanCount": active_plan_count,
        "todayCheckinCount": today_checkin_count,
        "totalCheckinCount": total_checkin_count,
        "defaultChildRewardBalance": balance,
        "recentCheckins": [checkin_to_dict(db, item) for item in recent],
    }
