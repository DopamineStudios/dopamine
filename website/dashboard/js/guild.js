class GuildManager {
    constructor() {
        this.DISCORD_API = "https://discord.com/api/v10";
        this.REQUIRED_PERMISSIONS = 0x20 | 0x8; // MANAGE_GUILD | ADMINISTRATOR
    }

    async fetchManagedGuilds() {
        const token = window.auth.getToken();
        if (!token) throw new Error('No token');

        const response = await fetch(`${this.DISCORD_API}/users/@me/guilds`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) {
            if (response.status === 401) {
                window.auth.logout();
            }
            throw new Error('Failed to fetch user guilds from Discord.');
        }

        const guilds = await response.json();
        return guilds.filter(g => g.owner || (parseInt(g.permissions) & this.REQUIRED_PERMISSIONS) !== 0);
    }

    async fetchUserInfo() {
        const token = window.auth.getToken();
        if (!token) return null;

        const response = await fetch(`${this.DISCORD_API}/users/@me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) return null;
        return response.json();
    }

    setActiveGuildId(guildId) {
        localStorage.setItem('active_guild_id', guildId);
    }

    getActiveGuildId() {
        return localStorage.getItem('active_guild_id');
    }

    getGuildIconUrl(guild) {
        if (!guild.icon) {
            return null;
        }
        return `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png`;
    }
}

window.guildManager = new GuildManager();
