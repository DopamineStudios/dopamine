"""Shared export/delete/monitor SQL helpers for the data management system."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from utils.data_protocol import DataDeleteResult, DataExportChunk, DataFeatureMeta, DataMonitorResult


def _rows_to_dicts(cursor, rows) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


async def export_table(db, query: str, params=()) -> list[dict]:
    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()
        if not cur.description:
            return []
        return _rows_to_dicts(cur, rows)


async def export_usage_user(db, user_id: int, guild_ids: Optional[list[int]]) -> DataExportChunk:
    chunk = DataExportChunk(feature_id="usage")
    if guild_ids is None:
        q = "SELECT date, guild_id, feature_id, command_name, count FROM usage_daily WHERE user_id = ?"
        params = (user_id,)
    else:
        placeholders = ",".join("?" * len(guild_ids))
        q = f"SELECT date, guild_id, feature_id, command_name, count FROM usage_daily WHERE user_id = ? AND (guild_id IS NULL OR guild_id IN ({placeholders}))"
        params = (user_id, *guild_ids)
    rows = await export_table(db, q, params)
    for row in rows:
        gid = row.pop("guild_id")
        if gid is None:
            chunk.global_data.setdefault("records", []).append(row)
        else:
            chunk.guild_data.setdefault(gid, {}).setdefault("records", []).append(row)
    return chunk


async def export_usage_guild(db, guild_id: int) -> DataExportChunk:
    chunk = DataExportChunk(feature_id="usage")
    rows = await export_table(
        db,
        "SELECT date, user_id, feature_id, command_name, count FROM usage_daily WHERE guild_id = ?",
        (guild_id,),
    )
    chunk.guild_data[guild_id] = {"records": rows}
    return chunk


async def delete_usage_user(db, user_id: int, guild_ids: Optional[list[int]]) -> DataDeleteResult:
    if guild_ids is None:
        cur = await db.execute("DELETE FROM usage_daily WHERE user_id = ?", (user_id,))
    else:
        placeholders = ",".join("?" * len(guild_ids))
        cur = await db.execute(
            f"DELETE FROM usage_daily WHERE user_id = ? AND guild_id IN ({placeholders})",
            (user_id, *guild_ids),
        )
    await db.commit()
    return DataDeleteResult(feature_id="usage", deleted=True, rows_affected=cur.rowcount)


async def delete_usage_guild(db, guild_id: int) -> DataDeleteResult:
    cur = await db.execute("DELETE FROM usage_daily WHERE guild_id = ?", (guild_id,))
    await db.commit()
    return DataDeleteResult(feature_id="usage", deleted=True, rows_affected=cur.rowcount)
