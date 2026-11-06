"""
Neural Commands Function Registry
Defines all available functions for the LLM to call via function calling API.
"""

from google.genai import types


class NeuralFunctionRegistry:
    """Registry of all neural command functions with their schemas."""
    
    def __init__(self):
        self.functions = self._build_function_declarations()
        self.tool = types.Tool(function_declarations=list(self.functions.values()))
    
    def _build_function_declarations(self) -> dict[str, types.FunctionDeclaration]:
        """Build all function declarations for the LLM."""
        return {
            # Dismissal responses (4 functions)
            "dismiss": types.FunctionDeclaration(
                name="dismiss",
                description="Politely decline the request without providing a reason. Use when the request is clearly out of scope or inappropriate.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
                    required=[]
                )
            ),
            "not_supported": types.FunctionDeclaration(
                name="not_supported",
                description="Explain that a specific feature or action is not currently supported.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "reason": types.Schema(
                            type=types.Type.STRING,
                            description="Brief explanation of what isn't supported and why"
                        )
                    },
                    required=["reason"]
                )
            ),
            "missing_mention": types.FunctionDeclaration(
                name="missing_mention",
                description="Request the user to mention a required target (user, role, or channel) that was not provided.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "missing_what": types.Schema(
                            type=types.Type.STRING,
                            description="What type of mention is missing (e.g., 'user', 'role', 'channel')"
                        )
                    },
                    required=["missing_what"]
                )
            ),
            "insufficient_permissions": types.FunctionDeclaration(
                name="insufficient_permissions",
                description="Inform the user they lack required permissions to perform the requested action.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "required_permissions": types.Schema(
                            type=types.Type.ARRAY,
                            description="List of permission names required",
                            items=types.Schema(type=types.Type.STRING)
                        )
                    },
                    required=["required_permissions"]
                )
            ),
            
            # Role management functions (5 functions)
            "create_role": types.FunctionDeclaration(
                name="create_role",
                description="Create a new role with specified properties. Color must be from the standard palette provided in context.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="Name for the new role"
                        ),
                        "color": types.Schema(
                            type=types.Type.STRING,
                            description="Color name from the standard palette (e.g., 'red', 'blue', 'green')"
                        ),
                        "permissions": types.Schema(
                            type=types.Type.ARRAY,
                            description="List of permission names to grant (e.g., ['manage_messages', 'kick_members'])",
                            items=types.Schema(type=types.Type.STRING)
                        ),
                        "hoist": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="Whether to display role members separately in the sidebar"
                        ),
                        "mentionable": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="Whether the role can be mentioned by others"
                        )
                    },
                    required=["name"]
                )
            ),
            "update_role": types.FunctionDeclaration(
                name="update_role",
                description="Update an existing role's properties. Only include parameters that should be changed.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "role_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the role to update (extracted from role mention)"
                        ),
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="New name for the role"
                        ),
                        "color": types.Schema(
                            type=types.Type.STRING,
                            description="New color from the standard palette"
                        ),
                        "permissions": types.Schema(
                            type=types.Type.ARRAY,
                            description="New permission list",
                            items=types.Schema(type=types.Type.STRING)
                        ),
                        "hoist": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="Whether to display separately"
                        ),
                        "mentionable": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="Whether the role can be mentioned"
                        ),
                        "position": types.Schema(
                            type=types.Type.INTEGER,
                            description="New position in role hierarchy (higher = more powerful)"
                        )
                    },
                    required=["role_id"]
                )
            ),
            "assign_role": types.FunctionDeclaration(
                name="assign_role",
                description="Assign a role to a user.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user to assign the role to"
                        ),
                        "role_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the role to assign"
                        )
                    },
                    required=["user_id", "role_id"]
                )
            ),
            "remove_role": types.FunctionDeclaration(
                name="remove_role",
                description="Remove a role from a user.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user to remove the role from"
                        ),
                        "role_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the role to remove"
                        )
                    },
                    required=["user_id", "role_id"]
                )
            ),
            "delete_role": types.FunctionDeclaration(
                name="delete_role",
                description="Permanently delete a role from the server.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "role_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the role to delete"
                        )
                    },
                    required=["role_id"]
                )
            ),
            
            # Channel management functions (4 functions)
            "create_channel": types.FunctionDeclaration(
                name="create_channel",
                description="Create a new text or voice channel, optionally within a category.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="Name for the new channel"
                        ),
                        "channel_type": types.Schema(
                            type=types.Type.STRING,
                            description="Type of channel: 'text' or 'voice'",
                            enum=["text", "voice"]
                        ),
                        "category_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the category to place channel in (optional)"
                        ),
                        "position": types.Schema(
                            type=types.Type.INTEGER,
                            description="Position within its category (optional)"
                        )
                    },
                    required=["name", "channel_type"]
                )
            ),
            "update_channel": types.FunctionDeclaration(
                name="update_channel",
                description="Update an existing channel's properties. Only include parameters that should be changed.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "channel_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the channel to update"
                        ),
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="New name for the channel"
                        ),
                        "category_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of category to move channel to (use 'none' to remove from category)"
                        ),
                        "position": types.Schema(
                            type=types.Type.INTEGER,
                            description="New position within its category"
                        ),
                        "topic": types.Schema(
                            type=types.Type.STRING,
                            description="New topic/description (text channels only)"
                        ),
                        "slowmode": types.Schema(
                            type=types.Type.INTEGER,
                            description="Slowmode delay in seconds (0-21600, text channels only)"
                        )
                    },
                    required=["channel_id"]
                )
            ),
            "create_category": types.FunctionDeclaration(
                name="create_category",
                description="Create a new category to organize channels.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="Name for the new category"
                        ),
                        "position": types.Schema(
                            type=types.Type.INTEGER,
                            description="Position in the channel list (optional)"
                        )
                    },
                    required=["name"]
                )
            ),
            "delete_channel": types.FunctionDeclaration(
                name="delete_channel",
                description="Permanently delete a channel or category.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "channel_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the channel or category to delete"
                        )
                    },
                    required=["channel_id"]
                )
            ),
            
            # Nickname management functions (2 functions)
            "set_nickname": types.FunctionDeclaration(
                name="set_nickname",
                description="Set or change a user's nickname in the server.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user whose nickname to set"
                        ),
                        "nickname": types.Schema(
                            type=types.Type.STRING,
                            description="New nickname (max 32 characters)"
                        )
                    },
                    required=["user_id", "nickname"]
                )
            ),
            "clear_nickname": types.FunctionDeclaration(
                name="clear_nickname",
                description="Remove a user's nickname, reverting to their Discord username.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user whose nickname to clear"
                        )
                    },
                    required=["user_id"]
                )
            ),
            
            # User information functions (2 functions)
            "get_user_info": types.FunctionDeclaration(
                name="get_user_info",
                description="Retrieve detailed information about a user including roles, join date, and current status.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user to get information about"
                        )
                    },
                    required=["user_id"]
                )
            ),
            "get_avatar": types.FunctionDeclaration(
                name="get_avatar",
                description="Get a user's avatar image URL and display it in an embed.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user whose avatar to display"
                        ),
                        "size": types.Schema(
                            type=types.Type.INTEGER,
                            description="Avatar size in pixels: 16, 32, 64, 128, 256, 512, 1024, 2048, or 4096 (default: 1024)"
                        )
                    },
                    required=["user_id"]
                )
            ),
            
            # Moderation functions (7 functions)
            "warn_user": types.FunctionDeclaration(
                name="warn_user",
                description="Issue a warning to a user, adding points to their moderation record. This may trigger automatic punishments based on warning thresholds.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "user_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the user to warn"
                        ),
                        "amount": types.Schema(
                            type=types.Type.INTEGER,
                            description="Number of warning points to add (default: 1)"
                        ),
                        "reason": types.Schema(
                            type=types.Type.STRING,
                            description="Reason for the warning"
                        )
                    },
                    required=["user_id", "reason"]
                )
            ),
            "edit_moderation_setting": types.FunctionDeclaration(
                name="edit_moderation_setting",
                description="Modify a moderation dashboard setting. Available settings: punishment_dm, punishment_log, simple_mode, decay_interval, rejoin_points, decay_log_enabled, show_medals.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "setting_name": types.Schema(
                            type=types.Type.STRING,
                            description="Name of the setting to change",
                            enum=["punishment_dm", "punishment_log", "simple_mode", "decay_interval", "rejoin_points", "decay_log_enabled", "show_medals"]
                        ),
                        "new_value": types.Schema(
                            type=types.Type.STRING,
                            description="New value for the setting (will be converted to appropriate type)"
                        )
                    },
                    required=["setting_name", "new_value"]
                )
            ),
            "edit_warning_action": types.FunctionDeclaration(
                name="edit_warning_action",
                description="Modify an existing warning action threshold (punishment triggered at specific warning points).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "action_index": types.Schema(
                            type=types.Type.INTEGER,
                            description="Index of the action to edit (1-based, from warning actions list)"
                        ),
                        "points": types.Schema(
                            type=types.Type.INTEGER,
                            description="Warning points threshold to trigger this action"
                        ),
                        "action_type": types.Schema(
                            type=types.Type.STRING,
                            description="Type of warning action",
                            enum=["warning"]
                        ),
                        "duration": types.Schema(
                            type=types.Type.STRING,
                            description="Duration for temporary punishments (e.g., '1h', '3d', '1w'). Required for mute/ban."
                        )
                    },
                    required=["action_index"]
                )
            ),
            "delete_warning_action": types.FunctionDeclaration(
                name="delete_warning_action",
                description="Remove a warning action threshold from the moderation system.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "action_index": types.Schema(
                            type=types.Type.INTEGER,
                            description="Index of the action to delete (1-based, from warning actions list)"
                        )
                    },
                    required=["action_index"]
                )
            ),
            "toggle_message_reporting": types.FunctionDeclaration(
                name="toggle_message_reporting",
                description="Enable or disable the message reporting system.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "enable": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="True to enable, False to disable"
                        )
                    },
                    required=["enable"]
                )
            ),
            "set_report_channel": types.FunctionDeclaration(
                name="set_report_channel",
                description="Set the channel where message reports are sent.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "channel_id": types.Schema(
                            type=types.Type.STRING,
                            description="ID of the channel to send reports to"
                        )
                    },
                    required=["channel_id"]
                )
            ),
            "set_report_roles": types.FunctionDeclaration(
                name="set_report_roles",
                description="Set which roles get pinged when a message is reported.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "role_ids": types.Schema(
                            type=types.Type.ARRAY,
                            description="List of role IDs to ping on reports",
                            items=types.Schema(type=types.Type.STRING)
                        )
                    },
                    required=["role_ids"]
                )
            ),
        }
    
    def get_function(self, name: str) -> types.FunctionDeclaration:
        """Get a specific function declaration by name."""
        return self.functions.get(name)
    
    def get_all_function_names(self) -> list[str]:
        """Get list of all registered function names."""
        return list(self.functions.keys())


# Global registry instance
registry = NeuralFunctionRegistry()
