import asyncio
import io
import logging
import random
import aiosqlite
from datetime import datetime, timedelta, time
import json

import discord
from discord import app_commands, Interaction, TextChannel
from discord.ext import commands, tasks
from beacon import beacon_commands

from config import DDB_PATH
from utils.data_protocol import DataDeleteResult, DataExportChunk, DataFeatureMeta, DataMonitorResult
from utils.discord_health import is_access_error, report_access_failure


class DatabasePool:
    def __init__(self, db_path, size=5):
        self.db_path = db_path
        self.size = size
        self.connections = []
        self._pointer = 0

    async def init(self):
        for _ in range(self.size):
            conn = await aiosqlite.connect(self.db_path)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            self.connections.append(conn)

    def get_connection(self) -> aiosqlite.Connection:
        conn = self.connections[self._pointer]
        self._pointer = (self._pointer + 1) % self.size
        return conn

    async def close(self):
        for conn in self.connections:
            await conn.close()


class DailyCats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_pool = DatabasePool(DDB_PATH)

        self.active_cat_channels = set()
        self.next_send_time = None

        self.init_data.start()

    def cog_unload(self):
        self.init_data.cancel()
        self.daily_task.cancel()

        asyncio.create_task(self.db_pool.close())

        self.active_cat_channels.clear()
        self.active_cat_channels = None
        self.next_send_time = None

    @tasks.loop(count=1)
    async def init_data(self):
        await self.db_pool.init()
        conn = self.db_pool.get_connection()

        await conn.execute(
            "CREATE TABLE IF NOT EXISTS cat_channels (channel_id INTEGER PRIMARY KEY)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS cat_images (id INTEGER PRIMARY KEY AUTOINCREMENT, image_data BLOB)")

        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.commit()

        async with conn.execute("SELECT channel_id FROM cat_channels") as cursor:
            async for row in cursor:
                self.active_cat_channels.add(row[0])

        async with conn.execute("SELECT value FROM settings WHERE key = 'next_send_time'") as cursor:
            row = await cursor.fetchone()
            if row:
                self.next_send_time = datetime.fromisoformat(row[0])
            else:
                now = datetime.now()
                self.next_send_time = datetime.combine(now.date() + timedelta(days=1), time(0, 0))
                await self.save_next_time()

        self.daily_task.start()

    async def save_next_time(self):
        conn = self.db_pool.get_connection()
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ('next_send_time', self.next_send_time.isoformat())
        )
        await conn.commit()

    @commands.command(name="catadd", hidden=True)
    @commands.is_owner()
    async def catadd(self, ctx: commands.Context):
        if not ctx.message.attachments:
            return await ctx.send("Please attach at least one image.")

        valid_types = ['image/png', 'image/jpeg', 'image/gif']
        images_added = 0
        conn = self.db_pool.get_connection()

        for attachment in ctx.message.attachments:
            if attachment.content_type not in valid_types:
                await ctx.send(f"Skipping {attachment.filename}: Not a valid image type (PNG/JPEG/GIF).",
                               delete_after=10)
                continue

            try:
                image_bytes = await attachment.read()

                await conn.execute("INSERT INTO cat_images (image_data) VALUES (?)", (image_bytes,))
                images_added += 1
            except Exception as e:
                await ctx.send(f"Failed to add {attachment.filename}: {e}", delete_after=10)

        await conn.commit()
        await ctx.send(f"Successfully added {images_added} cat pics to the database!", delete_after=10)
        asyncio.sleep(10)
        await ctx.message.delete()

    @tasks.loop(seconds=30)
    async def daily_task(self):
        if not self.next_send_time or not self.active_cat_channels:
            return

        now = datetime.now()
        if now >= self.next_send_time:
            image_blob = None
            conn = self.db_pool.get_connection()
            async with conn.execute("SELECT id FROM cat_images") as cursor:
                ids = [row[0] for row in await cursor.fetchall()]

            if ids:
                random_id = random.choice(ids)
                async with conn.execute("SELECT image_data FROM cat_images WHERE id = ?", (random_id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        image_blob = row[0]

            async def send_to_channel(channel_id):
                guild_id = None
                ch = self.bot.get_channel(channel_id)
                if isinstance(ch, discord.abc.GuildChannel):
                    guild_id = ch.guild.id
                elif ch is None:
                    try:
                        ch = await self.bot.fetch_channel(channel_id)
                        if isinstance(ch, discord.abc.GuildChannel):
                            guild_id = ch.guild.id
                    except Exception as e:
                        if guild_id is None:
                            for g in self.bot.guilds:
                                if g.get_channel(channel_id):
                                    guild_id = g.id
                                    ch = g.get_channel(channel_id)
                                    break
                        if guild_id and is_access_error(e):
                            await report_access_failure(
                                self.bot, guild_id, "daily", f"channel:{channel_id}"
                            )
                        return

                if not ch or guild_id is None:
                    return

                if channel_id in self.active_cat_channels and image_blob:
                    try:
                        file = discord.File(io.BytesIO(image_blob), filename="daily_cat.png")
                        await ch.send(content="Today's Cat Pic:", file=file)
                        await asyncio.sleep(0.25)
                    except Exception as e:
                        if is_access_error(e):
                            conn = self.db_pool.get_connection()
                            await conn.execute(
                                "DELETE FROM cat_channels WHERE channel_id = ?", (channel_id,)
                            )
                            await conn.commit()
                            self.active_cat_channels.discard(channel_id)
                            await report_access_failure(
                                self.bot, guild_id, "daily", f"channel:{channel_id}"
                            )

            await asyncio.gather(*(send_to_channel(cid) for cid in list(self.active_cat_channels)))

            self.next_send_time = self.next_send_time + timedelta(hours=23)
            await self.save_next_time()

    daily = app_commands.Group(name="daily", description="Daily automated messages.")

    cat_group = beacon_commands.Group(name="cat", description="Daily cat image commands", parent=daily, permissions_preset="automation")

    @cat_group.command(name="start", description="Start daily cat pics in a channel.")
    @app_commands.describe(
        channel="The channel where you want the daily cat image to be posted (defaults to current channel).")
    async def daily_cat_start(self, interaction: Interaction, channel: discord.TextChannel = None):
        channel_id = (channel.id if channel else interaction.channel_id)
        conn = self.db_pool.get_connection()

        if channel_id in self.active_cat_channels:
            return await interaction.response.send_message("Daily cat pics are already active here!", ephemeral=True)

        await conn.execute("INSERT INTO cat_channels (channel_id) VALUES (?)", (channel_id,))
        await conn.commit()
        self.active_cat_channels.add(channel_id)

        unix_timestamp = int(self.next_send_time.timestamp())

        await interaction.response.send_message(
            f"Daily cat pictures started! Next cat pic at: <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)"
        )

    @cat_group.command(name="stop", description="Stop daily cat pics in a channel.")
    @app_commands.describe(
        channel="The channel where you want the daily cat image to be stopped (defaults to current channel).")
    async def daily_cat_stop(self, interaction: Interaction, channel: discord.TextChannel = None):
        channel_id = channel.id if channel else interaction.channel_id
        conn = self.db_pool.get_connection()
        if channel_id not in self.active_cat_channels:
            return await interaction.response.send_message("Feature isn't active in this channel.", ephemeral=True)

        await conn.execute("DELETE FROM cat_channels WHERE channel_id = ?", (channel_id,))
        await conn.commit()
        self.active_cat_channels.remove(channel_id)

        await interaction.response.send_message(content="Daily cat pictures stopped.")

    @commands.command(name="del", hidden=True)
    @commands.is_owner()
    async def catwipe(self, ctx: commands.Context):
        conn = self.db_pool.get_connection()

        try:
            async with conn.execute("SELECT COUNT(*) FROM cat_images") as cursor:
                count = (await cursor.fetchone())[0]

            if count == 0:
                return await ctx.send("The cat database is already empty.")

            await conn.execute("DELETE FROM cat_images")
            await conn.execute("DELETE FROM sqlite_sequence WHERE name='cat_images'")
            await conn.commit()

            await ctx.send(f"Successfully wiped **{count}** images from the database.")

        except Exception as e:
            await ctx.send(f"An error occurred while wiping the database: {e}")

    def data_features(self) -> list[DataFeatureMeta]:
        return [DataFeatureMeta(
            feature_id="daily",
            name="Daily Cats",
            guild_export=True,
            guild_delete=True,
        )]

    async def data_export_user(self, user_id: int, *, guild_ids: list[int] | None) -> DataExportChunk:
        return DataExportChunk(feature_id="daily")

    async def _guild_cat_channels(self, guild: discord.Guild) -> list[int]:
        channels = []
        for channel_id in list(self.active_cat_channels or []):
            channel = guild.get_channel(channel_id)
            if channel is not None and getattr(channel, "guild", None) and channel.guild.id == guild.id:
                channels.append(channel_id)
        return channels

    async def data_export_guild(self, guild_id: int) -> DataExportChunk:
        chunk = DataExportChunk(feature_id="daily")
        guild = self.bot.get_guild(guild_id)
        cat_channels = await self._guild_cat_channels(guild) if guild else []
        conn = self.db_pool.get_connection()
        async with conn.execute("SELECT COUNT(*) FROM cat_images") as cursor:
            image_count = (await cursor.fetchone())[0]
        chunk.guild_data[guild_id] = {
            "cat_channels": cat_channels,
            "cat_images_metadata": {"count": image_count},
        }
        return chunk

    async def data_delete_user(self, user_id: int, *, guild_ids: list[int] | None, feature_id: str | None) -> DataDeleteResult:
        return DataDeleteResult(feature_id="daily")

    async def data_delete_guild(self, guild_id: int, feature_id: str | None) -> DataDeleteResult:
        if feature_id and feature_id != "daily":
            return DataDeleteResult(feature_id="daily")
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return DataDeleteResult(feature_id="daily")
        channel_ids = await self._guild_cat_channels(guild)
        if not channel_ids:
            return DataDeleteResult(feature_id="daily")
        conn = self.db_pool.get_connection()
        placeholders = ",".join("?" * len(channel_ids))
        cur = await conn.execute(
            f"DELETE FROM cat_channels WHERE channel_id IN ({placeholders})", channel_ids)
        await conn.commit()
        for cid in channel_ids:
            self.active_cat_channels.discard(cid)
        return DataDeleteResult(feature_id="daily", deleted=True, rows_affected=cur.rowcount)

    async def _channel_sendable(self, guild: discord.Guild, channel_id: int) -> bool:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if not isinstance(channel, discord.abc.GuildChannel) or channel.guild.id != guild.id:
            return False
        perms = channel.permissions_for(guild.me)
        return perms.view_channel and perms.send_messages

    async def data_monitor_guild(self, guild: discord.Guild) -> DataMonitorResult:
        result = DataMonitorResult(feature_id="daily")
        for channel_id in await self._guild_cat_channels(guild):
            if not await self._channel_sendable(guild, channel_id):
                conn = self.db_pool.get_connection()
                await conn.execute("DELETE FROM cat_channels WHERE channel_id = ?", (channel_id,))
                await conn.commit()
                self.active_cat_channels.discard(channel_id)
                result.actions.append(f"removed_cat_channel:{channel_id}")
        return result

async def setup(bot):
    await bot.add_cog(DailyCats(bot))