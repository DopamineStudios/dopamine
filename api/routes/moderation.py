from __future__ import annotations
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from api.auth import verify_discord_admin, AuthUser
from utils.queries.moderation import (
    get_mod_config,
    update_mod_config,
    get_guild_actions,
    add_guild_action,
    update_guild_action,
    delete_guild_action,
    get_all_infractions,
    get_user_infractions,
    get_infraction,
    delete_infraction,
    get_pending_punishments,
    remove_pending_punishment
)

router = APIRouter(prefix="/api/moderation", tags=["Moderation Dashboard"])

class ModConfigPayload(BaseModel):
    punishment_dm: Optional[int] = None
    punishment_log: Optional[int] = None
    decay_interval: Optional[int] = None
    rejoin_points: Optional[int] = None
    simple_mode: Optional[int] = None
    msg_report_enabled: Optional[bool | int] = None
    msg_report_channel: Optional[int] = None
    msg_report_roles: Optional[str] = None
    decay_log_enabled: Optional[int] = None
    show_medals: Optional[int] = None

    @field_validator("msg_report_enabled", mode="before")
    @classmethod
    def convert_bool_to_int(cls, v: Any) -> Optional[int]:
        if isinstance(v, bool):
            return 1 if v else 0
        return v

class ModConfigResponse(BaseModel):
    guild_id: int
    punishment_dm: int = 1
    punishment_log: int = 1
    decay_interval: int = 14
    rejoin_points: int = 4
    simple_mode: int = 1
    msg_report_enabled: int = 0
    msg_report_channel: int | None = None
    msg_report_roles: str | None = None
    decay_log_enabled: int = 0
    show_medals: int = 1

class ModConfigSaveResponse(BaseModel):
    status: str
    guild_id: int
    updated_by: int

class ActionCreateResponse(BaseModel):
    status: str
    action_id: int
    guild_id: int

class ActionCreatePayload(BaseModel):
    action_type: str
    duration: int = Field(default=0, ge=0)
    points: int = Field(ge=1)

class ActionUpdatePayload(BaseModel):
    points: int = Field(ge=1)

@router.get("/{guild_id}", response_model=ModConfigResponse)
@router.get("/{guild_id}/config", response_model=ModConfigResponse)
async def fetch_config(
    request: Request,
    guild_id: int, 
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    return await get_mod_config(db, guild_id)

@router.post("/{guild_id}", response_model=ModConfigSaveResponse)
@router.patch("/{guild_id}/config", response_model=ModConfigSaveResponse)
async def save_config(
    request: Request,
    guild_id: int, 
    payload: ModConfigPayload, 
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    data = payload.model_dump(exclude_unset=True)
    if "msg_report_enabled" in data and isinstance(data["msg_report_enabled"], bool):
        data["msg_report_enabled"] = 1 if data["msg_report_enabled"] else 0
    await update_mod_config(db, guild_id, **data)
    return {"status": "success", "guild_id": guild_id, "updated_by": auth.user_id}

@router.get("/{guild_id}/actions", response_model=List[dict[str, Any]])
async def fetch_actions(
    request: Request,
    guild_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    return await get_guild_actions(db, guild_id)

@router.post("/{guild_id}/actions", response_model=ActionCreateResponse)
async def create_action(
    request: Request,
    guild_id: int,
    payload: ActionCreatePayload,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    action_id = await add_guild_action(db, guild_id, payload.action_type, payload.duration, payload.points)
    return {"status": "success", "action_id": action_id, "guild_id": guild_id}

@router.patch("/{guild_id}/actions/{action_id}", response_model=dict[str, str])
async def modify_action(
    request: Request,
    guild_id: int,
    action_id: int,
    payload: ActionUpdatePayload,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    rowcount = await update_guild_action(db, action_id, guild_id, payload.points)
    if rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found.")
    return {"status": "success"}

@router.delete("/{guild_id}/actions/{action_id}", response_model=dict[str, str])
async def remove_action(
    request: Request,
    guild_id: int,
    action_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    await delete_guild_action(db, action_id)
    return {"status": "success"}

@router.get("/{guild_id}/infractions", response_model=List[dict[str, Any]])
async def fetch_all_infractions(
    request: Request,
    guild_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    return await get_all_infractions(db, guild_id)

@router.get("/{guild_id}/infractions/user/{user_id}", response_model=List[dict[str, Any]])
async def fetch_user_infractions(
    request: Request,
    guild_id: int,
    user_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    return await get_user_infractions(db, guild_id, user_id)

@router.delete("/{guild_id}/infractions/{case_number}", response_model=dict[str, str])
async def remove_infraction(
    request: Request,
    guild_id: int,
    case_number: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    success = await delete_infraction(db, guild_id, case_number)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    return {"status": "success"}

@router.get("/{guild_id}/pending", response_model=List[dict[str, Any]])
async def fetch_pending_punishments(
    request: Request,
    guild_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    return await get_pending_punishments(db, guild_id)

@router.delete("/{guild_id}/pending/{pending_id}", response_model=dict[str, str])
async def remove_pending(
    request: Request,
    guild_id: int,
    pending_id: int,
    auth: AuthUser = Depends(verify_discord_admin)
):
    db = request.app.state.db
    await remove_pending_punishment(db, guild_id, pending_id)
    return {"status": "success"}
