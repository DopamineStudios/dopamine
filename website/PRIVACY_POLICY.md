# Dopamine Bot Privacy Policy

<sub>Last Updated: 1 July 2026</sub>

Dopamine (“the Bot”) respects your privacy. This policy explains what data is collected, stored, used, and deleted while you interact with the Bot on Discord.

### Definition
“Personal data” means any information that can be used to identify an individual user, directly or indirectly.

---

## 1. Data Collection & Storage
The Bot collects and stores only the data necessary to operate its features. All persistent data is stored securely in **Turso** (cloud database) and/or locally on the Bot’s host device in secured SQLite databases. It is not sold, shared with advertisers, or uploaded to third-party cloud analytics platforms.

### Identifiers and configuration
The Bot may store:
- User IDs and Guild (server) IDs
- Channel, role, and emoji IDs used in feature configuration
- Guild names (for display, exports, and operational records)
- Timestamps related to moderation, scheduling, voting, and feature activity

### Feature-specific data
Depending on which features are enabled in a server, the Bot may also store:
- **Moderation data** — points, warnings, cases, infractions, ban schedules, pending punishments, and moderation settings
- **Logging configuration** — designated log channel IDs
- **Welcome / goodbye settings** — message templates, embed settings, and optional custom background images
- **Notes** — user-created note titles and content (provided voluntarily)
- **AFK status** — status text, timestamps, and optionally missed-message metadata (including message content when “save missed pings” is enabled)
- **Giveaway data** — giveaway settings, participant entries, and winner records
- **Automation content** — sticky messages, repeating/scheduled messages, autoresponse triggers and replies, autoreact panel settings, embed templates, and similar server-configured text
- **Starboard / Skullboard records** — settings and mappings between source messages and board posts (message IDs; content remains on Discord unless copied into board embeds)
- **Member tracker, slowmode, autopublish, haiku, factorial, nickname, self-purge, TempHide, DiscordPhone, alerts, and other feature data** as required for those features to function
- **Top.gg vote records** — user IDs and vote/check timestamps (see Section 6)

### Operational and privacy-system data
The Bot also maintains local and cloud records to support reliability, transparency, and your privacy rights:
- **Usage analytics** — daily counts of slash-command usage by user ID, guild ID, feature, and command name (aggregated operational statistics only)
- **Export queue metadata** — who requested an export, scope, status, and timestamps
- **Health monitor logs** — when features are automatically disabled due to missing guild/channel access
- **Backup logs** — filenames, sizes, and status of database backups
- **Guild lifecycle data** — who invited the Bot, when the Bot joined or was removed, and optional removal feedback if submitted
- **Scheduled guild purge records** — when server data is queued for deletion after the Bot is removed

### Message content
The Bot does not log or permanently store general chat messages. Message content may be stored only when:
- A user or administrator voluntarily configures it (e.g. notes, sticky messages, scheduled messages, autoresponses, TempHide messages, welcome/goodbye templates).
- A feature temporarily processes it to perform a task (e.g. moderation commands, haiku detection, starboard/skullboard reactions).
- A user enables features that retain specific message metadata (e.g. AFK missed pings).

Except where noted above, messages are processed in memory for the duration of the task and are not kept as a general message archive.

---

## 2. Data Usage
Stored data is used solely to operate, secure, and improve the Bot’s core functionality. The Bot uses data to:
- Enforce and log moderation actions
- Run server automation (welcome/goodbye messages, sticky messages, repeating messages, autoresponse, giveaways, starboard/skullboard, DiscordPhone, etc.)
- Store and retrieve user-created notes and similar voluntary content
- Verify top.gg vote status and cache results locally
- Provide the `/data` privacy dashboard — view, export, or delete stored data
- Record usage analytics to understand which features and commands are used (internal operational insight only; not used for advertising or profiling)
- Perform automated health checks and disable features that can no longer access a server or channel
- Create database backups (via Turso and local host backups) for disaster recovery
- Manage data retention when the Bot is removed from a server

### Usage analytics
When you use Bot slash commands, the Bot records a daily count linked to your user ID, the guild (if applicable), the feature, and the command name. This is used for internal reliability and product insight. It is not used for advertising, behavioural profiling, or sale to third parties.

### Data export delivery
When you request an export via `/data`, the Bot compiles your data from Turso/local storage into a ZIP file containing a human-readable summary (`dopamine_export.md`) and a machine-readable file (`raw_dopamine_export.json`), then sends it to you via Discord direct message. No external file-hosting service is used for exports.

### What we do not do
The Bot does not:
- Sell or rent user data
- Use data for targeted advertising
- Transmit stored databases to external analytics or cloud storage providers (except trusted secure cloud database provider Turso)
- Share personal data with third parties except as described in Section 6 (Discord API and top.gg)

All persistent processing remains on Turso cloud database and the Bot’s host unless data is delivered to you through Discord (exports, DMs, or in-server messages as part of normal Bot operation).

---

## 3. Data Retention & Deletion
### Self-service controls (`/data`)
Users can use the `/data` command to:
- View which categories of data the Bot stores
- Export their personal data (delivered by DM, limited to once every 24 hours per scope)
- Delete their personal data by feature or across selected servers

Server administrators (users with Administrator permission in the guild) can use the Server Data section of `/data` to export or delete data held for that server.

### Moderation integrity
For server safety and audit integrity, users cannot delete their own moderation points, infractions, pending punishments, or ban schedules through personal data deletion. Server administrators may delete full server data (including moderation records) via Server Data controls.

### When the Bot leaves a server
If the Bot is removed from a guild:
- The inviter (or server owner) may receive an optional removal feedback request by DM
- Server data is scheduled for automatic deletion after 30 days if the Bot is not re-invited
- If the Bot is re-invited before that period ends, the scheduled deletion is cancelled

### Backups
The Bot creates secure backups of its Turso and local databases approximately every 3 days. Backups exist solely for recovery and are not shared externally.

### Manual deletion requests
You may also request deletion by contacting the developer (see Contact). Data will be removed from active databases in Turso and local storage; residual copies may persist in the latest backup until that backup is rotated.

---

## 4. Security
All data is stored securely using **Turso** (cloud database) and privately managed host infrastructure. Standard encryption and access control measures are used to limit unauthorised access to the Bot’s databases and backup files.

Because the Bot operates on managed cloud and host infrastructure, users should also trust the server administrators and moderators who configure the Bot and manage their Discord server.

Automated health monitoring may disable features that lose access to a guild or channel, reducing the risk of failed operations against inaccessible data.

---

## 5. Discord Integration
The Bot interacts with Discord’s official API to perform authorised moderation, automation, and utility tasks. It may access:
- Guild, user, channel, role, and message IDs
- Permissions (to verify rights before acting)
- Message content only when required by an enabled feature or command

Except as described in Section 1, the Bot does not maintain a general archive of server chat history.

---

## 6. Third-Party Services
### Discord
The Bot uses Discord’s API to function. Data sent to Discord is governed by Discord’s Privacy Policy.

### Turso
The Bot uses Turso as its primary cloud database provider to store persistent guild configurations, user data, and feature state securely. Data stored on Turso is managed under Turso’s security and privacy standards.

### top.gg
The Bot interacts with the top.gg API to verify whether a user has voted for the Bot. When a vote check is performed, the user’s Discord user ID is sent to top.gg. If a user has voted, their ID and vote status may be cached locally to reduce API calls. No other personal data from top.gg is stored beyond what is needed for vote verification.

### No other third parties
Beyond Discord’s official API, Turso, and top.gg, the Bot does not transmit stored user or server databases to other third-party services.

---

## 7. Your Rights
You have the right to:
- Access a copy of your data via `/data` -> Export
- Delete non-protected personal data via `/data` -> Delete
- Request a manual export or deletion from the developer
- Opt out of non-essential features by not using them or asking server staff to disable them
- Request clarification about what data is held about you

Server administrators can manage server-wide data through `/data` -> Server Data.

Moderation integrity records tied to your user ID may be retained until deleted by a server administrator or until server data is purged under the retention rules in Section 3.

---

## 8. Policy Updates
This policy may be updated periodically to reflect new features, data practices, or legal requirements. When feasible, material changes will be announced through official Discord channels. Continued use of the Bot after updates constitutes acceptance of the revised policy.

### Contact
For privacy inquiries or deletion requests, contact the developer at: [hey@dopaminestudios.in](mailto:hey@dopaminestudios.in)
