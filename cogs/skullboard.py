import asyncio
import time
from collections import deque
from typing import Optional, Dict, Set

import discord
from beacon import PrivateLayoutView, beacon_commands
from discord import app_commands
from discord.ext import commands, tasks

from utils.data_handlers import export_table
from utils.data_protocol import DataDeleteResult, DataExportChunk, DataFeatureMeta, DataMonitorResult
from utils.discord_health import is_access_error, report_access_failure


class ThresholdModal(discord.ui.Modal, title="Edit Skull Threshold"):
    def __init__(self, view: 'SkullboardDashboard'):
        super().__init__()
        self.view = view
        self.threshold_input = discord.ui.TextInput(
            label="Skull Threshold",
            placeholder="Enter a number (min 1)",
            min_length=1,
            max_length=3,
            required=True
        )
        self.add_item(self.threshold_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.threshold_input.value)
            if val < 1:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Please enter a valid number greater than 0.",
                                                           ephemeral=True)

        await self.view.cog.update_guild_setting(interaction.guild.id, skull_threshold=val)

        self.view.build_layout()
        await interaction.response.edit_message(view=self.view)


class SkullboardDashboard(PrivateLayoutView):
    def __init__(self, user, cog, guild_id):
        super().__init__(user, timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.build_layout()

    def build_layout(self):
        self.clear_items()

        settings = self.cog.settings_cache.get(self.guild_id, {})
        is_enabled = bool(settings.get("enabled", 0))
        current_channel_id = settings.get("skullboard_channel_id")
        current_threshold = settings.get("skull_threshold", 3)

        channel_mention = f"<#{current_channel_id}>" if current_channel_id else "Not Set"

        container = discord.ui.Container()

        toggle_style = discord.ButtonStyle.secondary if is_enabled else discord.ButtonStyle.primary
        toggle_label = "Disable" if is_enabled else "Enable"
        toggle_btn = discord.ui.Button(label=toggle_label, style=toggle_style)
        toggle_btn.callback = self.toggle_callback

        container.add_item(discord.ui.Section(discord.ui.TextDisplay("## Skullboard Dashboard"), accessory=toggle_btn))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "A skullboard is like a Hall Of Shame for Discord messages. Users can react to a message with a 💀 and once it reaches the set threshold, Dopamine will post a status count and forwarded message in the channel you choose."))

        if is_enabled:
            container.add_item(discord.ui.TextDisplay(
                f"* **Current Channel:** {channel_mention}\n* **Current Threshold:** {current_threshold}"))
            container.add_item(discord.ui.Separator())

            threshold_btn = discord.ui.Button(label="Edit Threshold", style=discord.ButtonStyle.primary)
            threshold_btn.callback = self.threshold_callback

            channel_btn = discord.ui.Button(label="Edit Channel", style=discord.ButtonStyle.secondary)
            channel_btn.callback = self.channel_edit_callback

            row = discord.ui.ActionRow()
            row.add_item(threshold_btn)
            row.add_item(channel_btn)
            container.add_item(row)

        self.add_item(container)

    async def toggle_callback(self, interaction: discord.Interaction):
        settings = self.cog.settings_cache.get(self.guild_id, {})
        current_state = bool(settings.get("enabled", 0))
        current_channel = settings.get("skullboard_channel_id")

        if not current_state and not current_channel:
            await self.cog.update_guild_setting(self.guild_id, enabled=1)

            view = ChannelSelectView(self, self.user, self.cog, self.guild_id, interaction)
            return await interaction.response.edit_message(view=view)

        new_state = 0 if current_state else 1
        await self.cog.update_guild_setting(self.guild_id, enabled=new_state)

        self.build_layout()
        await interaction.response.edit_message(view=self)

    async def threshold_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ThresholdModal(self))

    async def channel_edit_callback(self, interaction: discord.Interaction):
        view = ChannelSelectView(self, self.user, self.cog, self.guild_id, interaction)
        await interaction.response.edit_message(view=view)


class ChannelSelectView(PrivateLayoutView):
    def __init__(self, view: 'SkullboardDashboard', user, cog, guild_id, parent_interaction: discord.Interaction):
        super().__init__(user, timeout=None)
        self.cog = cog
        self.view = view
        self.guild_id = guild_id
        self.parent_interaction = parent_interaction
        self.build_layout()

    def build_layout(self):
        container = discord.ui.Container()

        select = discord.ui.ChannelSelect(
            placeholder="Select a channel...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1
        )
        select.callback = self.select_callback

        row = discord.ui.ActionRow()
        row.add_item(select)

        container.add_item(discord.ui.TextDisplay("### Select a Channel"))
        container.add_item(discord.ui.TextDisplay("Choose the channel where you want the skullboard to appear:"))
        container.add_item(row)
        self.add_item(container)

    async def select_callback(self, interaction: discord.Interaction):
        selected_channel = interaction.data['values'][0]

        await self.cog.update_guild_setting(self.guild_id, skullboard_channel_id=int(selected_channel))

        self.view.build_layout()
        await self.parent_interaction.edit_original_response(view=self.view)


class SkullboardCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.SKULL_EMOJI = "💀"

        self.settings_cache: Dict[int, dict] = {}
        # guild_id -> {source_message_id: (status_message_id, forwarded_message_id)}
        self.skull_posts_cache: Dict[int, Dict[int, tuple[int, int]]] = {}
        # status_message_id -> (guild_id, source_message_id)
        self.status_to_source_cache: Dict[int, tuple[int, int]] = {}
        # forwarded_message_id -> (guild_id, source_message_id)
        self.forwarded_to_source_cache: Dict[int, tuple[int, int]] = {}

        self.skulled_messages: deque[int] = deque(maxlen=10000)
        self.guild_cooldowns: dict[int, float] = {}
        self._skullboard_tasks: Dict[int, asyncio.Task] = {}

    async def cog_load(self):
        await self.bot.db.wait_ready()
        await self.populate_caches()
        if not self._cache_cleanup.is_running():
            self._cache_cleanup.start()

    async def cog_unload(self):
        self._cache_cleanup.cancel()

        for task in self._skullboard_tasks.values():
            if not task.done():
                task.cancel()

        if self._skullboard_tasks:
            await asyncio.gather(*self._skullboard_tasks.values(), return_exceptions=True)

    async def populate_caches(self):
        """Load all data from DB into memory."""
        self.settings_cache.clear()
        self.skull_posts_cache.clear()
        self.status_to_source_cache.clear()
        self.forwarded_to_source_cache.clear()

        rows = await self.bot.db.execute("SELECT * FROM skullboard_guild_settings")
        for data in rows:
            self.settings_cache[data["guild_id"]] = data

        rows = await self.bot.db.execute(
            "SELECT guild_id, source_message_id, status_message_id, forwarded_message_id FROM skull_posts")
        for row in rows:
            gid, src_id = row["guild_id"], row["source_message_id"]
            status_id, fwd_id = row["status_message_id"], row["forwarded_message_id"]
            if gid not in self.skull_posts_cache:
                self.skull_posts_cache[gid] = {}
            self.skull_posts_cache[gid][src_id] = (status_id, fwd_id)
            self.status_to_source_cache[status_id] = (gid, src_id)
            self.forwarded_to_source_cache[fwd_id] = (gid, src_id)

    async def get_guild_settings(self, guild_id: int) -> dict:
        """Fetch settings from cache, or create in DB and cache if missing."""
        if guild_id in self.settings_cache:
            return self.settings_cache[guild_id]

        await self.bot.db.execute(
            "INSERT OR IGNORE INTO skullboard_guild_settings (guild_id, enabled) VALUES (?, 0)",
            (guild_id,)
        )

        rows = await self.bot.db.execute(
            "SELECT * FROM skullboard_guild_settings WHERE guild_id = ?", (guild_id,))
        data = rows[0]

        self.settings_cache[guild_id] = data
        return data

    async def update_guild_setting(self, guild_id: int, **kwargs):
        """Update both DB and cache manually (Write-Through)."""
        if not kwargs:
            return

        settings = await self.get_guild_settings(guild_id)
        settings.update(kwargs)

        set_clause = ", ".join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]

        await self.bot.db.execute(
            f"UPDATE skullboard_guild_settings SET {set_clause} WHERE guild_id = ?", values)

    def get_skull_emoji(self, count: int) -> str:
        if count >= 15:
            return "⚰️"
        elif count >= 10:
            return "☠️"
        elif count >= 5:
            return "🪦"
        else:
            return "💀"

    async def upsert_skull_post(self, guild_id: int, source_id: int, status_id: int, forwarded_id: int):
        """Update both DB and cache for skull posts and reverse lookups."""
        if guild_id not in self.skull_posts_cache:
            self.skull_posts_cache[guild_id] = {}

        old_ids = self.skull_posts_cache[guild_id].get(source_id)
        if old_ids:
            old_status, old_fwd = old_ids
            self.status_to_source_cache.pop(old_status, None)
            self.forwarded_to_source_cache.pop(old_fwd, None)

        self.skull_posts_cache[guild_id][source_id] = (status_id, forwarded_id)
        self.status_to_source_cache[status_id] = (guild_id, source_id)
        self.forwarded_to_source_cache[forwarded_id] = (guild_id, source_id)

        await self.bot.db.execute("""
            INSERT INTO skull_posts (guild_id, source_message_id, status_message_id, forwarded_message_id)
            VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, source_message_id) DO
            UPDATE SET
                status_message_id = excluded.status_message_id,
                forwarded_message_id = excluded.forwarded_message_id
            """, (guild_id, source_id, status_id, forwarded_id))

    async def delete_skull_post(self, guild_id: int, source_id: int):
        """Remove from DB, cache, reverse lookups, and votes."""
        if guild_id in self.skull_posts_cache:
            ids = self.skull_posts_cache[guild_id].pop(source_id, None)
            if ids:
                status_id, fwd_id = ids
                self.status_to_source_cache.pop(status_id, None)
                self.forwarded_to_source_cache.pop(fwd_id, None)

        await self.bot.db.execute(
            "DELETE FROM skull_posts WHERE guild_id = ? AND source_message_id = ?",
            (guild_id, source_id)
        )
        await self.bot.db.execute(
            "DELETE FROM skull_votes WHERE guild_id = ? AND source_message_id = ?",
            (guild_id, source_id)
        )

    def get_skull_post(self, guild_id: int, source_id: int) -> Optional[tuple[int, int]]:
        """Pure cache read for performance."""
        return self.skull_posts_cache.get(guild_id, {}).get(source_id)

    def get_source_from_skullboard(self, guild_id: int, message_id: int) -> Optional[int]:
        """Reverse lookup to find source ID from status or forwarded message ID."""
        if message_id in self.status_to_source_cache:
            gid, src_id = self.status_to_source_cache[message_id]
            if gid == guild_id:
                return src_id
        if message_id in self.forwarded_to_source_cache:
            gid, src_id = self.forwarded_to_source_cache[message_id]
            if gid == guild_id:
                return src_id
        return None

    @tasks.loop(minutes=5)
    async def _cache_cleanup(self):
        await self.bot.db.wait_ready()
        current_time = time.time()
        to_remove_cd = [k for k, v in self.guild_cooldowns.items() if current_time - v > 600]
        for k in to_remove_cd:
            self.guild_cooldowns.pop(k, None)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id != self.bot.user.id and str(payload.emoji) == self.SKULL_EMOJI:
            self._schedule_skullboard_update(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) == self.SKULL_EMOJI:
            self._schedule_skullboard_update(payload)

    def _schedule_skullboard_update(self, payload: discord.RawReactionActionEvent):
        mid = payload.message_id
        if mid in self._skullboard_tasks and not self._skullboard_tasks[mid].done():
            self._skullboard_tasks[mid].cancel()
        self._skullboard_tasks[mid] = self.bot.loop.create_task(self._process_skullboard_payload(payload))

    async def _process_skullboard_payload(self, payload: discord.RawReactionActionEvent):
        try:
            guild = self.bot.get_guild(payload.guild_id) or await self.bot.fetch_guild(payload.guild_id)
            if not guild:
                return

            settings = await self.get_guild_settings(guild.id)
            if not settings.get("enabled", 0):
                return

            sb_id = settings.get("skullboard_channel_id")
            if not sb_id:
                return

            source_msg_id = None
            source_channel_id = None

            mapped_source_id = self.get_source_from_skullboard(guild.id, payload.message_id)
            if mapped_source_id:
                source_msg_id = mapped_source_id

            if not source_msg_id:
                if payload.channel_id == sb_id:
                    return
                source_msg_id = payload.message_id
                source_channel_id = payload.channel_id

            src_chan = None
            msg = None

            if source_channel_id:
                try:
                    src_chan = guild.get_channel(source_channel_id) or await guild.fetch_channel(source_channel_id)
                    msg = await src_chan.fetch_message(source_msg_id)
                except discord.NotFound:
                    return
            else:
                existing_ids = self.get_skull_post(guild.id, source_msg_id)
                if not existing_ids:
                    return
                status_id, fwd_id = existing_ids
                sbc = guild.get_channel(sb_id) or await guild.fetch_channel(sb_id)
                try:
                    fwd_msg = await sbc.fetch_message(fwd_id)
                    if fwd_msg.reference and fwd_msg.reference.message_id:
                        source_msg_id = fwd_msg.reference.message_id
                        if fwd_msg.reference.channel_id:
                            source_channel_id = fwd_msg.reference.channel_id
                            src_chan = guild.get_channel(source_channel_id) or await guild.fetch_channel(source_channel_id)
                            msg = await src_chan.fetch_message(source_msg_id)
                except Exception:
                    pass

            if not msg:
                return

            reactors: Set[int] = set()
            skull_react_source = next((r for r in msg.reactions if str(r.emoji) == self.SKULL_EMOJI), None)
            if skull_react_source:
                async for user in skull_react_source.users():
                    if not user.bot:
                        reactors.add(user.id)

            existing_ids = self.get_skull_post(guild.id, msg.id)
            sbc = guild.get_channel(sb_id) or await guild.fetch_channel(sb_id)
            status_msg = None
            fwd_msg = None

            if existing_ids:
                status_id, fwd_id = existing_ids
                try:
                    status_msg = await sbc.fetch_message(status_id)
                    star_react_status = next((r for r in status_msg.reactions if str(r.emoji) == self.SKULL_EMOJI), None)
                    if star_react_status:
                        async for user in star_react_status.users():
                            if not user.bot:
                                reactors.add(user.id)
                except discord.NotFound:
                    pass

                try:
                    fwd_msg = await sbc.fetch_message(fwd_id)
                    star_react_fwd = next((r for r in fwd_msg.reactions if str(r.emoji) == self.SKULL_EMOJI), None)
                    if star_react_fwd:
                        async for user in star_react_fwd.users():
                            if not user.bot:
                                reactors.add(user.id)
                except discord.NotFound:
                    pass

            await self.bot.db.execute("DELETE FROM skull_votes WHERE guild_id = ? AND source_message_id = ?", (guild.id, msg.id))
            for uid in reactors:
                await self.bot.db.execute(
                    "INSERT OR IGNORE INTO skull_votes (guild_id, source_message_id, user_id) VALUES (?, ?, ?)",
                    (guild.id, msg.id, uid)
                )

            rows = await self.bot.db.execute(
                "SELECT COUNT(*) as count FROM skull_votes WHERE guild_id = ? AND source_message_id = ?",
                (guild.id, msg.id)
            )
            total_count = rows[0]["count"] if rows else 0

            threshold = settings["skull_threshold"]

            if total_count < threshold:
                if existing_ids:
                    s_id, f_id = existing_ids
                    for mid in (s_id, f_id):
                        try:
                            bm = await sbc.fetch_message(mid)
                            await bm.delete()
                        except Exception:
                            pass
                    await self.delete_skull_post(guild.id, msg.id)
                return

            dynamic_emoji = self.get_skull_emoji(total_count)
            content_str = f"{dynamic_emoji} **{total_count}** | {msg.channel.mention}"

            if existing_ids:
                status_id, fwd_id = existing_ids
                try:
                    status_msg = await sbc.fetch_message(status_id)
                    await status_msg.edit(content=content_str)
                except discord.NotFound:
                    status_msg = await sbc.send(content=content_str)
                    fwd_msg = await sbc.send(reference=msg, mention_author=False)
                    await self.upsert_skull_post(guild.id, msg.id, status_msg.id, fwd_msg.id)
            else:
                status_msg = await sbc.send(content=content_str)
                fwd_msg = await sbc.send(reference=msg, mention_author=False)
                await self.upsert_skull_post(guild.id, msg.id, status_msg.id, fwd_msg.id)

        except Exception as e:
            if is_access_error(e):
                await report_access_failure(self.bot, guild.id, "skullboard", str(sb_id))
        finally:
            self._skullboard_tasks.pop(payload.message_id, None)

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionClearEvent):
        source_id = self.get_source_from_skullboard(payload.guild_id, payload.message_id) or payload.message_id
        existing = self.get_skull_post(payload.guild_id, source_id)
        if not existing:
            return

        settings = await self.get_guild_settings(payload.guild_id)
        sb_id = settings.get("skullboard_channel_id")
        if sb_id:
            try:
                sbc = self.bot.get_channel(sb_id) or await self.bot.fetch_channel(sb_id)
                for mid in existing:
                    try:
                        bm = await sbc.fetch_message(mid)
                        await bm.delete()
                    except Exception:
                        pass
            except Exception:
                pass
        await self.delete_skull_post(payload.guild_id, source_id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id:
            return

        existing = self.get_skull_post(payload.guild_id, payload.message_id)
        if existing:
            settings = await self.get_guild_settings(payload.guild_id)
            sb_id = settings.get("skullboard_channel_id")
            if sb_id:
                try:
                    sbc = self.bot.get_channel(sb_id) or await self.bot.fetch_channel(sb_id)
                    for mid in existing:
                        try:
                            bm = await sbc.fetch_message(mid)
                            await bm.delete()
                        except Exception:
                            pass
                except Exception:
                    pass
            await self.delete_skull_post(payload.guild_id, payload.message_id)
            return

        source_id = self.get_source_from_skullboard(payload.guild_id, payload.message_id)
        if source_id:
            existing = self.get_skull_post(payload.guild_id, source_id)
            if existing:
                settings = await self.get_guild_settings(payload.guild_id)
                sb_id = settings.get("skullboard_channel_id")
                if sb_id:
                    try:
                        sbc = self.bot.get_channel(sb_id) or await self.bot.fetch_channel(sb_id)
                        for mid in existing:
                            try:
                                bm = await sbc.fetch_message(mid)
                                await bm.delete()
                            except Exception:
                                pass
                    except Exception:
                        pass
                await self.delete_skull_post(payload.guild_id, source_id)

    @beacon_commands.command(name="skullboard", description="Configure the Skullboard via Dashboard", permissions_preset="automation")
    async def skullboard_dashboard(self, interaction: discord.Interaction):
        await self.get_guild_settings(interaction.guild.id)
        view = SkullboardDashboard(interaction.user, self, interaction.guild.id)
        await interaction.response.send_message(view=view)

    @commands.command(name="testskullboard")
    async def testskullboard(self, ctx: commands.Context):
        if ctx.author.id != 758576879715483719 or not ctx.message.reference:
            return

        ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        settings = await self.get_guild_settings(ctx.guild.id)
        sb_id = settings.get("skullboard_channel_id")
        if not sb_id:
            return

        skull_react = next((r for r in ref.reactions if str(r.emoji) == self.SKULL_EMOJI), None)
        count = skull_react.count if skull_react else 1

        content_str = f"💀 **{count}** | {ref.channel.mention}"
        channel = self.bot.get_channel(sb_id) or await self.bot.fetch_channel(sb_id)
        status_msg = await channel.send(content=content_str)
        fwd_msg = await channel.send(reference=ref, mention_author=False)
        await self.upsert_skull_post(ctx.guild.id, ref.id, status_msg.id, fwd_msg.id)

    def data_features(self) -> list[DataFeatureMeta]:
        return [DataFeatureMeta(
            feature_id="skullboard",
            name="Skullboard",
            guild_export=True,
            guild_delete=True,
        )]

    async def data_export_user(self, user_id: int, *, guild_ids: list[int] | None) -> DataExportChunk:
        return DataExportChunk(feature_id="skullboard")

    async def data_export_guild(self, guild_id: int) -> DataExportChunk:
        chunk = DataExportChunk(feature_id="skullboard")
        settings = await export_table(
            self.bot.db, "SELECT * FROM skullboard_guild_settings WHERE guild_id = ?", (guild_id,))
        posts = await export_table(
            self.bot.db, "SELECT * FROM skull_posts WHERE guild_id = ?", (guild_id,))
        votes = await export_table(
            self.bot.db, "SELECT * FROM skull_votes WHERE guild_id = ?", (guild_id,))
        chunk.guild_data[guild_id] = {"settings": settings, "skull_posts": posts, "skull_votes": votes}
        return chunk

    async def data_delete_user(self, user_id: int, *, guild_ids: list[int] | None, feature_id: str | None) -> DataDeleteResult:
        if feature_id and feature_id != "skullboard":
            return DataDeleteResult(feature_id="skullboard")
        rows_affected = 0
        async with self.bot.db.acquire_db() as db:
            query = "DELETE FROM skull_votes WHERE user_id = ?"
            params = (user_id,)
            if guild_ids:
                placeholders = ",".join("?" * len(guild_ids))
                query += f" AND guild_id IN ({placeholders})"
                params += tuple(guild_ids)
            res = await db.execute(query, params)
            await db.commit()
            rows_affected = res if isinstance(res, int) else res.get("rowcount", 0)
        return DataDeleteResult(feature_id="skullboard", deleted=True, rows_affected=rows_affected)

    async def data_delete_guild(self, guild_id: int, feature_id: str | None) -> DataDeleteResult:
        if feature_id and feature_id != "skullboard":
            return DataDeleteResult(feature_id="skullboard")

        async with self.bot.db.acquire_db() as db:
            res1 = await db.execute("DELETE FROM skull_posts WHERE guild_id = ?", (guild_id,))
            res2 = await db.execute("DELETE FROM skull_votes WHERE guild_id = ?", (guild_id,))
            res3 = await db.execute("DELETE FROM skullboard_guild_settings WHERE guild_id = ?", (guild_id,))
            await db.commit()

        rows_affected = sum(r if isinstance(r, int) else 0 for r in (res1, res2, res3))

        self.settings_cache.pop(guild_id, None)
        self.skull_posts_cache.pop(guild_id, None)
        return DataDeleteResult(feature_id="skullboard", deleted=True, rows_affected=rows_affected)

    async def _board_channel_accessible(self, guild: discord.Guild, channel_id: int | None) -> bool:
        if not channel_id:
            return True
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if not isinstance(channel, discord.abc.GuildChannel) or channel.guild.id != guild.id:
            return False
        perms = channel.permissions_for(guild.me)
        return perms.view_channel and perms.send_messages and perms.embed_links

    async def data_monitor_guild(self, guild: discord.Guild) -> DataMonitorResult:
        result = DataMonitorResult(feature_id="skullboard")
        settings = self.settings_cache.get(guild.id)
        if not settings or not settings.get("enabled"):
            return result
        channel_id = settings.get("skullboard_channel_id")
        if await self._board_channel_accessible(guild, channel_id):
            return result
        await self.update_guild_setting(guild.id, enabled=0)
        result.actions.append("disabled_skullboard")
        return result


async def setup(bot):
    await bot.add_cog(SkullboardCog(bot))
