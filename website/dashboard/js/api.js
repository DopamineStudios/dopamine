class ApiClient {
    constructor() {
        this.baseUrl = '';
    }

    async request(endpoint, options = {}) {
        const token = window.auth.getToken();
        if (!token) {
            window.auth.login();
            throw new Error('Not authenticated');
        }

        const headers = {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
            ...(options.headers || {})
        };

        const config = {
            ...options,
            headers
        };

        try {
            const response = await fetch(endpoint, config);

            if (response.status === 401 || response.status === 403) {
                window.toast.show('Session expired or permission denied. Please log in again.', 'error');
                setTimeout(() => window.auth.logout(), 1500);
                throw new Error('Unauthorized');
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || 'An API error occurred.');
            }

            return data;
        } catch (error) {
            if (error.message !== 'Unauthorized') {
                window.toast.show(error.message, 'error');
            }
            throw error;
        }
    }

    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    }

    async post(endpoint, body) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(body)
        });
    }

    async patch(endpoint, body) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(body)
        });
    }

    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
}

window.api = new ApiClient();
