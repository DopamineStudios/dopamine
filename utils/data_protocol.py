from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DataFeatureMeta:
    feature_id: str
    name: str
    user_export: bool = False
    user_delete: bool = False
    guild_export: bool = False
    guild_delete: bool = False
    user_delete_note: Optional[str] = None


@dataclass
class DataExportChunk:
    feature_id: str
    global_data: dict[str, Any] = field(default_factory=dict)
    guild_data: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DataDeleteResult:
    feature_id: str
    deleted: bool = False
    rows_affected: int = 0
    message: str = ""


@dataclass
class DataMonitorResult:
    feature_id: str
    actions: list[str] = field(default_factory=list)


COG_NAME_BY_FEATURE: dict[str, str] = {
    "moderation": "Points",
    "welcome": "Welcome",
    "leave": "Leaves",
    "afk": "AFK",
    "factorial": "FactorialCog",
    "haiku": "HaikuDetector",
    "member_tracker": "MemberCountTracker",
    "logging": "Logging",
    "nickname": "Nickname",
    "embeds": "Embeds",
    "autoresponse": "Autoresponse",
    "notes": "Notes",
    "daily": "DailyCats",
    "selfpurge": "SelfPurge",
    "repeating_messages": "RepeatingMessages",
    "autopublish": "AutoPublish",
    "sticky_messages": "StickyMessages",
    "slowmode": "ScheduledSlowmode",
    "skullboard": "SkullboardCog",
    "starboard": "StarboardCog",
    "temphide": "TempHideCog",
    "discordphone": "DiscordPhone",
    "giveaway": "Giveaways",
    "autoreact": "AutoReact",
    "alerts": "Alerts",
    "topgg": "TopGGVoter",
    "usage": "Data",
}

COMMAND_PREFIX_TO_FEATURE: dict[str, str] = {
    "moderation": "moderation",
    "point": "moderation",
    "warn": "moderation",
    "pardon": "moderation",
    "unban": "moderation",
    "points": "moderation",
    "warnings": "moderation",
    "case": "moderation",
    "pending": "moderation",
    "welcome": "welcome",
    "goodbye": "leave",
    "leave": "leave",
    "afk": "afk",
    "factorial": "factorial",
    "haiku": "haiku",
    "member": "member_tracker",
    "logging": "logging",
    "nickname": "nickname",
    "embed": "embeds",
    "autoresponse": "autoresponse",
    "note": "notes",
    "cat": "daily",
    "selfpurge": "selfpurge",
    "repeating": "repeating_messages",
    "autopublish": "autopublish",
    "sticky": "sticky_messages",
    "slowmode": "slowmode",
    "skullboard": "skullboard",
    "starboard": "starboard",
    "discordphone": "discordphone",
    "giveaway": "giveaway",
    "autoreact": "autoreact",
    "data": "usage",
    "help": "help",
    "di": "usage",
}

EXPORT_DEBOUNCE_SECONDS = 90
EXPORT_COOLDOWN_SECONDS = 86400
BACKUP_INTERVAL_DAYS = 3
GUILD_RETENTION_DAYS = 30
