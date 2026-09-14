class AuthManager {
    constructor() {
        this.CLIENT_ID = "1411266382380924938";
        this.parseHashToken();
    }

    parseHashToken() {
        const hash = window.location.hash;
        if (hash && hash.includes('access_token')) {
            const params = new URLSearchParams(hash.substring(1));
            const accessToken = params.get('access_token');
            if (accessToken) {
                localStorage.setItem('discord_token', accessToken);
                // Clean hash from URL
                history.replaceState(null, '', window.location.pathname);
            }
        }
    }

    getToken() {
        return localStorage.getItem('discord_token');
    }

    isAuthenticated() {
        return !!this.getToken();
    }

    login() {
        const redirectUri = encodeURIComponent(`${window.location.origin}/dash/index.html`);
        const authUrl = `https://discord.com/api/oauth2/authorize?client_id=${this.CLIENT_ID}&redirect_uri=${redirectUri}&response_type=token&scope=identify%20guilds`;
        window.location.href = authUrl;
    }

    logout() {
        localStorage.removeItem('discord_token');
        localStorage.removeItem('active_guild_id');
        window.location.href = '/dash/index.html';
    }

    requireAuth() {
        if (!this.isAuthenticated()) {
            this.login();
        }
    }
}

window.auth = new AuthManager();
