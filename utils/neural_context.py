"""
Neural Commands Context Enrichment
Handles mention resolution and system prompt construction with full server context.
"""

import re
from typing import Optional

import discord


class NeuralContextBuilder:
    """Builds enriched context for neural command processing."""
    
    # Regex patterns (from Twilight chat.py)
    USER_MENTION_PATTERN = re.compile(r'<@!?(\d+)>')
    ROLE_MENTION_PATTERN = re.compile(r'<@&(\d+)>')
    CHANNEL_MENTION_PATTERN = re.compile(r'<#(\d+)>')
    
    # Standard color palette (hex values)
    COLOR_PALETTE = {
        "red": 0xE74C3C,
        "orange": 0xE67E22,
        "yellow": 0xF1C40F,
        "green": 0x2ECC71,
        "teal": 0x1ABC9C,
        "blue": 0x3498DB,
        "dark_blue": 0x206694,
        "purple": 0x9B59B6,
        "magenta": 0xE91E63,
        "pink": 0xF47FFF,
        "white": 0xFFFFFF,
        "light_grey": 0xBCC0C0,
        "grey": 0x95A5A6,
        "dark_grey": 0x607D8B,
        "darker_grey": 0x546E7A,
        "black": 0x000000,
        "gold": 0xF1C40F,
        "blurple": 0x5865F2,
    }
    
    def __init__(self, bot, moderation_cog=None):
        self.bot = bot
        self.moderation_cog = moderation_cog
    
    async def replace_mentions(self, text: str, guild: discord.Guild) -> str:
        """
        Replace Discord mentions with enriched context.
        Pattern from Twilight chat.py lines 735-774.
        """
        result_parts = []
        last_idx = 0
        
        # Find all mentions in order
        all_mentions = []
        for match in self.USER_MENTION_PATTERN.finditer(text):
            all_mentions.append(('user', match))
        for match in self.ROLE_MENTION_PATTERN.finditer(text):
            all_mentions.append(('role', match))
        for match in self.CHANNEL_MENTION_PATTERN.finditer(text):
            all_mentions.append(('channel', match))
        
        # Sort by position in text
        all_mentions.sort(key=lambda x: x[1].start())
        
        for mention_type, match in all_mentions:
            start, end = match.span()
            entity_id = int(match.group(1))
            
            # Add text before mention
            result_parts.append(text[last_idx:start])
            
            # Replace mention with enriched context
            if mention_type == 'user':
                member = guild.get_member(entity_id)
                if member:
                    roles_str = ", ".join([r.name for r in member.roles[1:]]) if len(member.roles) > 1 else "None"
                    replacement = (
                        f"@{member.display_name} "
                        f"(User ID: {member.id}, "
                        f"Username: {member.name}, "
                        f"Roles: {roles_str})"
                    )
                else:
                    try:
                        user = await self.bot.fetch_user(entity_id)
                        replacement = f"@{user.name} (User ID: {user.id}, Not in server)"
                    except:
                        replacement = f"<Unknown User {entity_id}>"
                result_parts.append(replacement)
            
            elif mention_type == 'role':
                role = guild.get_role(entity_id)
                if role:
                    member_count = len(role.members)
                    replacement = (
                        f"@{role.name} "
                        f"(Role ID: {role.id}, "
                        f"Members: {member_count}, "
                        f"Color: {role.color}, "
                        f"Position: {role.position})"
                    )
                else:
                    replacement = f"<Unknown Role {entity_id}>"
                result_parts.append(replacement)
            
            elif mention_type == 'channel':
                channel = guild.get_channel(entity_id)
                if channel:
                    if isinstance(channel, discord.TextChannel):
                        replacement = (
                            f"#{channel.name} "
                            f"(Channel ID: {channel.id}, "
                            f"Type: Text, "
                            f"Category: {channel.category.name if channel.category else 'None'})"
                        )
                    elif isinstance(channel, discord.VoiceChannel):
                        replacement = (
                            f"#{channel.name} "
                            f"(Channel ID: {channel.id}, "
                            f"Type: Voice, "
                            f"Category: {channel.category.name if channel.category else 'None'})"
                        )
                    elif isinstance(channel, discord.CategoryChannel):
                        replacement = (
                            f"Category: {channel.name} "
                            f"(Category ID: {channel.id}, "
                            f"Channels: {len(channel.channels)})"
                        )
                    else:
                        replacement = f"#{channel.name} (Channel ID: {channel.id})"
                else:
                    replacement = f"<Unknown Channel {entity_id}>"
                result_parts.append(replacement)
            
            last_idx = end
        
        # Add remaining text
        result_parts.append(text[last_idx:])
        
        return ''.join(result_parts)
    
    async def get_moderation_context(self, guild: discord.Guild) -> dict:
        """
        Retrieve complete moderation dashboard context.
        Includes settings, warning actions, and message reporting config.
        """
        if not self.moderation_cog:
            return {}
        
        guild_id = guild.id
        
        # Get moderation settings
        settings = self.moderation_cog.settings_cache.get(guild_id, {})
        
        # Get warning actions (sorted by points)
        actions = self.moderation_cog.action_cache.get(guild_id, [])
        actions_list = []
        for action in sorted(actions, key=lambda a: a['points']):
            action_str = f"{action['points']} points → {action['action_type']}"
            if action.get('duration'):
                action_str += f" ({action['duration']}s)"
            actions_list.append(action_str)
        
        # Format moderation context
        context = {
            "settings": {
                "punishment_dm": bool(settings.get("punishment_dm", 1)),
                "punishment_log": bool(settings.get("punishment_log", 1)),
                "simple_mode": bool(settings.get("simple_mode", 0)),
                "decay_interval": settings.get("decay_interval", 14),  # 14 days default
                "rejoin_points": settings.get("rejoin_points", 0),
                "decay_log_enabled": bool(settings.get("decay_log_enabled", 0)),
                "show_medals": bool(settings.get("show_medals", 1)),
            },
            "warning_actions": actions_list,
            "message_reporting": {
                "enabled": bool(settings.get("msg_report_enabled", 0)),
                "channel_id": settings.get("msg_report_channel"),
                "role_ids": settings.get("msg_report_roles", "").split(",") if settings.get("msg_report_roles") else [],
            }
        }
        
        return context
    
    async def get_user_warning_count(self, guild: discord.Guild, user_id: int) -> dict:
        """Get a user's current warning/point count."""
        if not self.moderation_cog:
            return {"warnings": 0, "points": 0}
        
        user_data = await self.moderation_cog.get_user_data(guild.id, user_id)
        return {
            "warnings": user_data.get("warnings", 0),
            "points": user_data.get("points", 0)
        }
    
    def get_category_channels(self, guild: discord.Guild) -> list[dict]:
        """
        Get all category channels with IDs.
        Discord can't mention categories, so we provide ID explicitly.
        """
        categories = []
        for category in guild.categories:
            categories.append({
                "name": category.name,
                "id": category.id,
                "position": category.position,
                "channels": len(category.channels)
            })
        return sorted(categories, key=lambda c: c["position"])
    
    def get_color_palette_str(self) -> str:
        """Format color palette for system prompt."""
        lines = []
        for color_name, hex_value in self.COLOR_PALETTE.items():
            lines.append(f"  - {color_name}: #{hex_value:06X}")
        return "\n".join(lines)
    
    async def build_system_prompt(
        self,
        guild: discord.Guild,
        user: discord.Member,
        enriched_message: str
    ) -> str:
        """
        Build complete system prompt with all context.
        Based on architecture document system prompt template.
        """
        # Get moderation context
        mod_context = await self.get_moderation_context(guild)
        
        # Get category channels
        categories = self.get_category_channels(guild)
        categories_str = "\n".join([
            f"  - {cat['name']} (ID: {cat['id']}, Position: {cat['position']}, Channels: {cat['channels']})"
            for cat in categories
        ])
        
        # Format moderation settings
        settings = mod_context.get("settings", {})
        settings_str = "\n".join([
            f"  - punishment_dm: {settings.get('punishment_dm', True)}",
            f"  - punishment_log: {settings.get('punishment_log', True)}",
            f"  - simple_mode: {settings.get('simple_mode', False)}",
            f"  - decay_interval: {settings.get('decay_interval', 2592000)} seconds",
            f"  - rejoin_points: {settings.get('rejoin_points', 0)}",
            f"  - decay_log_enabled: {settings.get('decay_log_enabled', False)}",
            f"  - show_medals: {settings.get('show_medals', True)}",
        ])
        
        # Format warning actions
        actions = mod_context.get("warning_actions", [])
        if actions:
            actions_str = "\n".join([f"  - {action}" for action in actions])
        else:
            actions_str = "  - No warning actions configured"
        
        # Format message reporting
        msg_report = mod_context.get("message_reporting", {})
        msg_report_channel = "Not set"
        if msg_report.get("channel_id"):
            channel = guild.get_channel(int(msg_report["channel_id"]))
            if channel:
                msg_report_channel = f"#{channel.name} (ID: {channel.id})"
        
        msg_report_roles = "None"
        if msg_report.get("role_ids"):
            role_names = []
            for role_id in msg_report["role_ids"]:
                if role_id:
                    role = guild.get_role(int(role_id))
                    if role:
                        role_names.append(role.name)
            if role_names:
                msg_report_roles = ", ".join(role_names)
        
        # Build system prompt
        system_prompt = f"""You are a Discord server management assistant. Your role is to interpret natural language commands and execute appropriate actions via function calling. You NEVER output text—only structured function calls.

## Server Context
Server: {guild.name} (ID: {guild.id})
Total Members: {guild.member_count}
User: {user.display_name} (ID: {user.id})
User Permissions: {", ".join([p[0] for p in user.guild_permissions if p[1]])}

## Category Channels (with IDs)
Discord cannot mention categories, so use these IDs directly:
{categories_str}

## Standard Color Palette
When creating or updating roles, use these color names:
{self.get_color_palette_str()}

## Moderation Settings
Current dashboard configuration:
{settings_str}

## Warning Actions
Automatic punishments triggered at warning thresholds:
{actions_str}

## Message Reporting
- Enabled: {msg_report.get('enabled', False)}
- Report Channel: {msg_report_channel}
- Ping Roles: {msg_report_roles}

## Response Rules
1. NEVER output text. Always call a function.
2. Use `dismiss()` for clearly inappropriate requests.
3. Use `not_supported(reason)` for unsupported features.
4. Use `missing_mention(missing_what)` when required mentions are absent.
5. Use `insufficient_permissions(required_permissions)` when user lacks permissions.
6. Extract IDs from enriched mention context (format: "ID: 123456789").
7. For colors, use color names from the palette (e.g., "blue", "red").
8. For categories in channel operations, use category IDs from the list above.
9. Validate that requested operations are sensible before calling functions.
10. For moderation settings, use exact setting names from the list above.

## User's Message
{enriched_message}"""
        
        return system_prompt
    
    def extract_id_from_mention(self, text: str, mention_type: str) -> Optional[int]:
        """
        Extract ID from enriched mention text.
        Example: "@User (User ID: 123456789, ...)" -> 123456789
        """
        patterns = {
            "user": r"User ID:\s*(\d+)",
            "role": r"Role ID:\s*(\d+)",
            "channel": r"(?:Channel|Category) ID:\s*(\d+)",
        }
        
        pattern = patterns.get(mention_type)
        if not pattern:
            return None
        
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
        return None
    
    def get_color_hex(self, color_name: str) -> Optional[int]:
        """Get hex color value from palette name."""
        return self.COLOR_PALETTE.get(color_name.lower())
