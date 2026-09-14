document.addEventListener('DOMContentLoaded', async () => {
    window.auth.requireAuth();

    const guildId = window.guildManager.getActiveGuildId();
    if (!guildId) {
        window.location.href = 'index.html';
        return;
    }

    const serverHeader = document.getElementById('serverHeader');
    const logoutBtn = document.getElementById('logoutBtn');
    logoutBtn.addEventListener('click', () => window.auth.logout());

    try {
        const guilds = await window.guildManager.fetchManagedGuilds();
        const currentGuild = guilds.find(g => g.id === guildId);

        if (currentGuild) {
            const iconUrl = window.guildManager.getGuildIconUrl(currentGuild);
            const iconContent = iconUrl 
                ? `<img src="${iconUrl}" alt="${currentGuild.name}" style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover;">`
                : `<div style="width: 50px; height: 50px; border-radius: 50%; background: var(--bg-secondary); display: flex; align-items: center; justify-content: center; font-family: 'Bebas Neue'; font-size: 1.2rem;">${currentGuild.name.charAt(0)}</div>`;

            serverHeader.innerHTML = `
                <div style="display: flex; align-items: center; gap: 16px;">
                    ${iconContent}
                    <div>
                        <h2 style="margin: 0; font-family: 'Bebas Neue'; font-size: 2rem; letter-spacing: 1px;">${currentGuild.name}</h2>
                        <p style="margin: 0; color: var(--text-secondary); font-size: 0.85rem;">Select a module below to configure</p>
                    </div>
                </div>
                <a href="index.html" class="btn-secondary-dash" style="text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">&larr; Switch Server</a>
            `;
        }

        const modCard = document.getElementById('modCard');
        modCard.addEventListener('click', () => {
            window.location.href = 'moderation.html';
        });

    } catch (error) {
        console.error(error);
        window.toast.show('Failed to load server details.', 'error');
    }
});
