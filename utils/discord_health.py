from __future__ import annotations

from typing import Optional, Tuple

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


async def resolve_guild(
    bot, guild_id: int, *, feature_id: str, detail: str = "guild_unreachable"
) -> Optional[discord.Guild]:
    guild = bot.get_guild(guild_id)
    if guild is not None:
        return guild
    try:
        return await bot.fetch_guild(guild_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        if is_access_error(exc):
            await report_access_failure(bot, guild_id, feature_id, detail)
        return None


async def resolve_guild_channel(
    bot,
    guild_id: int,
    channel_id: int,
    *,
    feature_id: str,
    detail: str = "",
) -> Tuple[Optional[discord.Guild], Optional[discord.abc.GuildChannel]]:
    guild = await resolve_guild(bot, guild_id, feature_id=feature_id, detail=detail or "guild_unreachable")
    if guild is None:
        return None, None

    channel = guild.get_channel(channel_id)
    if channel is not None:
        return guild, channel

    try:
        fetched = await bot.fetch_channel(channel_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        if is_access_error(exc):
            await report_access_failure(
                bot, guild_id, feature_id, detail or f"channel:{channel_id}"
            )
        return guild, None

    if isinstance(fetched, discord.abc.GuildChannel) and fetched.guild.id == guild.id:
        return guild, fetched

    await report_access_failure(bot, guild_id, feature_id, detail or f"channel:{channel_id}")
    return guild, None


def channel_can_send(channel: discord.abc.GuildChannel, guild: discord.Guild) -> bool:
    perms = channel.permissions_for(guild.me)
    return perms.view_channel and perms.send_messages
