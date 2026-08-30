from __future__ import annotations
import aiohttp
from fastapi import Header, HTTPException, status
from pydantic import BaseModel
from cachetools import TTLCache

DISCORD_API_URL = "https://discord.com/api/v10"
REQUIRED_PERMISSIONS = 0x20 | 0x8  # MANAGE_GUILD (0x20) | ADMINISTRATOR (0x8)

auth_cache = TTLCache(maxsize=1024, ttl=60)
_http_session: aiohttp.ClientSession | None = None

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

class AuthUser(BaseModel):
    user_id: int
    guild_id: int

async def verify_discord_admin(
    guild_id: int, 
    authorization: str = Header(...)
) -> AuthUser:
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing or invalid Authorization header format."
        )

    token = parts[1]
    cache_key = (token, guild_id)
    if cache_key in auth_cache:
        return auth_cache[cache_key]

    session = await get_http_session()
    async with session.get(
        f"{DISCORD_API_URL}/users/@me", 
        headers={"Authorization": f"Bearer {token}"}
    ) as resp:
        if resp.status != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid or expired Discord OAuth2 token."
            )
        user_data = await resp.json()
        user_id = int(user_data["id"])

    async with session.get(
        f"{DISCORD_API_URL}/users/@me/guilds", 
        headers={"Authorization": f"Bearer {token}"}
    ) as resp:
        if resp.status != 200:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Failed to retrieve user guilds from Discord."
            )
        guilds = await resp.json()

    target_guild = next((g for g in guilds if int(g["id"]) == guild_id), None)
    
    if not target_guild:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You are not a member of this server."
        )

    is_owner = target_guild.get("owner", False)
    permissions = int(target_guild.get("permissions", 0))
    if not is_owner and not (permissions & REQUIRED_PERMISSIONS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You lack administrative permissions for this server."
        )

    auth_user = AuthUser(user_id=user_id, guild_id=guild_id)
    auth_cache[cache_key] = auth_user
    return auth_user
