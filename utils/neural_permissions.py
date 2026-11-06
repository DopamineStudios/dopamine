"""
Neural Commands Permission Validation
Two-stage permission checking: pre-LLM gate and per-function validation.
"""

from typing import Optional

import discord


class PermissionValidator:
    """Validates user permissions for neural command operations."""
    
    # Permission requirements for each function category
    FUNCTION_PERMISSIONS = {
        # Role management
        "create_role": ["manage_roles"],
        "update_role": ["manage_roles"],
        "assign_role": ["manage_roles"],
        "remove_role": ["manage_roles"],
        "delete_role": ["manage_roles"],
        
        # Channel management
        "create_channel": ["manage_channels"],
        "update_channel": ["manage_channels"],
        "create_category": ["manage_channels"],
        "delete_channel": ["manage_channels"],
        
        # Nickname management
        "set_nickname": ["manage_nicknames"],
        "clear_nickname": ["manage_nicknames"],
        
        # User information (no permissions required)
        "get_user_info": [],
        "get_avatar": [],
        
        # Moderation
        "warn_user": ["moderate_members"],
        "edit_moderation_setting": ["manage_guild"],
        "edit_warning_action": ["manage_guild"],
        "delete_warning_action": ["manage_guild"],
        "toggle_message_reporting": ["manage_guild"],
        "set_report_channel": ["manage_guild"],
        "set_report_roles": ["manage_guild"],
        
        # Dismissals (no permissions required)
        "dismiss": [],
        "not_supported": [],
        "missing_mention": [],
        "insufficient_permissions": [],
    }
    
    def __init__(self, bot):
        self.bot = bot
    
    def check_pre_llm_permissions(self, member: discord.Member) -> tuple[bool, Optional[list[str]]]:
        """
        Pre-LLM permission gate.
        Check if user has ANY management permission to use neural commands.
        Returns (has_permission, missing_permissions_list)
        """
        required_any = [
            "manage_roles",
            "manage_channels",
            "manage_nicknames",
            "moderate_members",
            "manage_guild"
        ]
        
        perms = member.guild_permissions
        
        # Check if user has at least one management permission
        has_any = any([
            perms.manage_roles,
            perms.manage_channels,
            perms.manage_nicknames,
            perms.moderate_members,
            perms.manage_guild
        ])
        
        if has_any:
            return True, None
        
        return False, required_any
    
    def check_function_permission(
        self,
        function_name: str,
        member: discord.Member
    ) -> tuple[bool, Optional[list[str]]]:
        """
        Per-function permission check.
        Returns (has_permission, missing_permissions_list)
        """
        required_perms = self.FUNCTION_PERMISSIONS.get(function_name, [])
        
        # No permissions required
        if not required_perms:
            return True, None
        
        perms = member.guild_permissions
        missing = []
        
        for perm_name in required_perms:
            if not getattr(perms, perm_name, False):
                missing.append(perm_name)
        
        if missing:
            return False, missing
        
        return True, None
    
    def check_role_hierarchy(
        self,
        member: discord.Member,
        target_role: discord.Role
    ) -> tuple[bool, Optional[str]]:
        """
        Check if member can manage a specific role based on hierarchy.
        Returns (can_manage, error_reason)
        """
        # Owner can do anything
        if member.id == member.guild.owner_id:
            return True, None
        
        # Check if member's top role is higher than target role
        if member.top_role <= target_role:
            return False, f"Your highest role ({member.top_role.name}) is not above the target role ({target_role.name})"
        
        # Check if bot's top role is higher than target role
        bot_member = member.guild.get_member(self.bot.user.id)
        if bot_member and bot_member.top_role <= target_role:
            return False, f"Bot's highest role is not above the target role ({target_role.name})"
        
        return True, None
    
    def check_member_hierarchy(
        self,
        actor: discord.Member,
        target: discord.Member,
        is_moderation: bool = True
    ) -> tuple[bool, Optional[str]]:
        """
        Check if actor can perform actions on target member based on role hierarchy.
        Returns (can_act, error_reason)
        """
        # Owner can act on anyone except themselves (unless not moderation)
        if actor.id == actor.guild.owner_id:
            if target.id == actor.guild.owner_id and is_moderation:
                return False, "Cannot perform actions on the server owner"
            return True, None
        
        # Can't act on server owner
        if target.id == target.guild.owner_id:
            return False, "Cannot perform actions on the server owner"
        
        # Can't act on self for moderation actions
        if actor.id == target.id:
            if is_moderation:
                return False, "Cannot perform this action on yourself"
            return True, None
        
        # Check role hierarchy
        if actor.top_role <= target.top_role:
            return False, f"Your highest role is not above {target.display_name}'s highest role"
        
        # Check if bot can act on target
        bot_member = actor.guild.get_member(self.bot.user.id)
        if bot_member and bot_member.top_role <= target.top_role:
            return False, f"Bot's highest role is not above {target.display_name}'s highest role"
        
        return True, None
    
    def check_channel_permissions(
        self,
        member: discord.Member,
        channel: discord.abc.GuildChannel
    ) -> tuple[bool, Optional[str]]:
        """
        Check if member can manage a specific channel.
        Returns (can_manage, error_reason)
        """
        if not member.guild_permissions.manage_channels:
            return False, "You need 'Manage Channels' permission"
        
        # Check if member has manage permission in the channel
        channel_perms = channel.permissions_for(member)
        if not channel_perms.manage_channels:
            return False, f"You don't have permission to manage #{channel.name}"
        
        return True, None
    
    def validate_nickname_length(self, nickname: str) -> tuple[bool, Optional[str]]:
        """
        Validate nickname constraints.
        Returns (is_valid, error_reason)
        """
        if len(nickname) > 32:
            return False, f"Nickname too long ({len(nickname)}/32 characters)"
        
        if len(nickname) < 1:
            return False, "Nickname cannot be empty"
        
        return True, None
    
    def validate_channel_name(self, name: str, channel_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate channel name constraints.
        Returns (is_valid, error_reason)
        """
        if len(name) > 100:
            return False, f"Channel name too long ({len(name)}/100 characters)"
        
        if len(name) < 1:
            return False, "Channel name cannot be empty"
        
        # Text/voice channels can't have spaces or special characters
        if channel_type in ["text", "voice"]:
            if not name.replace("-", "").replace("_", "").isalnum():
                return False, "Channel name can only contain letters, numbers, hyphens, and underscores"
        
        return True, None
    
    def validate_role_name(self, name: str) -> tuple[bool, Optional[str]]:
        """
        Validate role name constraints.
        Returns (is_valid, error_reason)
        """
        if len(name) > 100:
            return False, f"Role name too long ({len(name)}/100 characters)"
        
        if len(name) < 1:
            return False, "Role name cannot be empty"
        
        return True, None
    
    def validate_slowmode(self, seconds: int) -> tuple[bool, Optional[str]]:
        """
        Validate slowmode constraints.
        Returns (is_valid, error_reason)
        """
        if seconds < 0:
            return False, "Slowmode cannot be negative"
        
        if seconds > 21600:  # 6 hours max
            return False, "Slowmode cannot exceed 6 hours (21600 seconds)"
        
        return True, None
    
    def get_permission_name_readable(self, perm_name: str) -> str:
        """Convert permission name to human-readable format."""
        readable = {
            "manage_roles": "Manage Roles",
            "manage_channels": "Manage Channels",
            "manage_nicknames": "Manage Nicknames",
            "moderate_members": "Moderate Members",
            "manage_guild": "Manage Server",
            "kick_members": "Kick Members",
            "ban_members": "Ban Members",
            "manage_messages": "Manage Messages",
        }
        return readable.get(perm_name, perm_name.replace("_", " ").title())
    
    def format_missing_permissions(self, missing_perms: list[str]) -> str:
        """Format missing permissions list for user-friendly message."""
        readable = [self.get_permission_name_readable(p) for p in missing_perms]
        
        if len(readable) == 1:
            return readable[0]
        elif len(readable) == 2:
            return f"{readable[0]} and {readable[1]}"
        else:
            return ", ".join(readable[:-1]) + f", and {readable[-1]}"
