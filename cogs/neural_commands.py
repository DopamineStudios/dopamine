import re
import time
from datetime import datetime, timezone
from typing import Optional

import discord
import google.genai as genai
from discord import app_commands
from discord.ext import commands
from google.genai import types

from cogs.moderation import parse_duration, format_punishment_label, format_duration_str, UndoActionView
from config import GEMINI_API_KEY, NEURAL_COMMANDS_MODEL
from utils.data_handlers import export_table
from utils.data_protocol import (
    DataFeatureMeta,
    DataExportChunk,
    DataDeleteResult,
    DataMonitorResult,
)
from utils.neural_context import NeuralContextBuilder
from utils.neural_functions import registry
from utils.neural_permissions import PermissionValidator


class NeuralCommands(commands.Cog):
    """Natural Language Commands powered by Google GenAI."""
    
    MODEL_NAME = NEURAL_COMMANDS_MODEL
    
    def __init__(self, bot):
        self.bot = bot
        self.client = None
        self.context_builder = None
        self.permission_validator = None
        
        # Initialize Google AI client
        if GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception as e:
                print(f"Failed to initialize Gemini client: {e}")
        else:
            print("GEMINI_API_KEY not set. Neural commands disabled.")
    
    async def cog_load(self):
        """Initialize dependencies after cog loads."""
        # Wait for database and schema to be fully ready
        await self.bot.db.wait_ready()
        
        moderation_cog = self.bot.get_cog("Moderation")
        self.context_builder = NeuralContextBuilder(self.bot, moderation_cog)
        self.permission_validator = PermissionValidator(self.bot)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for bot mentions and process as neural commands."""
        # Ignore bots
        if message.author.bot:
            return
        
        # Only in guilds
        if not message.guild:
            return
        
        # Check if bot is mentioned
        if self.bot.user not in message.mentions:
            return
        
        # Check if client is initialized
        if not self.client or not self.context_builder or not self.permission_validator:
            return
        
        # Check guild access (enabled status, blocked channels, allowed roles)
        allowed = await self._check_guild_access(message)
        if not allowed:
            return
        
        # Remove bot mention from message
        content = message.content
        for mention in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            content = content.replace(mention, "").strip()
        
        if not content:
            return
        
        # Pre-LLM permission check
        has_perm, missing = self.permission_validator.check_pre_llm_permissions(message.author)
        if not has_perm:
            return
        
        # Process the command
        async with message.channel.typing():
            try:
                await self._process_neural_command(message, content)
            except Exception as e:
                await message.reply(
                    f"❌ An error occurred while processing your command: {str(e)}",
                    mention_author=False
                )
                print(f"Neural command error: {e}")
    
    async def _process_neural_command(self, message: discord.Message, content: str):
        """Process a neural command through the LLM."""
        # Enrich mentions in the message
        enriched_content = await self.context_builder.replace_mentions(content, message.guild)
        
        # Build system prompt with full context
        system_prompt = await self.context_builder.build_system_prompt(
            message.guild,
            message.author,
            enriched_content
        )
        
        # Generate with function calling (async client method)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.MODEL_NAME,
                contents=system_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.95,
                    top_k=20,
                    max_output_tokens=1024,
                    tools=[registry.tool],
                )
            )
        except Exception as e:
            await message.reply(f"❌ LLM error: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "llm_error", False, str(e))
            return
        
        # Parse function call from response
        if not response.candidates:
            await message.reply("❌ No response from LLM", mention_author=False)
            return
        
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            await message.reply("❌ Empty response from LLM", mention_author=False)
            return
        
        function_call = None
        for part in candidate.content.parts:
            if getattr(part, 'function_call', None):
                function_call = part.function_call
                break
        
        if not function_call:
            await message.reply("❌ LLM did not return a function call", mention_author=False)
            return
        
        function_name = function_call.name
        function_args = dict(function_call.args) if function_call.args else {}
        
        # Execute the function
        await self._execute_function(message, function_name, function_args)
    
    async def _execute_function(self, message: discord.Message, function_name: str, args: dict):
        """Route function call to appropriate handler."""
        start_time = time.time()
        
        # Dismissal responses
        if function_name == "dismiss":
            await self._handle_dismiss(message)
            await self._log_usage(message.guild.id, message.author.id, function_name, True, None)
        
        elif function_name == "not_supported":
            await self._handle_not_supported(message, args.get("reason", ""))
            await self._log_usage(message.guild.id, message.author.id, function_name, True, None)
        
        elif function_name == "missing_mention":
            await self._handle_missing_mention(message, args.get("missing_what", ""))
            await self._log_usage(message.guild.id, message.author.id, function_name, True, None)
        
        elif function_name == "insufficient_permissions":
            await self._handle_insufficient_permissions(message, args.get("required_permissions", []))
            await self._log_usage(message.guild.id, message.author.id, function_name, True, None)
        
        # Role management
        elif function_name == "create_role":
            await self._handle_create_role(message, args)
        
        elif function_name == "update_role":
            await self._handle_update_role(message, args)
        
        elif function_name == "assign_role":
            await self._handle_assign_role(message, args)
        
        elif function_name == "remove_role":
            await self._handle_remove_role(message, args)
        
        elif function_name == "delete_role":
            await self._handle_delete_role(message, args)
        
        # Channel management
        elif function_name == "create_channel":
            await self._handle_create_channel(message, args)
        
        elif function_name == "update_channel":
            await self._handle_update_channel(message, args)
        
        elif function_name == "create_category":
            await self._handle_create_category(message, args)
        
        elif function_name == "delete_channel":
            await self._handle_delete_channel(message, args)
        
        # Nickname management
        elif function_name == "set_nickname":
            await self._handle_set_nickname(message, args)
        
        elif function_name == "clear_nickname":
            await self._handle_clear_nickname(message, args)
        
        # User information
        elif function_name == "get_user_info":
            await self._handle_get_user_info(message, args)
        
        elif function_name == "get_avatar":
            await self._handle_get_avatar(message, args)
        
        # Moderation
        elif function_name == "warn_user":
            await self._handle_warn_user(message, args)
        
        elif function_name == "edit_moderation_setting":
            await self._handle_edit_moderation_setting(message, args)
        
        elif function_name == "edit_warning_action":
            await self._handle_edit_warning_action(message, args)
        
        elif function_name == "delete_warning_action":
            await self._handle_delete_warning_action(message, args)
        
        elif function_name == "toggle_message_reporting":
            await self._handle_toggle_message_reporting(message, args)
        
        elif function_name == "set_report_channel":
            await self._handle_set_report_channel(message, args)
        
        elif function_name == "set_report_roles":
            await self._handle_set_report_roles(message, args)
        
        else:
            await message.reply(f"❌ Unknown function: {function_name}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, function_name, False, "Unknown function")
        
        # Log to optional guild log channel
        elapsed = time.time() - start_time
        await self._log_to_channel(message, function_name, args, elapsed)
    
    # ==================== Dismissal Handlers ====================
    
    async def _handle_dismiss(self, message: discord.Message):
        """Politely decline the request."""
        await message.reply(
            "I can't help with that request.",
            mention_author=False
        )
    
    async def _handle_not_supported(self, message: discord.Message, reason: str):
        """Explain unsupported feature."""
        await message.reply(
            f"❌ Not supported: {reason}",
            mention_author=False
        )
    
    async def _handle_missing_mention(self, message: discord.Message, missing_what: str):
        """Request missing mention."""
        await message.reply(
            f"❌ Please mention the {missing_what} you want to target.",
            mention_author=False
        )
    
    async def _handle_insufficient_permissions(self, message: discord.Message, required_permissions: list[str]):
        """Inform about missing permissions."""
        perms_str = self.permission_validator.format_missing_permissions(required_permissions)
        await message.reply(
            f"❌ You need the following permission(s) to do that: {perms_str}",
            mention_author=False
        )
    
    async def _confirm_destructive(self, message: discord.Message, title: str, body: str) -> bool:
        """Confirm a destructive action using DestructiveConfirmationView."""
        from cogs.moderation import DestructiveConfirmationView
        moderation_cog = self.bot.get_cog("Moderation")
        view = DestructiveConfirmationView(message.author, moderation_cog, title, body)
        msg = await message.reply(view=view, mention_author=False)
        view.message = msg
        await view.wait()
        return view.value is True
    
    # ==================== Role Management Handlers ====================
    
    async def _handle_create_role(self, message: discord.Message, args: dict):
        """Create a new role."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("create_role", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "create_role", False, "Insufficient permissions")
            return
        
        # Validate role name
        name = args.get("name")
        is_valid, error = self.permission_validator.validate_role_name(name)
        if not is_valid:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_role", False, error)
            return
        
        # Get color
        color_name = args.get("color")
        color = discord.Color.default()
        if color_name:
            color_hex = self.context_builder.get_color_hex(color_name)
            if color_hex is not None:
                color = discord.Color(color_hex)
        
        # Parse permissions with security check against actor's permissions
        permissions = discord.Permissions.none()
        if args.get("permissions"):
            author_perms = message.author.guild_permissions
            for perm_name in args["permissions"]:
                if hasattr(permissions, perm_name):
                    if message.author.id != message.guild.owner_id and not getattr(author_perms, perm_name, False):
                        await message.reply(f"❌ You cannot grant the `{perm_name}` permission because you do not possess it.", mention_author=False)
                        await self._log_usage(message.guild.id, message.author.id, "create_role", False, f"Unauthorized permission: {perm_name}")
                        return
                    setattr(permissions, perm_name, True)
        
        # Create role
        try:
            role = await message.guild.create_role(
                name=name,
                color=color,
                permissions=permissions,
                hoist=args.get("hoist", False),
                mentionable=args.get("mentionable", False),
                reason=f"Neural command by {message.author}"
            )
            
            await message.reply(
                f"✅ Created role {role.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "create_role", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to create roles", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_role", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to create role: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_role", False, str(e))
    
    async def _handle_update_role(self, message: discord.Message, args: dict):
        """Update an existing role."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("update_role", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Insufficient permissions")
            return
        
        # Get role
        role_id = self._parse_id(args.get("role_id", 0))
        role = message.guild.get_role(role_id)
        if not role:
            await message.reply("❌ Role not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Role not found")
            return
        
        # Check hierarchy
        can_manage, error = self.permission_validator.check_role_hierarchy(message.author, role)
        if not can_manage:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_role", False, error)
            return
        
        # Build update kwargs
        kwargs = {"reason": f"Neural command by {message.author}"}
        
        if "name" in args:
            is_valid, error = self.permission_validator.validate_role_name(args["name"])
            if not is_valid:
                await message.reply(f"❌ {error}", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "update_role", False, error)
                return
            kwargs["name"] = args["name"]
        
        if "color" in args:
            color_hex = self.context_builder.get_color_hex(args["color"])
            if color_hex is not None:
                kwargs["color"] = discord.Color(color_hex)
        
        if "permissions" in args:
            permissions = discord.Permissions.none()
            author_perms = message.author.guild_permissions
            for perm_name in args["permissions"]:
                if hasattr(permissions, perm_name):
                    if message.author.id != message.guild.owner_id and not getattr(author_perms, perm_name, False):
                        await message.reply(f"❌ You cannot grant the `{perm_name}` permission because you do not possess it.", mention_author=False)
                        await self._log_usage(message.guild.id, message.author.id, "update_role", False, f"Unauthorized permission: {perm_name}")
                        return
                    setattr(permissions, perm_name, True)
            kwargs["permissions"] = permissions
        
        if "hoist" in args:
            kwargs["hoist"] = args["hoist"]
        
        if "mentionable" in args:
            kwargs["mentionable"] = args["mentionable"]
        
        if "position" in args:
            try:
                new_pos = int(args["position"])
            except ValueError:
                await message.reply("❌ Invalid position value", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Invalid position")
                return
            max_actor_pos = message.author.top_role.position
            max_bot_pos = message.guild.me.top_role.position
            if message.author.id != message.guild.owner_id and new_pos >= max_actor_pos:
                await message.reply("❌ Target position cannot be higher than or equal to your highest role.", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Position exceeds actor hierarchy")
                return
            if new_pos >= max_bot_pos:
                await message.reply("❌ Target position cannot be higher than or equal to the bot's highest role.", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Position exceeds bot hierarchy")
                return
            kwargs["position"] = new_pos
        
        # Update role
        try:
            await role.edit(**kwargs)
            
            await message.reply(
                f"✅ Updated role {role.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "update_role", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to edit that role", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_role", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to update role: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_role", False, str(e))
    
    async def _handle_assign_role(self, message: discord.Message, args: dict):
        """Assign a role to a user."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("assign_role", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, "Insufficient permissions")
            return
        
        # Get user and role
        user_id = int(args.get("user_id", 0))
        role_id = int(args.get("role_id", 0))
        
        member = message.guild.get_member(user_id)
        role = message.guild.get_role(role_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, "User not found")
            return
        
        if not role:
            await message.reply("❌ Role not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, "Role not found")
            return
        
        # Check hierarchies
        can_manage_role, error = self.permission_validator.check_role_hierarchy(message.author, role)
        if not can_manage_role:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, error)
            return
        
        can_manage_member, error = self.permission_validator.check_member_hierarchy(message.author, member)
        if not can_manage_member:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, error)
            return
        
        # Assign role
        try:
            if role in member.roles:
                await message.reply(f"❌ {member.mention} already has the {role.mention} role", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "assign_role", False, "Already has role")
                return
            
            await member.add_roles(role, reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Assigned {role.mention} to {member.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "assign_role", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to assign that role", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to assign role: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "assign_role", False, str(e))
    
    async def _handle_remove_role(self, message: discord.Message, args: dict):
        """Remove a role from a user."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("remove_role", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, "Insufficient permissions")
            return
        
        # Get user and role
        user_id = int(args.get("user_id", 0))
        role_id = int(args.get("role_id", 0))
        
        member = message.guild.get_member(user_id)
        role = message.guild.get_role(role_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, "User not found")
            return
        
        if not role:
            await message.reply("❌ Role not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, "Role not found")
            return
        
        # Check hierarchies
        can_manage_role, error = self.permission_validator.check_role_hierarchy(message.author, role)
        if not can_manage_role:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, error)
            return
        
        can_manage_member, error = self.permission_validator.check_member_hierarchy(message.author, member)
        if not can_manage_member:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, error)
            return
        
        # Remove role
        try:
            if role not in member.roles:
                await message.reply(f"❌ {member.mention} doesn't have the {role.mention} role", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "remove_role", False, "Doesn't have role")
                return
            
            await member.remove_roles(role, reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Removed {role.mention} from {member.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "remove_role", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to remove that role", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to remove role: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "remove_role", False, str(e))
    
    async def _handle_delete_role(self, message: discord.Message, args: dict):
        """Delete a role."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("delete_role", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, "Insufficient permissions")
            return
        
        # Get role
        role_id = int(args.get("role_id", 0))
        role = message.guild.get_role(role_id)
        
        if not role:
            await message.reply("❌ Role not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, "Role not found")
            return
        
        # Check hierarchy
        can_manage, error = self.permission_validator.check_role_hierarchy(message.author, role)
        if not can_manage:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, error)
            return
        
        # Confirm destructive action
        if not await self._confirm_destructive(message, "Confirm Role Deletion", f"Are you sure you want to delete role **{role.name}**?"):
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, "Cancelled by user")
            return
        
        # Delete role
        try:
            role_name = role.name
            await role.delete(reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Deleted role `{role_name}`",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "delete_role", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to delete that role", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to delete role: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_role", False, str(e))
    
    # ==================== Channel Management Handlers ====================
    
    async def _handle_create_channel(self, message: discord.Message, args: dict):
        """Create a new channel."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("create_channel", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "create_channel", False, "Insufficient permissions")
            return
        
        # Validate channel name
        name = args.get("name", "")
        channel_type = args.get("channel_type", "text")
        is_valid, error = self.permission_validator.validate_channel_name(name, channel_type)
        if not is_valid:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_channel", False, error)
            return
        
        # Get category
        category = None
        if args.get("category_id"):
            category_id = int(args["category_id"])
            category = message.guild.get_channel(category_id)
            if category and not isinstance(category, discord.CategoryChannel):
                await message.reply("❌ Specified category ID is not a category channel", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "create_channel", False, "Invalid category")
                return
        
        # Create channel
        try:
            kwargs = {
                "name": name,
                "category": category,
                "reason": f"Neural command by {message.author}"
            }
            
            if args.get("position") is not None:
                kwargs["position"] = args["position"]
            
            if channel_type == "voice":
                channel = await message.guild.create_voice_channel(**kwargs)
            else:
                channel = await message.guild.create_text_channel(**kwargs)
            
            await message.reply(
                f"✅ Created channel {channel.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "create_channel", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to create channels", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_channel", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to create channel: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_channel", False, str(e))
    
    async def _handle_update_channel(self, message: discord.Message, args: dict):
        """Update an existing channel."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("update_channel", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "update_channel", False, "Insufficient permissions")
            return
        
        # Get channel
        channel_id = int(args.get("channel_id", 0))
        channel = message.guild.get_channel(channel_id)
        
        if not channel:
            await message.reply("❌ Channel not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_channel", False, "Channel not found")
            return
        
        # Channel permission check
        has_ch_perm, ch_err = self.permission_validator.check_channel_permissions(message.author, channel)
        if not has_ch_perm:
            await message.reply(f"❌ {ch_err}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_channel", False, ch_err)
            return
        
        # Build update kwargs
        kwargs = {"reason": f"Neural command by {message.author}"}
        
        if "name" in args:
            channel_type = "text" if isinstance(channel, discord.TextChannel) else "voice"
            is_valid, error = self.permission_validator.validate_channel_name(args["name"], channel_type)
            if not is_valid:
                await message.reply(f"❌ {error}", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "update_channel", False, error)
                return
            kwargs["name"] = args["name"]
        
        if "category_id" in args:
            if args["category_id"].lower() == "none":
                kwargs["category"] = None
            else:
                category_id = int(args["category_id"])
                category = message.guild.get_channel(category_id)
                if category and isinstance(category, discord.CategoryChannel):
                    kwargs["category"] = category
                else:
                    await message.reply("❌ Invalid category", mention_author=False)
                    await self._log_usage(message.guild.id, message.author.id, "update_channel", False, "Invalid category")
                    return
        
        if "position" in args:
            kwargs["position"] = args["position"]
        
        if isinstance(channel, discord.TextChannel):
            if "topic" in args:
                kwargs["topic"] = args["topic"]
            
            if "slowmode" in args:
                is_valid, error = self.permission_validator.validate_slowmode(args["slowmode"])
                if not is_valid:
                    await message.reply(f"❌ {error}", mention_author=False)
                    await self._log_usage(message.guild.id, message.author.id, "update_channel", False, error)
                    return
                kwargs["slowmode_delay"] = args["slowmode"]
        
        # Update channel
        try:
            await channel.edit(**kwargs)
            await message.reply(
                f"✅ Updated channel {channel.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "update_channel", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to edit that channel", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_channel", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to update channel: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "update_channel", False, str(e))
    
    async def _handle_create_category(self, message: discord.Message, args: dict):
        """Create a new category."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("create_category", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "create_category", False, "Insufficient permissions")
            return
        
        # Validate name
        name = args.get("name", "")
        if len(name) > 100 or len(name) < 1:
            await message.reply("❌ Category name must be 1-100 characters", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_category", False, "Invalid name length")
            return
        
        # Create category
        try:
            kwargs = {
                "name": name,
                "reason": f"Neural command by {message.author}"
            }
            
            if args.get("position") is not None:
                kwargs["position"] = args["position"]
            
            category = await message.guild.create_category(**kwargs)
            await message.reply(
                f"✅ Created category `{category.name}`",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "create_category", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to create categories", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_category", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to create category: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "create_category", False, str(e))
    
    async def _handle_delete_channel(self, message: discord.Message, args: dict):
        """Delete a channel or category."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("delete_channel", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, "Insufficient permissions")
            return
        
        # Get channel
        channel_id = self._parse_id(args.get("channel_id", 0))
        channel = message.guild.get_channel(channel_id)
        
        if not channel:
            await message.reply("❌ Channel not found", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, "Channel not found")
            return
        
        # Channel permission check
        has_ch_perm, ch_err = self.permission_validator.check_channel_permissions(message.author, channel)
        if not has_ch_perm:
            await message.reply(f"❌ {ch_err}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, ch_err)
            return
        
        # Don't delete current channel
        if channel.id == message.channel.id:
            await message.reply("❌ Cannot delete the current channel", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, "Cannot delete current channel")
            return
        
        # Protect critical channels
        guild = message.guild
        critical_channels = {
            guild.rules_channel.id if guild.rules_channel else None,
            guild.system_channel.id if guild.system_channel else None,
            guild.afk_channel.id if guild.afk_channel else None,
        }
        async with self.bot.db.acquire_db() as db:
            rows = await db.execute("SELECT log_channel_id FROM neural_command_settings WHERE guild_id = ?", (guild.id,))
            if rows and rows[0].get("log_channel_id"):
                critical_channels.add(rows[0]["log_channel_id"])

        if channel.id in critical_channels:
            await message.reply(f"❌ Cannot delete critical server channel **{channel.name}**.", mention_author=False)
            await self._log_usage(guild.id, message.author.id, "delete_channel", False, "Critical channel protection")
            return
        
        # Confirm destructive action
        channel_type = "category" if isinstance(channel, discord.CategoryChannel) else "channel"
        if not await self._confirm_destructive(message, "Confirm Channel Deletion", f"Are you sure you want to delete {channel_type} **{channel.name}**?"):
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, "Cancelled by user")
            return
        
        # Delete channel
        try:
            channel_name = channel.name
            channel_type = "category" if isinstance(channel, discord.CategoryChannel) else "channel"
            await channel.delete(reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Deleted {channel_type} `{channel_name}`",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to delete that channel", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to delete channel: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_channel", False, str(e))
    
    # ==================== Nickname Management Handlers ====================
    
    async def _handle_set_nickname(self, message: discord.Message, args: dict):
        """Set a user's nickname."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("set_nickname", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, "Insufficient permissions")
            return
        
        # Get user
        user_id = self._parse_id(args.get("user_id", 0))
        member = message.guild.get_member(user_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, "User not found")
            return
        
        # Check hierarchy (allow self-nickname change if actor equals target)
        can_manage, error = self.permission_validator.check_member_hierarchy(message.author, member, is_moderation=False)
        if not can_manage:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, error)
            return
        
        # Validate nickname
        nickname = args.get("nickname", "")
        is_valid, error = self.permission_validator.validate_nickname_length(nickname)
        if not is_valid:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, error)
            return
        
        # Set nickname
        try:
            old_nick = member.display_name
            await member.edit(nick=nickname, reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Changed {member.mention}'s nickname from `{old_nick}` to `{nickname}`",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to change that user's nickname", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to set nickname: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_nickname", False, str(e))
    
    async def _handle_clear_nickname(self, message: discord.Message, args: dict):
        """Clear a user's nickname."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("clear_nickname", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, "Insufficient permissions")
            return
        
        # Get user
        user_id = self._parse_id(args.get("user_id", 0))
        member = message.guild.get_member(user_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, "User not found")
            return
        
        # Check hierarchy (allow self-nickname clear if actor equals target)
        can_manage, error = self.permission_validator.check_member_hierarchy(message.author, member, is_moderation=False)
        if not can_manage:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, error)
            return
        
        # Clear nickname
        try:
            if not member.nick:
                await message.reply(f"❌ {member.mention} doesn't have a nickname", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, "No nickname")
                return
            
            old_nick = member.nick
            await member.edit(nick=None, reason=f"Neural command by {message.author}")
            await message.reply(
                f"✅ Cleared {member.mention}'s nickname (was `{old_nick}`)",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", True, None)
        
        except discord.Forbidden:
            await message.reply("❌ I don't have permission to change that user's nickname", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, "Bot lacks permission")
        except Exception as e:
            await message.reply(f"❌ Failed to clear nickname: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "clear_nickname", False, str(e))
    
    # ==================== User Information Handlers ====================
    
    async def _handle_get_user_info(self, message: discord.Message, args: dict):
        """Get detailed user information."""
        user_id = self._parse_id(args.get("user_id", 0))
        member = message.guild.get_member(user_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "get_user_info", False, "User not found")
            return
        
        # Build info embed
        embed = discord.Embed(
            title=f"User Info: {member.display_name}",
            color=member.color
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Username", value=member.name, inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        
        joined_str = f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown"
        embed.add_field(
            name="Joined Server",
            value=joined_str,
            inline=True
        )
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True
        )
        
        roles_str = " ".join([r.mention for r in member.roles[1:]]) if len(member.roles) > 1 else "None"
        embed.add_field(name=f"Roles [{len(member.roles)-1}]", value=roles_str, inline=False)
        
        # Add warning count if moderation cog is available
        moderation_cog = self.bot.get_cog("Moderation")
        if moderation_cog:
            user_data = await moderation_cog.get_user_data(message.guild.id, member.id)
            warnings = user_data.get("warnings", 0)
            points = user_data.get("points", 0)
            embed.add_field(name="Warnings", value=str(warnings), inline=True)
            embed.add_field(name="Points", value=str(points), inline=True)
        
        await message.reply(embed=embed, mention_author=False)
        await self._log_usage(message.guild.id, message.author.id, "get_user_info", True, None)
    
    async def _handle_get_avatar(self, message: discord.Message, args: dict):
        """Get a user's avatar."""
        user_id = self._parse_id(args.get("user_id", 0))
        try:
            size = int(args.get("size", 1024))
        except Exception:
            size = 1024
        valid_sizes = {16, 32, 64, 128, 256, 512, 1024, 2048, 4096}
        if size not in valid_sizes:
            size = 1024
        
        member = message.guild.get_member(user_id)
        if not member:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                await message.reply("❌ User not found", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "get_avatar", False, "User not found")
                return
        else:
            user = member
        
        # Build avatar embed
        avatar_url = user.display_avatar.with_size(size).url
        
        embed = discord.Embed(
            title=f"{user.name}'s Avatar",
            color=discord.Color.blurple()
        )
        embed.set_image(url=avatar_url)
        embed.add_field(name="Download", value=f"[Click here]({avatar_url})", inline=False)
        
        await message.reply(embed=embed, mention_author=False)
        await self._log_usage(message.guild.id, message.author.id, "get_avatar", True, None)
    
    # ==================== Moderation Handlers ====================
    
    async def _handle_warn_user(self, message: discord.Message, args: dict):
        """Warn a user using the moderation system."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("warn_user", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "warn_user", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "warn_user", False, "Moderation cog not loaded")
            return
        
        # Get user
        user_id = int(args.get("user_id", 0))
        member = message.guild.get_member(user_id)
        
        if not member:
            await message.reply("❌ User not found in this server", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "warn_user", False, "User not found")
            return
        
        # Check hierarchy
        can_manage, error = self.permission_validator.check_member_hierarchy(message.author, member)
        if not can_manage:
            await message.reply(f"❌ {error}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "warn_user", False, error)
            return
        
        # Get amount and reason
        try:
            amount = max(1, int(args.get("amount", 1)))
        except (ValueError, TypeError):
            amount = 1
        reason = args.get("reason", "No reason provided")
        
        try:
            # Ensure guild moderation setup exists
            if message.guild.id not in moderation_cog.settings_cache:
                await self.bot.db.execute(
                    "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
                    (message.guild.id,)
                )
                moderation_cog.settings_cache[message.guild.id] = {
                    "punishment_dm": 1, "punishment_log": 1, "simple_mode": 1,
                    "decay_interval": 14, "rejoin_points": 4,
                    "msg_report_enabled": 0, "msg_report_channel": None, "msg_report_roles": None,
                    "decay_log_enabled": 0, "show_medals": 1
                }
                await moderation_cog.apply_default_actions(message.guild.id)
            
            # Resolve pending punishments if any
            rows = await self.bot.db.execute(
                "SELECT id FROM pending_punishments WHERE guild_id = ? AND user_id = ?",
                (message.guild.id, member.id)
            )
            if rows:
                pending_id = rows[0]["id"]
                try:
                    await member.timeout(None, reason="Pending punishment resolved by formal infraction.")
                except Exception:
                    pass
                await self.bot.db.execute("DELETE FROM pending_punishments WHERE id = ?", (pending_id,))
            
            all_errors = []
            data = await moderation_cog.get_user_data(message.guild.id, member.id)
            old_points = max(0, data["points"])
            new_points = max(0, data["points"] + amount)
            now = int(time.time())
            
            await moderation_cog.update_user_points(message.guild.id, member.id, new_points, punishment_ts=now)
            
            action, duration = moderation_cog.get_punishment_data(new_points, message.guild.id)
            settings = moderation_cog.settings_cache.get(message.guild.id, {})
            term = "warning" if settings.get("simple_mode", 0) == 1 else "point"
            
            punishment_duration = int(duration.total_seconds()) if duration else 0
            punishment_text = format_punishment_label(action, duration)
            
            case_number = await moderation_cog.record_infraction(
                guild_id=message.guild.id,
                user_id=member.id,
                moderator_id=message.author.id,
                amount=amount,
                reason=reason,
                punishment_type=action,
                punishment_duration=punishment_duration,
                points_after=new_points,
                created_at=now,
            )
            
            if action:
                reason_text = f"{term.title()}s: {new_points} | {reason or 'No reason provided.'}"
                action_text = action
                if action == "timeout":
                    action_text = "timed out"
                elif action == "ban":
                    action_text = "banned"
                elif action == "kick":
                    action_text = "kicked"
                elif action == "warning":
                    action_text = "warned"
                
                duration_str = format_duration_str(int(duration.total_seconds())) if duration else None
                display_action = action_text.capitalize()
                if "ban" in action_text.lower() and duration_str is None:
                    display_action = "Permanently banned"
                
                if duration_str:
                    first_line = f"{display_action} for {duration_str}."
                    dm_prep = "from" if "ban" in action_text.lower() or "kick" in action_text.lower() else "in"
                    dm_first_line = f"You have been {display_action} {dm_prep} {message.guild.name} for {duration_str}."
                else:
                    first_line = f"{display_action}."
                    dm_prep = "from" if "ban" in action_text.lower() or "kick" in action_text.lower() else "in"
                    dm_first_line = f"You have been {display_action} {dm_prep} {message.guild.name}."
                
                is_ban = "ban" in action_text.lower() or "kick" in action_text.lower()
                main_color = discord.Color.red() if is_ban else discord.Color.orange()
                
                log_embed = discord.Embed(
                    title=f"{action.capitalize()} | Case #{case_number}",
                    description=(
                        f"* **Old Amount:** {old_points} {term}(s)\n"
                        f"* **New Amount:** {new_points} {term}(s)\n"
                        f"* **Resulting Action:** {first_line}\n"
                        f"* **Reason:** {reason or 'No reason provided.'}"
                    ),
                    color=main_color
                )
                log_embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
                log_embed.set_footer(text=f"by {message.author.display_name}", icon_url=message.author.display_avatar.url)
                
                dm_embed = discord.Embed(
                    title=dm_first_line,
                    description=(
                        f"* **Old Amount:** {old_points} {term}(s)\n"
                        f"* **New Amount:** {new_points} {term}(s)\n"
                        f"* **Reason:** {reason or 'No reason provided.'}"
                    ),
                    color=main_color
                )
                dm_embed.set_footer(text=f"by {message.author.display_name}", icon_url=message.author.display_avatar.url)
                
                if settings.get("punishment_dm", 1):
                    try:
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        all_errors.append("DM not sent because user's DMs are closed")
                    except Exception:
                        all_errors.append("DM not sent")
                
                try:
                    if action == "timeout" and duration:
                        await member.timeout(discord.utils.utcnow() + duration, reason=reason_text)
                    elif action == "kick":
                        await member.kick(reason=reason_text)
                    elif action == "ban":
                        await message.guild.ban(member, reason=reason_text, delete_message_days=0)
                        if duration:
                            unban_ts = int((discord.utils.utcnow() + duration).timestamp())
                            await self.bot.db.execute(
                                "INSERT OR REPLACE INTO ban_schedule (guild_id, user_id, unban_at) VALUES (?, ?, ?)",
                                (message.guild.id, member.id, unban_ts)
                            )
                except discord.Forbidden:
                    all_errors.append("Punishment failed (Missing Permissions)")
                except Exception as e:
                    all_errors.append(f"Punishment error: {str(e)}")
                
                if settings.get("punishment_log", 1):
                    log_ch = await moderation_cog.get_log_channel(message.guild)
                    if log_ch:
                        try:
                            await log_ch.send(embed=log_embed)
                        except Exception:
                            pass
            
            embed_desc = (
                f"{member.mention} now has {new_points} {term}(s) – {punishment_text}.\n"
                f"* **Reason:** {reason or 'No reason provided.'}"
            )
            if all_errors:
                embed_desc += f"\n* **Errors:** {', '.join(all_errors)}"
            
            embed = discord.Embed(
                description=embed_desc,
                color=discord.Color.red()
            )
            embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url)
            embed.set_footer(
                text=f"by {message.author.display_name} • Case #{case_number}",
                icon_url=message.author.display_avatar.url
            )
            
            expires_at = now + 10
            undo_view = UndoActionView(moderation_cog, case_number, message.guild.id, expires_at)
            reply_msg = await message.reply(embed=embed, view=undo_view, mention_author=False)
            undo_view.message = reply_msg
            
            await self._log_usage(message.guild.id, message.author.id, "warn_user", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to warn user: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "warn_user", False, str(e))
    
    async def _handle_edit_moderation_setting(self, message: discord.Message, args: dict):
        """Edit a moderation dashboard setting."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("edit_moderation_setting", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, "Moderation cog not loaded")
            return
        
        setting_name = args.get("setting_name")
        new_value_str = args.get("new_value")
        
        # Valid settings
        valid_settings = {
            "punishment_dm": bool,
            "punishment_log": bool,
            "simple_mode": bool,
            "decay_interval": int,
            "rejoin_points": int,
            "decay_log_enabled": bool,
            "show_medals": bool,
        }
        
        if setting_name not in valid_settings:
            await message.reply(f"❌ Invalid setting name: {setting_name}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, "Invalid setting")
            return
        
        # Convert value to appropriate type
        try:
            value_type = valid_settings[setting_name]
            if value_type == bool:
                new_value = new_value_str.lower() in ["true", "1", "yes", "on", "enabled"]
            elif setting_name == "decay_interval":
                val_str = str(new_value_str).lower().strip()
                if val_str == "0" or val_str == "none":
                    new_value = 0
                else:
                    seconds = parse_duration(val_str)
                    if not seconds:
                        try:
                            new_value = int(val_str)
                        except ValueError:
                            raise ValueError("Invalid duration")
                    else:
                        new_value = seconds // 86400
                if new_value != 0 and (new_value < 1 or new_value > 365):
                    await message.reply("❌ Decay interval must be between 1 and 365 days (or 0 to disable).", mention_author=False)
                    await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, "Out of range days")
                    return
            elif value_type == int:
                new_value = int(new_value_str)
            else:
                new_value = new_value_str
        except ValueError:
            await message.reply(f"❌ Invalid value for {setting_name}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, "Invalid value")
            return
        
        # Update setting in database
        try:
            db_val = int(new_value) if isinstance(new_value, bool) else new_value
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
                (message.guild.id,)
            )
            await self.bot.db.execute(
                f"UPDATE moderation_settings SET {setting_name} = ? WHERE guild_id = ?",
                (db_val, message.guild.id)
            )
            
            # Refresh cache
            if message.guild.id in moderation_cog.settings_cache:
                moderation_cog.settings_cache[message.guild.id][setting_name] = db_val
            else:
                await moderation_cog.populate_caches()
            
            await message.reply(
                f"✅ Updated moderation setting: `{setting_name}` = `{new_value}`",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to update setting: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_moderation_setting", False, str(e))
    
    async def _handle_edit_warning_action(self, message: discord.Message, args: dict):
        """Edit a warning action threshold."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("edit_warning_action", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", False, "Moderation cog not loaded")
            return
        
        # Get action index
        action_index = args.get("action_index", 1)
        actions = moderation_cog.action_cache.get(message.guild.id, [])
        
        if action_index < 1 or action_index > len(actions):
            await message.reply(f"❌ Invalid action index. Valid range: 1-{len(actions)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", False, "Invalid action index")
            return
        
        # Get existing action
        action = sorted(actions, key=lambda a: a['points'])[action_index - 1]
        action_id = action['id']
        
        # Build update values
        points = args.get("points", action['points'])
        action_type = args.get("action_type", action['action_type'])
        duration_str = args.get("duration")
        
        # Parse duration if provided
        duration = action.get('duration')
        if duration_str:
            duration = parse_duration(duration_str)
            if duration is None:
                await message.reply("❌ Invalid duration format. Use format like '1h', '3d', '1w'", mention_author=False)
                await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", False, "Invalid duration")
                return
        
        # Update action in database
        try:
            async with self.bot.db.acquire_db() as db:
                await db.execute(
                    "UPDATE actions SET points = ?, action_type = ?, duration = ? WHERE id = ?",
                    (points, action_type, duration, action_id)
                )
                await db.commit()
            
            # Refresh cache
            await moderation_cog.refresh_action_cache(message.guild.id)
            
            duration_display = f" ({duration}s)" if duration else ""
            await message.reply(
                f"✅ Updated warning action #{action_index}: {points} points → {action_type}{duration_display}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to update warning action: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "edit_warning_action", False, str(e))
    
    async def _handle_delete_warning_action(self, message: discord.Message, args: dict):
        """Delete a warning action threshold."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("delete_warning_action", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", False, "Moderation cog not loaded")
            return
        
        # Get action index
        action_index = args.get("action_index", 1)
        actions = moderation_cog.action_cache.get(message.guild.id, [])
        
        if action_index < 1 or action_index > len(actions):
            await message.reply(f"❌ Invalid action index. Valid range: 1-{len(actions)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", False, "Invalid action index")
            return
        
        # Get action
        action = sorted(actions, key=lambda a: a['points'])[action_index - 1]
        action_id = action['id']
        points = action['points']
        
        # Confirm destructive action
        if not await self._confirm_destructive(message, "Confirm Warning Action Deletion", f"Are you sure you want to delete warning action at threshold **{points} points**?"):
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", False, "Cancelled by user")
            return
        
        # Delete action from database
        try:
            async with self.bot.db.acquire_db() as db:
                await db.execute("DELETE FROM actions WHERE id = ?", (action_id,))
                await db.commit()
            
            # Refresh cache
            await moderation_cog.refresh_action_cache(message.guild.id)
            
            await message.reply(
                f"✅ Deleted warning action #{action_index} ({action['points']} points → {action['action_type']})",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to delete warning action: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "delete_warning_action", False, str(e))
    
    async def _handle_toggle_message_reporting(self, message: discord.Message, args: dict):
        """Toggle message reporting on/off."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("toggle_message_reporting", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "toggle_message_reporting", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "toggle_message_reporting", False, "Moderation cog not loaded")
            return
        
        enable = args.get("enable", False)
        
        # Update setting
        try:
            val = 1 if enable else 0
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
                (message.guild.id,)
            )
            await self.bot.db.execute(
                "UPDATE moderation_settings SET msg_report_enabled = ? WHERE guild_id = ?",
                (val, message.guild.id)
            )
            
            # Refresh cache
            if message.guild.id in moderation_cog.settings_cache:
                moderation_cog.settings_cache[message.guild.id]["msg_report_enabled"] = val
            else:
                await moderation_cog.populate_caches()
            
            status = "enabled" if enable else "disabled"
            await message.reply(
                f"✅ Message reporting {status}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "toggle_message_reporting", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to toggle message reporting: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "toggle_message_reporting", False, str(e))
    
    async def _handle_set_report_channel(self, message: discord.Message, args: dict):
        """Set the channel for message reports."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("set_report_channel", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "set_report_channel", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_channel", False, "Moderation cog not loaded")
            return
        
        # Get channel
        channel_id = int(args.get("channel_id", 0))
        channel = message.guild.get_channel(channel_id)
        
        if not channel or not isinstance(channel, discord.TextChannel):
            await message.reply("❌ Invalid text channel", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_channel", False, "Invalid channel")
            return
        
        # Update setting
        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
                (message.guild.id,)
            )
            await self.bot.db.execute(
                "UPDATE moderation_settings SET msg_report_channel = ? WHERE guild_id = ?",
                (channel_id, message.guild.id)
            )
            
            # Refresh cache
            if message.guild.id in moderation_cog.settings_cache:
                moderation_cog.settings_cache[message.guild.id]["msg_report_channel"] = channel_id
            else:
                await moderation_cog.populate_caches()
            
            await message.reply(
                f"✅ Message reports will be sent to {channel.mention}",
                mention_author=False
            )
            await self._log_usage(message.guild.id, message.author.id, "set_report_channel", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to set report channel: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_channel", False, str(e))
    
    async def _handle_set_report_roles(self, message: discord.Message, args: dict):
        """Set which roles get pinged for reports."""
        # Permission check
        has_perm, missing = self.permission_validator.check_function_permission("set_report_roles", message.author)
        if not has_perm:
            await self._handle_insufficient_permissions(message, missing)
            await self._log_usage(message.guild.id, message.author.id, "set_report_roles", False, "Insufficient permissions")
            return
        
        # Get moderation cog
        moderation_cog = self.bot.get_cog("Moderation")
        if not moderation_cog:
            await message.reply("❌ Moderation system not available", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_roles", False, "Moderation cog not loaded")
            return
        
        # Get roles
        role_ids = args.get("role_ids", [])
        valid_roles = []
        
        for role_id_str in role_ids:
            role_id = int(role_id_str)
            role = message.guild.get_role(role_id)
            if role:
                valid_roles.append(str(role_id))
        
        if not valid_roles:
            await message.reply("❌ No valid roles provided", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_roles", False, "No valid roles")
            return
        
        # Update setting
        try:
            role_ids_str = ",".join(valid_roles)
            
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO moderation_settings (guild_id) VALUES (?)",
                (message.guild.id,)
            )
            await self.bot.db.execute(
                "UPDATE moderation_settings SET msg_report_roles = ? WHERE guild_id = ?",
                (role_ids_str, message.guild.id)
            )
            
            # Refresh cache
            if message.guild.id in moderation_cog.settings_cache:
                moderation_cog.settings_cache[message.guild.id]["msg_report_roles"] = role_ids_str
            else:
                await moderation_cog.populate_caches()
            
            role_mentions = [f"<@&{rid}>" for rid in valid_roles]
            await message.reply(
                f"✅ Report notifications will ping: {', '.join(role_mentions)}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await self._log_usage(message.guild.id, message.author.id, "set_report_roles", True, None)
        
        except Exception as e:
            await message.reply(f"❌ Failed to set report roles: {str(e)}", mention_author=False)
            await self._log_usage(message.guild.id, message.author.id, "set_report_roles", False, str(e))
    
    # ==================== Utility Methods ====================
    
    def _parse_id(self, val: str | int) -> int:
        """Parse ID robustly from integer, string, or mention context."""
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            match = re.search(r"\d+", val)
            if match:
                return int(match.group(0))
        try:
            return int(val)
        except Exception:
            return 0

    async def _check_guild_access(self, message: discord.Message) -> bool:
        """Check if neural commands are enabled, channel is not blocked, and user has allowed roles if configured."""
        try:
            result = await self.bot.db.execute(
                "SELECT enabled, allowed_roles, blocked_channels FROM neural_command_settings WHERE guild_id = ?",
                (message.guild.id,)
            )
            if not result:
                return True
            row = result[0]
            if not bool(row.get("enabled", 1)):
                return False
            
            # Check blocked channels
            blocked_channels_str = row.get("blocked_channels")
            if blocked_channels_str:
                blocked_ids = [int(cid) for cid in blocked_channels_str.split(",") if cid.strip().isdigit()]
                if message.channel.id in blocked_ids:
                    return False
            
            # Check allowed roles (if configured, user must have at least one unless guild owner or admin)
            if message.author.id == message.guild.owner_id or message.author.guild_permissions.administrator:
                return True
            
            allowed_roles_str = row.get("allowed_roles")
            if allowed_roles_str:
                allowed_ids = [int(rid) for rid in allowed_roles_str.split(",") if rid.strip().isdigit()]
                if allowed_ids:
                    user_role_ids = {r.id for r in message.author.roles}
                    if not any(rid in user_role_ids for rid in allowed_ids):
                        return False
            
            return True
        except Exception:
            return True

    async def _is_enabled(self, guild_id: int) -> bool:
        """Check if neural commands are enabled for a guild."""
        try:
            result = await self.bot.db.execute(
                "SELECT enabled FROM neural_command_settings WHERE guild_id = ?",
                (guild_id,)
            )
            if result and len(result) > 0:
                return bool(result[0].get("enabled", 1))
            return True  # Enabled by default
        except Exception:
            return True
    
    async def _log_usage(self, guild_id: int, user_id: int, function_name: str, success: bool, error_message: Optional[str]):
        """Log neural command usage to database."""
        try:
            await self.bot.db.execute_write(
                "INSERT INTO neural_command_usage (guild_id, user_id, function_name, success, error_message, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, function_name, int(success), error_message, int(time.time()))
            )
            
            # Also log to usage_daily for anonymous analytics
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await self.bot.db.execute_write(
                "INSERT INTO usage_daily (date, user_id, guild_id, feature_id, command_name, count) "
                "VALUES (?, 0, ?, 'neural_commands', ?, 1) "
                "ON CONFLICT(date, user_id, guild_id, feature_id, command_name) DO UPDATE SET count = count + 1",
                (date_str, guild_id, function_name)
            )
        except Exception as e:
            print(f"Failed to log neural command usage: {e}")
    
    async def _log_to_channel(self, message: discord.Message, function_name: str, args: dict, elapsed: float):
        """Log neural command execution to optional guild log channel."""
        try:
            # Get log channel
            result = await self.bot.db.execute(
                "SELECT log_channel_id FROM neural_command_settings WHERE guild_id = ?",
                (message.guild.id,)
            )
            
            if not result or not result[0].get("log_channel_id"):
                return
            
            log_channel_id = result[0]["log_channel_id"]
            log_channel = message.guild.get_channel(log_channel_id)
            
            if not log_channel:
                return
            
            # Build log embed
            embed = discord.Embed(
                title="Neural Command Executed",
                color=discord.Color.blue(),
                timestamp=message.created_at
            )
            
            embed.add_field(name="User", value=message.author.mention, inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Function", value=f"`{function_name}`", inline=True)
            
            if args:
                args_str = "\n".join([f"- {k}: `{v}`" for k, v in args.items()])
                embed.add_field(name="Arguments", value=args_str[:1024], inline=False)
            
            embed.add_field(name="Execution Time", value=f"{elapsed:.2f}s", inline=True)
            embed.add_field(name="Message", value=f"[Jump]({message.jump_url})", inline=True)
            
            await log_channel.send(embed=embed)
        
        except Exception as e:
            print(f"Failed to log to channel: {e}")

    # ==================== Admin Slash Commands ====================

    neural_group = app_commands.Group(
        name="neural",
        description="Configure Natural Language Commands",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @neural_group.command(name="enable", description="Enable Natural Language Commands in this server")
    @app_commands.guild_only()
    async def neural_enable(self, interaction: discord.Interaction):
        """Enable Natural Language Commands."""
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.acquire_db() as db:
            await db.execute("INSERT OR IGNORE INTO neural_command_settings (guild_id) VALUES (?)", (interaction.guild.id,))
            await db.execute("UPDATE neural_command_settings SET enabled = 1 WHERE guild_id = ?", (interaction.guild.id,))
            await db.commit()
        await interaction.followup.send("✅ Natural Language Commands have been **enabled** for this server.", ephemeral=True)

    @neural_group.command(name="disable", description="Disable Natural Language Commands in this server")
    @app_commands.guild_only()
    async def neural_disable(self, interaction: discord.Interaction):
        """Disable Natural Language Commands."""
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.acquire_db() as db:
            await db.execute("INSERT OR IGNORE INTO neural_command_settings (guild_id) VALUES (?)", (interaction.guild.id,))
            await db.execute("UPDATE neural_command_settings SET enabled = 0 WHERE guild_id = ?", (interaction.guild.id,))
            await db.commit()
        await interaction.followup.send("🛑 Natural Language Commands have been **disabled** for this server.", ephemeral=True)

    @neural_group.command(name="log-channel", description="Set or clear the channel for logging neural command actions")
    @app_commands.describe(channel="The channel to log neural commands in, or omit to disable logging")
    @app_commands.guild_only()
    async def neural_log_channel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Set or clear the logging channel for neural commands."""
        await interaction.response.defer(ephemeral=True)
        if channel:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.send_messages or not perms.embed_links:
                await interaction.followup.send(
                    f"❌ I don't have permission to send messages and embed links in {channel.mention}.",
                    ephemeral=True,
                )
                return
            chan_id = channel.id
            msg = f"✅ Neural command actions will now be logged to {channel.mention}."
        else:
            chan_id = None
            msg = "✅ Neural command action logging has been **disabled**."

        async with self.bot.db.acquire_db() as db:
            await db.execute("INSERT OR IGNORE INTO neural_command_settings (guild_id) VALUES (?)", (interaction.guild.id,))
            await db.execute("UPDATE neural_command_settings SET log_channel_id = ? WHERE guild_id = ?", (chan_id, interaction.guild.id))
            await db.commit()
        await interaction.followup.send(msg, ephemeral=True)

    @neural_group.command(name="status", description="Show current Neural Commands configuration and status")
    @app_commands.guild_only()
    async def neural_status(self, interaction: discord.Interaction):
        """Show current Neural Commands configuration and status."""
        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.execute(
            "SELECT enabled, log_channel_id FROM neural_command_settings WHERE guild_id = ?",
            (interaction.guild.id,)
        )
        is_enabled = True
        log_channel_str = "None (disabled)"
        if rows and len(rows) > 0:
            is_enabled = bool(rows[0].get("enabled", 1))
            log_id = rows[0].get("log_channel_id")
            if log_id:
                log_chan = interaction.guild.get_channel(log_id)
                log_channel_str = log_chan.mention if log_chan else f"Deleted Channel ({log_id})"

        embed = discord.Embed(
            title="🧠 Natural Language Commands Status",
            color=discord.Color.brand_green() if is_enabled else discord.Color.red(),
        )
        embed.add_field(name="Status", value="🟢 Enabled" if is_enabled else "🔴 Disabled", inline=True)
        embed.add_field(name="Log Channel", value=log_channel_str, inline=True)
        embed.add_field(name="Model", value=self.MODEL_NAME, inline=False)
        embed.set_footer(text="Mention the bot with an instruction to execute commands.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @neural_group.command(name="stats", description="View Neural Commands usage statistics for this server")
    @app_commands.guild_only()
    async def neural_stats(self, interaction: discord.Interaction):
        """View Neural Commands usage statistics for this server."""
        await interaction.response.defer(ephemeral=True)
        stats = await self.bot.db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count, "
            "COUNT(DISTINCT user_id) AS user_count "
            "FROM neural_command_usage WHERE guild_id = ?",
            (interaction.guild.id,)
        )
        top_funcs = await self.bot.db.execute(
            "SELECT function_name, COUNT(*) AS count "
            "FROM neural_command_usage WHERE guild_id = ? "
            "GROUP BY function_name ORDER BY count DESC LIMIT 5",
            (interaction.guild.id,)
        )

        total = stats[0]["total"] if stats and stats[0]["total"] else 0
        success_count = stats[0]["success_count"] if stats and stats[0]["success_count"] else 0
        user_count = stats[0]["user_count"] if stats and stats[0]["user_count"] else 0
        success_rate = f"{(success_count / total * 100):.1f}%" if total > 0 else "N/A"

        embed = discord.Embed(
            title="📊 Neural Commands Usage Statistics",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Total Commands", value=str(total), inline=True)
        embed.add_field(name="Success Rate", value=success_rate, inline=True)
        embed.add_field(name="Unique Users", value=str(user_count), inline=True)

        if top_funcs:
            top_str = "\n".join([f"• `{row['function_name']}`: {row['count']} executions" for row in top_funcs])
            embed.add_field(name="Top Actions", value=top_str, inline=False)
        else:
            embed.add_field(name="Top Actions", value="No commands recorded yet.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== Data Protocol ====================

    def data_features(self) -> list[DataFeatureMeta]:
        """Return features metadata for the privacy system."""
        return [
            DataFeatureMeta(
                feature_id="neural_commands",
                name="Natural Language Commands",
                guild_export=True,
                guild_delete=True,
                user_export=True,
                user_delete=True,
            )
        ]

    async def data_export_user(self, user_id: int, *, guild_ids: list[int] | None) -> DataExportChunk:
        """Export user-specific neural command usage data."""
        chunk = DataExportChunk(feature_id="neural_commands")
        if guild_ids:
            placeholders = ",".join("?" for _ in guild_ids)
            rows = await self.bot.db.execute(
                f"SELECT guild_id, function_name, success, error_message, timestamp FROM neural_command_usage WHERE user_id = ? AND guild_id IN ({placeholders})",
                (user_id, *guild_ids),
            )
        else:
            rows = await self.bot.db.execute(
                "SELECT guild_id, function_name, success, error_message, timestamp FROM neural_command_usage WHERE user_id = ?",
                (user_id,),
            )
        if rows:
            chunk.user_data["neural_command_usage"] = rows
        return chunk

    async def data_export_guild(self, guild_id: int) -> DataExportChunk:
        """Export guild-specific neural command settings and usage data."""
        chunk = DataExportChunk(feature_id="neural_commands")
        settings = await export_table(
            self.bot.db, "SELECT * FROM neural_command_settings WHERE guild_id = ?", (guild_id,)
        )
        usage = await export_table(
            self.bot.db, "SELECT function_name, success, error_message, timestamp FROM neural_command_usage WHERE guild_id = ?", (guild_id,)
        )
        chunk.guild_data[guild_id] = {
            "neural_command_settings": settings,
            "neural_command_usage": usage,
        }
        return chunk

    async def data_delete_user(
        self, user_id: int, *, guild_ids: list[int] | None, feature_id: str | None
    ) -> DataDeleteResult:
        """Delete user-specific neural command usage records."""
        if feature_id and feature_id != "neural_commands":
            return DataDeleteResult(feature_id="neural_commands")

        async with self.bot.db.acquire_db() as db:
            if guild_ids:
                placeholders = ",".join("?" for _ in guild_ids)
                count_rows = await db.execute(
                    f"SELECT COUNT(*) AS cnt FROM neural_command_usage WHERE user_id = ? AND guild_id IN ({placeholders})",
                    (user_id, *guild_ids),
                )
                rows_affected = count_rows[0]["cnt"] if count_rows else 0
                await db.execute(
                    f"DELETE FROM neural_command_usage WHERE user_id = ? AND guild_id IN ({placeholders})",
                    (user_id, *guild_ids),
                )
            else:
                count_rows = await db.execute(
                    "SELECT COUNT(*) AS cnt FROM neural_command_usage WHERE user_id = ?",
                    (user_id,),
                )
                rows_affected = count_rows[0]["cnt"] if count_rows else 0
                await db.execute(
                    "DELETE FROM neural_command_usage WHERE user_id = ?",
                    (user_id,),
                )
            await db.commit()

        return DataDeleteResult(feature_id="neural_commands", deleted=True, rows_affected=rows_affected)

    async def data_delete_guild(self, guild_id: int, feature_id: str | None) -> DataDeleteResult:
        """Delete all guild settings and usage data."""
        if feature_id and feature_id != "neural_commands":
            return DataDeleteResult(feature_id="neural_commands")

        async with self.bot.db.acquire_db() as db:
            cnt1 = await db.execute("SELECT COUNT(*) AS cnt FROM neural_command_settings WHERE guild_id = ?", (guild_id,))
            cnt2 = await db.execute("SELECT COUNT(*) AS cnt FROM neural_command_usage WHERE guild_id = ?", (guild_id,))
            rows_affected = (cnt1[0]["cnt"] if cnt1 else 0) + (cnt2[0]["cnt"] if cnt2 else 0)

            await db.execute("DELETE FROM neural_command_settings WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM neural_command_usage WHERE guild_id = ?", (guild_id,))
            await db.commit()

        return DataDeleteResult(feature_id="neural_commands", deleted=True, rows_affected=rows_affected)

    async def data_monitor_guild(self, guild: discord.Guild) -> DataMonitorResult:
        """Monitor guild health: verify configured log channel still exists."""
        result = DataMonitorResult(feature_id="neural_commands")
        settings = await self.bot.db.execute(
            "SELECT log_channel_id FROM neural_command_settings WHERE guild_id = ?",
            (guild.id,)
        )
        if settings and settings[0].get("log_channel_id"):
            log_chan_id = settings[0]["log_channel_id"]
            channel = guild.get_channel(log_chan_id)
            if not channel:
                async with self.bot.db.acquire_db() as db:
                    await db.execute(
                        "UPDATE neural_command_settings SET log_channel_id = NULL WHERE guild_id = ?",
                        (guild.id,)
                    )
                    await db.commit()
                result.actions.append(f"cleared_missing_log_channel:{log_chan_id}")
        return result


async def setup(bot):
    await bot.add_cog(NeuralCommands(bot))
