document.addEventListener('DOMContentLoaded', async () => {
    window.auth.requireAuth();

    const guildId = window.guildManager.getActiveGuildId();
    if (!guildId) {
        window.location.href = 'index.html';
        return;
    }

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.addEventListener('click', () => window.auth.logout());

    // Tabs
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.style.display = 'none');
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            document.getElementById(targetId).style.display = 'block';
        });
    });

    // Load Moderation Config
    async function loadConfig() {
        try {
            const config = await window.api.get(`/api/moderation/${guildId}/config`);
            document.getElementById('simple_mode').checked = config.simple_mode === 1;
            document.getElementById('punishment_dm').checked = config.punishment_dm === 1;
            document.getElementById('punishment_log').checked = config.punishment_log === 1;
            document.getElementById('decay_log_enabled').checked = config.decay_log_enabled === 1;
            document.getElementById('show_medals').checked = config.show_medals === 1;
            document.getElementById('decay_interval').value = config.decay_interval;
            document.getElementById('rejoin_points').value = config.rejoin_points;
            document.getElementById('msg_report_enabled').checked = config.msg_report_enabled === 1;
            document.getElementById('msg_report_channel').value = config.msg_report_channel || '';
            document.getElementById('msg_report_roles').value = config.msg_report_roles || '';
        } catch (e) {
            console.error(e);
        }
    }

    // Save Config helper
    async function saveConfigPatch(payload) {
        try {
            await window.api.patch(`/api/moderation/${guildId}/config`, payload);
            window.toast.show('Moderation settings updated successfully.', 'success');
        } catch (e) {
            console.error(e);
        }
    }

    // Attach Config Listeners
    ['simple_mode', 'punishment_dm', 'punishment_log', 'decay_log_enabled', 'show_medals', 'msg_report_enabled'].forEach(id => {
        document.getElementById(id).addEventListener('change', (e) => {
            saveConfigPatch({ [id]: e.target.checked ? 1 : 0 });
        });
    });

    ['decay_interval', 'rejoin_points'].forEach(id => {
        document.getElementById(id).addEventListener('change', (e) => {
            const val = parseInt(e.target.value);
            if (isNaN(val)) return;
            saveConfigPatch({ [id]: val });
        });
    });

    document.getElementById('saveMsgReportBtn').addEventListener('click', () => {
        const channelVal = document.getElementById('msg_report_channel').value.trim();
        const rolesVal = document.getElementById('msg_report_roles').value.trim();
        saveConfigPatch({
            msg_report_channel: channelVal ? parseInt(channelVal) : null,
            msg_report_roles: rolesVal || null
        });
    });

    // Load Actions
    async function loadActions() {
        const tbody = document.getElementById('actionsTableBody');
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center;">Loading actions...</td></tr>';
        try {
            const actions = await window.api.get(`/api/moderation/${guildId}/actions`);
            tbody.innerHTML = '';
            if (actions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center;">No actions configured.</td></tr>';
                return;
            }
            actions.sort((a, b) => a.points - b.points);
            actions.forEach(action => {
                const tr = document.createElement('tr');
                const term = document.getElementById('simple_mode').checked ? 'Warnings' : 'Points';
                tr.innerHTML = `
                    <td><strong>${action.points}</strong> ${term}</td>
                    <td style="text-transform: capitalize;">${action.action_type}</td>
                    <td>${action.duration === 0 ? 'Permanent / Instant' : action.duration + 's'}</td>
                    <td>
                        <button class="btn-danger-dash" style="padding: 4px 12px; font-size: 0.8rem;" onclick="deleteAction(${action.id})">Delete</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #ff6b6b;">Failed to load actions.</td></tr>';
        }
    }

    window.deleteAction = async (actionId) => {
        if (!confirm('Are you sure you want to delete this action threshold?')) return;
        try {
            await window.api.delete(`/api/moderation/${guildId}/actions/${actionId}`);
            window.toast.show('Action deleted successfully.', 'success');
            loadActions();
        } catch (e) {
            console.error(e);
        }
    };

    // Create Action Modal
    const modal = document.getElementById('actionModal');
    document.getElementById('openCreateActionModal').addEventListener('click', () => modal.classList.add('active'));
    document.getElementById('cancelActionModal').addEventListener('click', () => modal.classList.remove('active'));

    document.getElementById('submitActionBtn').addEventListener('click', async () => {
        const actionType = document.getElementById('newActionType').value;
        const durationSec = parseInt(document.getElementById('newActionDuration').value) || 0;
        const points = parseInt(document.getElementById('newActionPoints').value);

        if (isNaN(points) || points < 1) {
            window.toast.show('Please enter a valid points/warnings threshold.', 'error');
            return;
        }

        try {
            await window.api.post(`/api/moderation/${guildId}/actions`, {
                action_type: actionType,
                duration: durationSec,
                points: points
            });
            window.toast.show('Action created successfully.', 'success');
            modal.classList.remove('active');
            loadActions();
        } catch (e) {
            console.error(e);
        }
    });

    // Load Infractions
    async function loadInfractions() {
        const tbody = document.getElementById('infractionsTableBody');
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">Loading infractions...</td></tr>';
        try {
            const infractions = await window.api.get(`/api/moderation/${guildId}/infractions`);
            tbody.innerHTML = '';
            if (infractions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">No infractions recorded.</td></tr>';
                return;
            }
            infractions.forEach(inf => {
                const tr = document.createElement('tr');
                const dateStr = new Date(inf.created_at * 1000).toLocaleString();
                tr.innerHTML = `
                    <td>#${inf.case_number}</td>
                    <td>${inf.user_id}</td>
                    <td>${inf.moderator_id}</td>
                    <td>+${inf.amount}</td>
                    <td>${inf.reason || 'No reason'}</td>
                    <td>
                        <button class="btn-danger-dash" style="padding: 4px 12px; font-size: 0.8rem;" onclick="deleteInfraction(${inf.case_number})">Delete</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #ff6b6b;">Failed to load infractions.</td></tr>';
        }
    }

    window.deleteInfraction = async (caseNumber) => {
        if (!confirm(`Are you sure you want to delete Case #${caseNumber}?`)) return;
        try {
            await window.api.delete(`/api/moderation/${guildId}/infractions/${caseNumber}`);
            window.toast.show('Infraction case deleted.', 'success');
            loadInfractions();
        } catch (e) {
            console.error(e);
        }
    };

    // Load Pending Punishments
    async function loadPending() {
        const tbody = document.getElementById('pendingTableBody');
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center;">Loading pending punishments...</td></tr>';
        try {
            const pending = await window.api.get(`/api/moderation/${guildId}/pending`);
            tbody.innerHTML = '';
            if (pending.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align: center;">No pending punishments.</td></tr>';
                return;
            }
            pending.forEach(p => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${p.id}</td>
                    <td>${p.user_id}</td>
                    <td>${p.moderator_id}</td>
                    <td>${p.reason || 'No reason'}</td>
                    <td>
                        <button class="btn-danger-dash" style="padding: 4px 12px; font-size: 0.8rem;" onclick="deletePending(${p.id})">Remove</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #ff6b6b;">Failed to load pending punishments.</td></tr>';
        }
    }

    window.deletePending = async (pendingId) => {
        if (!confirm('Are you sure you want to remove this pending punishment?')) return;
        try {
            await window.api.delete(`/api/moderation/${guildId}/pending/${pendingId}`);
            window.toast.show('Pending punishment removed.', 'success');
            loadPending();
        } catch (e) {
            console.error(e);
        }
    };

    // Initial Load
    await loadConfig();
    await loadActions();
    await loadInfractions();
    await loadPending();
});
