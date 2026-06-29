"""auth_routes.py - Login/logout and role-gated user management.

Mounted on the app via ``app.include_router(router)`` in main.py. Two groups:

* ``/api/auth/*`` — login (public), logout + me (any authenticated user).
* ``/api/users/*`` — admin reads + creates *normal* users; super_admin does full CRUD and
  password renewal. Passwords are bcrypt-hashed on the way in and never returned.

Guard rails keep at least one active super_admin alive and stop self-deletion.
"""

import logging
import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordResetRequest,
    UserCreate,
    UserList,
    UserPublic,
    UserRole,
    UserUpdate,
)
from app.security import (
    get_current_user,
    hash_password,
    new_token,
    require_admin,
    require_super_admin,
    token_expiry_iso,
    verify_password,
)

log = logging.getLogger("aisha.auth")
router = APIRouter(tags=["auth"])


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@router.post("/api/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    user = db.get_user_by_username(body.username)
    # One generic message whether the user is missing, disabled, or the password is wrong.
    if (not user or not user.get("is_active")
            or not verify_password(body.password, user["password_hash"])):
        raise HTTPException(401, "Invalid username or password.")

    raw, th = new_token()
    expires = token_expiry_iso()
    db.insert_auth_session(th, user["id"], expires)
    db.set_last_login(user["id"])
    log.info("Login: %s (%s)", user["username"], user["role"])
    return LoginResponse(token=raw, expires_at=expires, user=UserPublic(**user))


@router.post("/api/auth/logout")
def logout(current: dict = Depends(get_current_user)):
    db.delete_auth_session(current["_auth_token_hash"])
    return {"ok": True}


@router.get("/api/auth/me", response_model=UserPublic)
def me(current: dict = Depends(get_current_user)):
    return UserPublic(**current)


# --------------------------------------------------------------------------- #
# User management
# --------------------------------------------------------------------------- #
@router.get("/api/users", response_model=UserList)
def list_users(page: int = 1, limit: int = 20, search: str = None, role: str = None,
               _: dict = Depends(require_admin)):
    results, total = db.list_users(page=page, limit=limit, search=search, role=role)
    return UserList(count=total, page=page, limit=limit, results=results)


@router.get("/api/users/{user_id}", response_model=UserPublic)
def get_user(user_id: str, _: dict = Depends(require_admin)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    return UserPublic(**user)


@router.post("/api/users", response_model=UserPublic, status_code=201)
def create_user(body: UserCreate, current: dict = Depends(require_admin)):
    # Admins can only mint normal users; super_admins may assign any role.
    role = body.role if current["role"] == "super_admin" else UserRole.user
    if db.get_user_by_username(body.username):
        raise HTTPException(409, "That username is already taken.")

    uid = uuid.uuid4().hex
    try:
        db.insert_user({
            "id": uid,
            "username": body.username,
            "password_hash": hash_password(body.password),
            "role": role.value,
            "created_by": current["id"],
        })
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is already taken.")
    log.info("User created: %s (%s) by %s", body.username, role.value, current["username"])
    return UserPublic(**db.get_user_by_id(uid))


@router.patch("/api/users/{user_id}", response_model=UserPublic)
def update_user(user_id: str, body: UserUpdate, current: dict = Depends(require_super_admin)):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found.")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return UserPublic(**target)

    _guard_last_super_admin(target, changes)

    new_username = changes.get("username")
    if new_username and new_username.lower() != target["username"].lower():
        if db.get_user_by_username(new_username):
            raise HTTPException(409, "That username is already taken.")
    if isinstance(changes.get("role"), UserRole):
        changes["role"] = changes["role"].value

    try:
        db.update_user(user_id, **changes)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is already taken.")
    # Disabling an account immediately invalidates its active sessions.
    if changes.get("is_active") is False:
        db.delete_auth_sessions_for_user(user_id)
    log.info("User updated: %s by %s (%s)", target["username"], current["username"],
             ", ".join(changes))
    return UserPublic(**db.get_user_by_id(user_id))


@router.delete("/api/users/{user_id}")
def delete_user(user_id: str, current: dict = Depends(require_super_admin)):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if user_id == current["id"]:
        raise HTTPException(400, "You can't delete your own account.")
    if (target["role"] == "super_admin" and target["is_active"]
            and db.count_active_super_admins() <= 1):
        raise HTTPException(400, "You can't delete the last active super admin.")

    db.delete_user(user_id)  # auth_sessions cascade via FK
    log.info("User deleted: %s by %s", target["username"], current["username"])
    return {"deleted": user_id}


@router.post("/api/users/{user_id}/password")
def reset_password(user_id: str, body: PasswordResetRequest,
                   current: dict = Depends(require_super_admin)):
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    db.set_password_hash(user_id, hash_password(body.new_password))
    db.delete_auth_sessions_for_user(user_id)  # force re-login with the new password
    log.info("Password reset: %s by %s", target["username"], current["username"])
    return {"ok": True, "user_id": user_id}


def _guard_last_super_admin(target: dict, changes: dict) -> None:
    """Block demoting or disabling the only remaining active super_admin."""
    if target["role"] != "super_admin" or not target["is_active"]:
        return
    new_role = changes.get("role")
    demoting = new_role is not None and new_role not in (UserRole.super_admin, "super_admin")
    deactivating = changes.get("is_active") is False
    if (demoting or deactivating) and db.count_active_super_admins() <= 1:
        raise HTTPException(400, "You can't remove the last active super admin.")
