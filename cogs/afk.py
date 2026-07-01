import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import AFKDB_PATH
from beacon import ViewPaginator, PrivateView
from utils.data_handlers import export_table
from utils.data_protocol import DataDeleteResult, DataExportChunk, DataFeatureMeta, DataMonitorResult

AFK_BUFFER_SECONDS = 30
AFK_MAX_SECONDS = 72 * 60 * 60


@dataclass
class AFKState:
    user_id: int
    status: Optional[str]
    is_global: bool
    save_missed_pings: bool
    started_at: int
    buffer_until: int
    origin_guild_id: Optional[int]
    old_nick: Optional[str]


@dataclass
class MissedPing:
    id: int
    user_id: int
    author_id: int
    guild_id: Optional[int]
    channel_id: Optional[int]
    message_id: Optional[int]
    content: str
    timestamp: int


class ViewMissedPings(PrivateView):
    def __init__(self, cog: "AFK", user_id: int, user: discord.User):
        super().__init__(user, timeout=None)
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="View Missed Pings", style=discord.ButtonStyle.primary)
    async def view_missed_pings(self, interaction: discord.Interaction, button: discord.ui.Button):

        entries = self.cog.missed_pings_cache.get(self.user_id, [])

        if not entries:
            return await interaction.response.send_message("You have no missed pings.", ephemeral=True)

        lines: List[str] = []
        for idx, entry in enumerate(entries, start=1):
            guild = interaction.client.get_guild(entry.guild_id) if entry.guild_id else None
            member = guild.get_member(entry.author_id) if guild else None
            user = member or interaction.client.get_user(entry.author_id) or await interaction.client.fetch_user(
                entry.author_id)
            display_name = user.mention or (user.name if user else f"User {entry.author_id}")
            msg_link = ""
            if entry.guild_id and entry.channel_id and entry.message_id:
                msg_link = f" [[Jump]](<https://discord.com/channels/{entry.guild_id}/{entry.channel_id}/{entry.message_id}>)"

            lines.append(
                f'{idx}. {display_name} in **{guild.name}**'
                f'(<t:{entry.timestamp}:d> <t:{entry.timestamp}:t>): '
                f'"{entry.content}"{msg_link}\n\n'
            )

        paginator = ViewPaginator(
            title=f"{len(entries)} Missed Pings",
            data=lines,
            per_page=5,
            color=discord.Color(0x944ae8),
        )
        try:
            message = await interaction.user.send(
                embed=paginator.format_embed(),
                view=paginator
            )
            link = message.jump_url
            sent = True
        except discord.Forbidden:
            await interaction.response.send_message(
                """I can't DM you the Missed Pings! Please first DM me "hi" so that Discord lets me DM you.""",
                ephemeral=True)
            sent = False

        if sent:
            await interaction.response.send_message(
                f"I sent the Missed Pings to your DMs! [Click here to Jump]({link}).", ephemeral=True)
            await self.cog.clear_missed_pings(self.user_id)


class AFK(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_pool: Optional[asyncio.Queue[aiosqlite.Connection]] = None
        self.afk_users: Dict[int, AFKState] = {}
        self.missed_pings_cache: Dict[int, List[MissedPing]] = {}

    async def cog_load(self):
        await self.init_pools()
        await self.init_db()
        await self.populate_caches()

    async def cog_unload(self):
        if self.db_pool is not None:
            while not self.db_pool.empty():
                try:
                    conn = self.db_pool.get_nowait()
                    await conn.close()
                except (asyncio.QueueEmpty, Exception):
                    break
            self.db_pool = None

    async def create_pooled_connection(self, path: str) -> aiosqlite.Connection:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                conn = await aiosqlite.connect(
                    path,
                    timeout=5,
                    isolation_level=None,
                )
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA foreign_keys=ON")
                await conn.commit()
                return conn
            except Exception:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (2 ** attempt))
                    continue
                raise

    async def init_pools(self, pool_size: int = 5):
        if self.db_pool is None:
            self.db_pool = asyncio.Queue(maxsize=pool_size)
            for _ in range(pool_size):
                conn = await self.create_pooled_connection(AFKDB_PATH)
                await self.db_pool.put(conn)

    @asynccontextmanager
    async def acquire_db(self) -> aiosqlite.Connection:
        assert self.db_pool is not None
        conn = await self.db_pool.get()
        try:
            yield conn
        finally:
            await self.db_pool.put(conn)

    async def init_db(self):
        async with self.acquire_db() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS afk_users (
                    user_id INTEGER PRIMARY KEY,
                    status TEXT,
                    is_global INTEGER DEFAULT 1,
                    role_id INTEGER,
                    save_missed_pings INTEGER DEFAULT 1,
                    started_at INTEGER NOT NULL,
                    buffer_until INTEGER NOT NULL,
                    origin_guild_id INTEGER,
                    old_nick TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS missed_pings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message_id INTEGER,
                    content TEXT,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_missed_pings_user_id ON missed_pings (user_id, timestamp)"
            )
            await db.commit()

    async def populate_caches(self):
        self.afk_users.clear()
        self.missed_pings_cache.clear()

        now = int(discord.utils.utcnow().timestamp())

        async with self.acquire_db() as db:
            async with db.execute(
                    """
                    SELECT user_id, status, is_global, save_missed_pings,
                           started_at, buffer_until, origin_guild_id, old_nick
                    FROM afk_users
                    """
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    (
                        user_id,
                        status,
                        is_global,
                        save_missed_pings,
                        started_at,
                        buffer_until,
                        origin_guild_id,
                        old_nick,
                    ) = row

                    if now - started_at >= AFK_MAX_SECONDS:
                        await db.execute("DELETE FROM afk_users WHERE user_id = ?", (user_id,))
                        continue

                    state = AFKState(
                        user_id=user_id,
                        status=status,
                        is_global=bool(is_global),
                        save_missed_pings=bool(save_missed_pings),
                        started_at=started_at,
                        buffer_until=buffer_until,
                        origin_guild_id=origin_guild_id,
                        old_nick=old_nick,
                    )
                    self.afk_users[user_id] = state

            async with db.execute(
                    """
                    SELECT id, user_id, author_id, guild_id, channel_id,
                           message_id, content, timestamp
                    FROM missed_pings
                    ORDER BY timestamp ASC
                    """
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    (
                        mp_id,
                        user_id,
                        author_id,
                        guild_id,
                        channel_id,
                        message_id,
                        content,
                        timestamp,
                    ) = row
                    entry = MissedPing(
                        id=mp_id,
                        user_id=user_id,
                        author_id=author_id,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=message_id,
                        content=content or "*No message content*",
                        timestamp=timestamp,
                    )
                    self.missed_pings_cache.setdefault(user_id, []).append(entry)

    async def set_afk(
            self,
            *,
            user: discord.Member,
            status: Optional[str],
            is_global: bool,
            save_missed_pings: bool,
    ):
        now = int(discord.utils.utcnow().timestamp())
        buffer_until = now + AFK_BUFFER_SECONDS

        old_nick = user.nick
        origin_guild_id = user.guild.id if isinstance(user.guild, discord.Guild) else None

        try:
            new_nick = f"[AFK] {user.display_name}"
            if len(new_nick) <= 32:
                await user.edit(nick=new_nick, reason="AFK enabled")
        except (discord.Forbidden, discord.HTTPException):
            pass

        state = AFKState(
            user_id=user.id,
            status=status,
            is_global=is_global,
            save_missed_pings=save_missed_pings,
            started_at=now,
            buffer_until=buffer_until,
            origin_guild_id=origin_guild_id,
            old_nick=old_nick,
        )

        self.afk_users[user.id] = state

        async with self.acquire_db() as db:
            await db.execute(
                """
                INSERT INTO afk_users (
                    user_id, status, is_global,
                    save_missed_pings, started_at, buffer_until,
                    origin_guild_id, old_nick
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    status = excluded.status,
                    is_global = excluded.is_global,
                    save_missed_pings = excluded.save_missed_pings,
                    started_at = excluded.started_at,
                    buffer_until = excluded.buffer_until,
                    origin_guild_id = excluded.origin_guild_id,
                    old_nick = excluded.old_nick
                """,
                (
                    user.id,
                    status,
                    int(is_global),
                    int(save_missed_pings),
                    now,
                    buffer_until,
                    origin_guild_id,
                    old_nick,
                ),
            )
            await db.commit()

    async def clear_afk(self, user_id: int, revert_nick: bool = True):
        state = self.afk_users.pop(user_id, None)

        if revert_nick and state and state.origin_guild_id:
            guild = self.bot.get_guild(state.origin_guild_id)
            if guild:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                if member:
                    try:
                        await member.edit(nick=state.old_nick, reason="AFK ended")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        async with self.acquire_db() as db:
            await db.execute("DELETE FROM afk_users WHERE user_id = ?", (user_id,))
            await db.commit()

    async def clear_missed_pings(self, user_id: int):
        self.missed_pings_cache.pop(user_id, None)
        async with self.acquire_db() as db:
            await db.execute("DELETE FROM missed_pings WHERE user_id = ?", (user_id,))
            await db.commit()

    def _format_afk_notice(self, member: discord.Member, state: AFKState) -> str:
        now = int(discord.utils.utcnow().timestamp())
        elapsed = max(0, now - state.started_at)

        if elapsed < 60:
            ago = "A few seconds ago"
        elif elapsed < 3600:
            minutes = elapsed // 60
            ago = f"{minutes} minutes ago"
        else:
            hours = elapsed // 3600
            ago = f"{hours} hours ago"

        if state.status:
            return f"{member.display_name} is AFK: {state.status} - {ago}"
        return f"{member.display_name} is AFK - {ago}"

    def _format_welcome_back(self, state: AFKState, missed_count: int) -> str:
        now = int(discord.utils.utcnow().timestamp())
        elapsed = max(0, now - state.started_at)

        if elapsed < 60:
            base = "Welcome back! You were AFK for less than a minute!"
        elif elapsed < 3600:
            minutes = elapsed // 60
            base = f"Welcome back! You were AFK for **{minutes}** minutes!"
        else:
            hours, remainder = divmod(elapsed, 3600)
            minutes = remainder // 60

            if minutes > 0:
                base = f"Welcome back! You were AFK for **{hours}** hours and **{minutes}** minutes!"
            else:
                base = f"Welcome back! You were AFK for **{hours}** hours!"

        if missed_count > 0 and state.save_missed_pings:
            base += f"\nYou have **{missed_count}** missed pings!"

        return base

    def _is_afk_active_in_context(self, state: AFKState, guild: Optional[discord.Guild]) -> bool:
        now = int(discord.utils.utcnow().timestamp())
        if now - state.started_at >= AFK_MAX_SECONDS:
            return False
        if not state.is_global and guild and state.origin_guild_id:
            return guild.id == state.origin_guild_id
        return True

    async def _maybe_cleanup_if_expired(self, user_id: int, state: AFKState) -> bool:
        now = int(discord.utils.utcnow().timestamp())
        if now - state.started_at >= AFK_MAX_SECONDS:
            await self.clear_afk(user_id, revert_nick=True)
            return True
        return False

    @commands.command(name="afk")
    async def prefix_afk(self, ctx: commands.Context, *, status: Optional[str] = None):
        if not isinstance(ctx.author, discord.Member):
            return

        state = self.afk_users.get(ctx.author.id)
        if state:
            return await ctx.send("You're already AFK!", delete_after=10)

        await self.set_afk(
            user=ctx.author,
            status=status,
            is_global=True,
            save_missed_pings=True,
        )
        reply = f"{ctx.author.mention} you're now AFK: {status}" if status else f"{ctx.author.mention} you're now AFK!"
        await ctx.send(reply)

    @app_commands.command(name="afk", description="Set or update your AFK status.")
    @app_commands.describe(
        status="Optional AFK status message.",
        global_mentions="Whether mentions in all servers should trigger AFK responses instead of only the current server.",
        save_missed_pings="Whether to save messages where you are mentioned and show them when you're back.",
    )
    async def slash_afk(
            self,
            interaction: discord.Interaction,
            status: Optional[str] = None,
            global_mentions: Optional[bool] = True,
            save_missed_pings: Optional[bool] = True,
    ):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("AFK can only be used in servers.", ephemeral=True)

        state = self.afk_users.get(interaction.user.id)
        if state:
            return await interaction.response.send_message("You're already AFK!", ephemeral=True)

        is_global = bool(global_mentions) if global_mentions is not None else True
        save_mp = bool(save_missed_pings) if save_missed_pings is not None else True

        await self.set_afk(
            user=interaction.user,
            status=status,
            is_global=is_global,
            save_missed_pings=save_mp,
        )

        reply = f"{interaction.user.mention} you're now AFK: {status}" if status else f"{interaction.user.mention} you're now AFK!"
        await interaction.response.send_message(
            reply
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        user_id = message.author.id
        state = self.afk_users.get(user_id)

        if state and self._is_afk_active_in_context(state, message.guild):
            now = int(discord.utils.utcnow().timestamp())
            if await self._maybe_cleanup_if_expired(user_id, state):
                return

            if now >= state.buffer_until:
                missed = self.missed_pings_cache.get(user_id, [])
                content = self._format_welcome_back(state, len(missed))
                view = ViewMissedPings(self, user_id, message.author) if missed and state.save_missed_pings else None

                try:
                    await message.reply(content, view=view, mention_author=False)
                except (discord.Forbidden, discord.HTTPException):
                    pass

                await self.clear_afk(user_id, revert_nick=True)
                return

        if message.guild is None:
            return

        for mentioned in message.mentions:
            if mentioned.bot:
                continue

            state = self.afk_users.get(mentioned.id)
            if not state:
                continue

            if await self._maybe_cleanup_if_expired(mentioned.id, state):
                continue

            if not self._is_afk_active_in_context(state, message.guild):
                continue

            if state.save_missed_pings:
                await self._store_missed_ping(
                    user_id=mentioned.id,
                    author_id=message.author.id,
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                    content=message.content or "*No message content*",
                    timestamp=int(message.created_at.timestamp()),
                )

            notice = self._format_afk_notice(mentioned, state)
            try:
                await message.channel.send(notice)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if message.role_mentions:
            for role in message.role_mentions:
                for uid, state in list(self.afk_users.items()):
                    if await self._maybe_cleanup_if_expired(uid, state):
                        continue

                    if not self._is_afk_active_in_context(state, message.guild):
                        continue

                    member = message.guild.get_member(uid)
                    if not member or role not in member.roles:
                        continue

                    await self._store_missed_ping(
                        user_id=uid,
                        author_id=message.author.id,
                        guild_id=message.guild.id,
                        channel_id=message.channel.id,
                        message_id=message.id,
                        content=message.content or "*No message content*",
                        timestamp=int(message.created_at.timestamp()),
                    )

                    if len(role.members) <= 3:
                        notice = self._format_afk_notice(member, state)
                        try:
                            await message.channel.send(notice)
                        except (discord.Forbidden, discord.HTTPException):
                            pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        message_id = payload.message_id

        for user_id, entries in self.missed_pings_cache.items():
            for entry in entries:
                if entry.message_id == message_id:
                    entry.content = "*[This message was deleted]*"

        async with self.acquire_db() as db:
            await db.execute(
                "UPDATE missed_pings SET content = ? WHERE message_id = ?",
                ("[This message was deleted]", message_id),
            )
            await db.commit()

    async def _store_missed_ping(
            self,
            *,
            user_id: int,
            author_id: int,
            guild_id: Optional[int],
            channel_id: Optional[int],
            message_id: Optional[int],
            content: str,
            timestamp: int,
    ):
        async with self.acquire_db() as db:
            cursor = await db.execute(
                """
                INSERT INTO missed_pings (
                    user_id, author_id, guild_id, channel_id,
                    message_id, content, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    author_id,
                    guild_id,
                    channel_id,
                    message_id,
                    content or "*No message content*",
                    timestamp,
                ),
            )
            await db.commit()
            mp_id = cursor.lastrowid

        entry = MissedPing(
            id=mp_id,
            user_id=user_id,
            author_id=author_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            content=content or "*No message content*",
            timestamp=timestamp,
        )
        self.missed_pings_cache.setdefault(user_id, []).append(entry)

    def data_features(self) -> list[DataFeatureMeta]:
        return [DataFeatureMeta(
            feature_id="afk",
            name="AFK",
            user_export=True,
            user_delete=True,
        )]

    async def data_export_user(self, user_id: int, *, guild_ids: list[int] | None) -> DataExportChunk:
        chunk = DataExportChunk(feature_id="afk")
        async with self.acquire_db() as db:
            afk_rows = await export_table(
                db,
                """SELECT user_id, status, is_global, save_missed_pings, started_at,
                          buffer_until, origin_guild_id, old_nick
                   FROM afk_users WHERE user_id = ?""",
                (user_id,),
            )
            missed_rows = await export_table(
                db,
                """SELECT id, user_id, author_id, guild_id, channel_id,
                          message_id, content, timestamp
                   FROM missed_pings WHERE user_id = ? ORDER BY timestamp ASC""",
                (user_id,),
            )
        if afk_rows:
            chunk.global_data["afk_state"] = afk_rows[0]
        if missed_rows:
            chunk.global_data["missed_pings"] = missed_rows
        return chunk

    async def data_export_guild(self, guild_id: int) -> DataExportChunk:
        return DataExportChunk(feature_id="afk")

    async def data_delete_user(self, user_id: int, *, guild_ids: list[int] | None, feature_id: str | None) -> DataDeleteResult:
        if feature_id and feature_id != "afk":
            return DataDeleteResult(feature_id="afk")
        rows_affected = 0
        async with self.acquire_db() as db:
            cur = await db.execute("DELETE FROM afk_users WHERE user_id = ?", (user_id,))
            rows_affected += cur.rowcount
            cur = await db.execute("DELETE FROM missed_pings WHERE user_id = ?", (user_id,))
            rows_affected += cur.rowcount
            await db.commit()
        self.afk_users.pop(user_id, None)
        self.missed_pings_cache.pop(user_id, None)
        return DataDeleteResult(feature_id="afk", deleted=True, rows_affected=rows_affected)

    async def data_delete_guild(self, guild_id: int, feature_id: str | None) -> DataDeleteResult:
        return DataDeleteResult(feature_id="afk")

    async def data_monitor_guild(self, guild: discord.Guild) -> DataMonitorResult:
        return DataMonitorResult(feature_id="afk")


async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))