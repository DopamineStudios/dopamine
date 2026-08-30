from __future__ import annotations
from typing import Any, Optional, List
from utils.database import DatabaseManager

async def get_mod_config(db: DatabaseManager, guild_id: int) -> dict[str, Any]:
    await db.wait_ready()
    rows = await db.execute(
        "SELECT * FROM moderation_settings WHERE guild_id = ?",
        (guild_id,)
    )
    if not rows:
        return {
            "guild_id": guild_id,
            "punishment_dm": 1,
            "punishment_log": 1,
            "decay_interval": 14,
            "rejoin_points": 4,
            "simple_mode": 1,
            "msg_report_enabled": 0,
            "msg_report_channel": None,
            "msg_report_roles": None,
            "decay_log_enabled": 0,
            "show_medals": 1
        }
    return dict(rows[0])

async def update_mod_config(
    db: DatabaseManager,
    guild_id: int,
    **kwargs: Any
) -> None:
    await db.wait_ready()
    await db.execute_write(
        "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
        (guild_id,)
    )
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(guild_id)
    sql = f"UPDATE moderation_settings SET {', '.join(fields)} WHERE guild_id = ?"
    await db.execute_write(sql, tuple(values))

async def get_guild_actions(db: DatabaseManager, guild_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id, guild_id, action_type, duration, points FROM actions WHERE guild_id = ?",
        (guild_id,)
    )

async def add_guild_action(db: DatabaseManager, guild_id: int, action_type: str, duration: int, points: int) -> int:
    await db.wait_ready()
    rows = await db.execute(
        "INSERT INTO actions (guild_id, action_type, duration, points) VALUES (?, ?, ?, ?) RETURNING id",
        (guild_id, action_type, duration, points)
    )
    return int(rows[0]["id"]) if rows else 0

async def update_guild_action(db: DatabaseManager, action_id: int, guild_id: int, points: int) -> int:
    await db.wait_ready()
    return await db.execute_write(
        "UPDATE actions SET points = ? WHERE id = ? AND guild_id = ?",
        (points, action_id, guild_id)
    )

async def delete_guild_action(db: DatabaseManager, action_id: int) -> None:
    await db.wait_ready()
    await db.execute_write("DELETE FROM actions WHERE id = ?", (action_id,))

async def delete_all_actions(db: DatabaseManager, guild_id: int) -> None:
    await db.wait_ready()
    await db.execute_write("DELETE FROM actions WHERE guild_id = ?", (guild_id,))

async def get_all_infractions(db: DatabaseManager, guild_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id, guild_id, case_number, user_id, moderator_id, amount, reason, punishment_type, punishment_duration, points_after, created_at FROM infractions WHERE guild_id = ? ORDER BY created_at DESC",
        (guild_id,)
    )

async def get_user_infractions(db: DatabaseManager, guild_id: int, user_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id, guild_id, case_number, user_id, moderator_id, amount, reason, punishment_type, punishment_duration, points_after, created_at FROM infractions WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
        (guild_id, user_id)
    )

async def get_infraction(db: DatabaseManager, guild_id: int, case_number: int) -> Optional[dict[str, Any]]:
    await db.wait_ready()
    rows = await db.execute(
        "SELECT id, guild_id, case_number, user_id, moderator_id, amount, reason, punishment_type, punishment_duration, points_after, created_at FROM infractions WHERE guild_id = ? AND case_number = ?",
        (guild_id, case_number)
    )
    return rows[0] if rows else None

async def next_case_number(db: DatabaseManager, guild_id: int) -> int:
    await db.wait_ready()
    rows = await db.execute(
        "SELECT COALESCE(MAX(case_number), 0) + 1 AS next_num FROM infractions WHERE guild_id = ?",
        (guild_id,)
    )
    return rows[0]["next_num"] if rows else 1

async def record_infraction(
    db: DatabaseManager,
    guild_id: int,
    user_id: int,
    moderator_id: int,
    amount: int,
    reason: Optional[str],
    punishment_type: Optional[str],
    punishment_duration: int,
    points_after: int,
    created_at: int
) -> int:
    await db.wait_ready()
    case_number = await next_case_number(db, guild_id)
    await db.execute_write(
        """INSERT INTO infractions
           (guild_id, case_number, user_id, moderator_id, amount, reason,
            punishment_type, punishment_duration, points_after, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (guild_id, case_number, user_id, moderator_id, amount, reason,
         punishment_type, punishment_duration, points_after, created_at)
    )
    return case_number

async def delete_infraction(db: DatabaseManager, guild_id: int, case_number: int) -> bool:
    await db.wait_ready()
    rowcount = await db.execute_write(
        "DELETE FROM infractions WHERE guild_id = ? AND case_number = ?",
        (guild_id, case_number)
    )
    return rowcount > 0

async def get_user_data(db: DatabaseManager, guild_id: int, user_id: int) -> dict[str, Any]:
    await db.wait_ready()
    rows = await db.execute(
        "SELECT guild_id, user_id, points, last_punishment, last_decay, total_decayed FROM moderation_users WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    )
    if not rows:
        await db.execute_write(
            "INSERT OR IGNORE INTO moderation_users (guild_id, user_id, points, total_decayed) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, 0, 0)
        )
        return {"points": 0, "last_punishment": None, "last_decay": None, "total_decayed": 0}
    return dict(rows[0])

async def update_user_points(
    db: DatabaseManager,
    guild_id: int,
    user_id: int,
    points: int,
    punishment_ts: Optional[int] = None,
    total_decayed: Optional[int] = None,
    last_decay: Optional[int] = None
) -> None:
    await db.wait_ready()
    current = await get_user_data(db, guild_id, user_id)
    new_punishment = punishment_ts if punishment_ts is not None else current.get("last_punishment")
    new_decay = last_decay if last_decay is not None else current.get("last_decay")
    if punishment_ts is not None:
        new_decay = None
    new_total_decayed = total_decayed if total_decayed is not None else current.get("total_decayed", 0)

    await db.execute_write(
        """UPDATE moderation_users
           SET points = ?, last_punishment = ?, last_decay = ?, total_decayed = ?
           WHERE guild_id = ? AND user_id = ?""",
        (points, new_punishment, new_decay, new_total_decayed, guild_id, user_id)
    )

async def get_guild_active_users(db: DatabaseManager, guild_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT user_id, points, last_punishment, last_decay FROM moderation_users WHERE guild_id = ? AND points > 0",
        (guild_id,)
    )

async def get_pending_punishments(db: DatabaseManager, guild_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id, user_id, moderator_id, reason, created_at, timeout_until FROM pending_punishments WHERE guild_id = ? ORDER BY created_at DESC",
        (guild_id,)
    )

async def add_pending_punishment(
    db: DatabaseManager,
    guild_id: int,
    user_id: int,
    moderator_id: int,
    reason: str,
    created_at: int,
    timeout_until: int
) -> int:
    await db.wait_ready()
    rows = await db.execute(
        "INSERT INTO pending_punishments (guild_id, user_id, moderator_id, reason, created_at, timeout_until) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (guild_id, user_id, moderator_id, reason, created_at, timeout_until)
    )
    return int(rows[0]["id"]) if rows else 0

async def remove_pending_punishment(db: DatabaseManager, guild_id: int, pending_id: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "DELETE FROM pending_punishments WHERE guild_id = ? AND id = ?",
        (guild_id, pending_id)
    )

async def is_user_pending(db: DatabaseManager, guild_id: int, user_id: int) -> bool:
    await db.wait_ready()
    rows = await db.execute(
        "SELECT 1 FROM pending_punishments WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    )
    return len(rows) > 0

async def add_ban_schedule(db: DatabaseManager, guild_id: int, user_id: int, unban_at: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "INSERT OR REPLACE INTO ban_schedule (guild_id, user_id, unban_at) VALUES (?, ?, ?)",
        (guild_id, user_id, unban_at)
    )

async def remove_ban_schedule(db: DatabaseManager, guild_id: int, user_id: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "DELETE FROM ban_schedule WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    )

async def get_expired_bans(db: DatabaseManager, now: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT guild_id, user_id FROM ban_schedule WHERE unban_at <= ?",
        (now,)
    )

async def get_all_moderation_users(db: DatabaseManager) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT guild_id, user_id, points, last_punishment, last_decay, total_decayed FROM moderation_users"
    )

async def get_all_moderation_settings(db: DatabaseManager) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT guild_id, punishment_dm, punishment_log, decay_interval, rejoin_points, simple_mode, msg_report_enabled, msg_report_channel, msg_report_roles, decay_log_enabled, show_medals FROM moderation_settings"
    )

async def get_all_actions_global(db: DatabaseManager) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id, guild_id, action_type, duration, points FROM actions"
    )

async def apply_default_actions(db: DatabaseManager, guild_id: int) -> None:
    await db.wait_ready()
    rows = await db.execute("SELECT 1 FROM actions WHERE guild_id = ? LIMIT 1", (guild_id,))
    if not rows:
        default_actions = [
            ("warning", 0, 1),
            ("timeout", 3600, 2),
            ("ban", 43200, 3),
            ("ban", 604800, 4),
            ("ban", 0, 5)
        ]
        async with db.acquire_db() as conn:
            for a, d, p in default_actions:
                await conn.execute(
                    "INSERT INTO actions (guild_id, action_type, duration, points) VALUES (?, ?, ?, ?)",
                    (guild_id, a, d, p)
                )
            await conn.commit()

async def ensure_mod_config(db: DatabaseManager, guild_id: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
        (guild_id,)
    )

async def disable_msg_report(db: DatabaseManager, guild_id: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "UPDATE moderation_settings SET msg_report_enabled = 0 WHERE guild_id = ?",
        (guild_id,)
    )

async def get_pending_by_user(db: DatabaseManager, guild_id: int, user_id: int) -> List[dict[str, Any]]:
    await db.wait_ready()
    return await db.execute(
        "SELECT id FROM pending_punishments WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    )

async def update_msg_report_enabled(db: DatabaseManager, guild_id: int, enabled: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "UPDATE moderation_settings SET msg_report_enabled = ? WHERE guild_id = ?",
        (enabled, guild_id)
    )

async def update_msg_report_channel(db: DatabaseManager, guild_id: int, channel_id: Optional[int]) -> None:
    await db.wait_ready()
    await db.execute_write(
        "UPDATE moderation_settings SET msg_report_channel = ? WHERE guild_id = ?",
        (channel_id, guild_id)
    )

async def update_msg_report_roles(db: DatabaseManager, guild_id: int, roles: Optional[str]) -> None:
    await db.wait_ready()
    await db.execute_write(
        "UPDATE moderation_settings SET msg_report_roles = ? WHERE guild_id = ?",
        (roles, guild_id)
    )

async def reset_actions_for_simple_mode(db: DatabaseManager, guild_id: int, simple_mode: int, preset_actions: List[tuple]) -> None:
    await db.wait_ready()
    async with db.acquire_db() as conn:
        await conn.execute("DELETE FROM actions WHERE guild_id = ?", (guild_id,))
        for a, d, p in preset_actions:
            await conn.execute(
                "INSERT INTO actions (guild_id, action_type, duration, points) VALUES (?, ?, ?, ?)",
                (guild_id, a, d, p)
            )
        await conn.execute(
            "UPDATE moderation_settings SET simple_mode = ? WHERE guild_id = ?",
            (simple_mode, guild_id)
        )
        await conn.commit()

async def remove_pending_by_id(db: DatabaseManager, pending_id: int) -> None:
    await db.wait_ready()
    await db.execute_write("DELETE FROM pending_punishments WHERE id = ?", (pending_id,))

async def remove_ban_schedule_record(db: DatabaseManager, guild_id: int, user_id: int) -> None:
    await db.wait_ready()
    await db.execute_write(
        "DELETE FROM ban_schedule WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    )


