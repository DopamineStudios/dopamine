from __future__ import annotations

import discord

ACCESS_ERROR_CODES = {50001, 50007, 50013, 10003, 10004, 10008}


def is_access_error(exc: BaseException) -> bool:
    if isinstance(exc, discord.Forbidden):
        return True
    if isinstance(exc, discord.NotFound):
        return True
    if isinstance(exc, discord.HTTPException):
        if exc.status == 403:
            return True
        if exc.code in ACCESS_ERROR_CODES:
            return True
    return False


async def report_access_failure(bot, guild_id: int, feature_id: str, detail: str = "") -> None:
    cog = bot.get_cog("Data")
    if cog is None:
        return
    await cog.on_feature_access_failure(guild_id, feature_id, detail)
