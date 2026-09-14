document.addEventListener('DOMContentLoaded', async () => {
    window.auth.requireAuth();

    const guildGrid = document.getElementById('guildGrid');
    const userBadge = document.getElementById('userBadge');
    const logoutBtn = document.getElementById('logoutBtn');

    logoutBtn.addEventListener('click', () => window.auth.logout());

    try {
        const user = await window.guildManager.fetchUserInfo();
        if (user) {
            const avatarUrl = user.avatar 
                ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
                : 'https://cdn.discordapp.com/embed/avatars/0.png';
            userBadge.innerHTML = `
                <img src="${avatarUrl}" alt="Avatar" style="width: 32px; height: 32px; border-radius: 50%;">
                <span>${user.username}</span>
            `;
        }

        const guilds = await window.guildManager.fetchManagedGuilds();
        guildGrid.innerHTML = '';

        if (guilds.length === 0) {
            guildGrid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; color: var(--text-secondary); padding: 40px;">
                    <p>No manageable servers found where you have Administrator or Manage Server permissions.</p>
                    <a href="https://discord.com/api/oauth2/authorize?client_id=1411266382380924938&scope=bot" target="_blank" class="btn-dash" style="display: inline-block; width: auto; margin-top: 16px;">Invite Bot to Server</a>
                </div>
            `;
            return;
        }

        guilds.forEach(guild => {
            const card = document.createElement('div');
            card.className = 'guild-card';

            const iconUrl = window.guildManager.getGuildIconUrl(guild);
            const iconContent = iconUrl 
                ? `<img src="${iconUrl}" alt="${guild.name}" class="guild-icon">`
                : `<div class="guild-icon">${guild.name.charAt(0)}</div>`;

            card.innerHTML = `
                ${iconContent}
                <h3>${guild.name}</h3>
                <p>ID: ${guild.id}</p>
                <button class="btn-dash">Configure Server</button>
            `;

            card.addEventListener('click', () => {
                window.guildManager.setActiveGuildId(guild.id);
                window.location.href = 'server.html';
            });

            guildGrid.appendChild(card);
        });

    } catch (error) {
        console.error(error);
        guildGrid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; color: #ff6b6b;">Failed to load servers. Please try logging in again.</div>`;
    }
});
