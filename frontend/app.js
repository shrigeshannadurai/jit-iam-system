const API_URL = "";

document.addEventListener('DOMContentLoaded', () => {
    fetchResources();
    
    // Poll resources every 5 seconds
    setInterval(fetchResources, 5000);

    const accessForm = document.getElementById('access-form');
    accessForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const devId = document.getElementById('dev-id').value;
        const resId = document.getElementById('res-id').value;
        const reason = document.getElementById('reason').value;
        
        const btn = accessForm.querySelector('button');
        btn.textContent = "Requesting...";
        btn.disabled = true;

        try {
            const res = await fetch(`${API_URL}/request-access`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ developer_id: devId, resource_id: resId, reason: reason })
            });
            const data = await res.json();
            
            const out = document.getElementById('request-output');
            out.classList.remove('hidden');
            if (res.ok) {
                out.innerHTML = `Request ID: <strong><br/>${data.request_id}</strong><br/><br/>${data.message}`;
                out.style.borderColor = "var(--warning)";
                document.getElementById('req-id').value = data.request_id; // auto fill status check
            } else {
                out.innerHTML = `Error: ${data.detail || 'Unknown'}`;
                out.style.borderColor = "var(--error)";
            }
        } catch (err) {
            console.error(err);
        } finally {
            btn.textContent = "Request Access";
            btn.disabled = false;
        }
    });

    document.getElementById('check-status-btn').addEventListener('click', async () => {
        const reqId = document.getElementById('req-id').value;
        if (!reqId) return;

        const out = document.getElementById('status-output');
        try {
            const res = await fetch(`${API_URL}/request/${reqId}`);
            const data = await res.json();
            
            out.classList.remove('hidden');
            if (res.ok) {
                let col = "var(--warning)";
                if (data.status === 'approved') col = "var(--success)";
                if (data.status === 'denied') col = "var(--error)";
                out.style.borderColor = col;
                
                out.innerHTML = `Status: <strong>${data.status.toUpperCase()}</strong><br>Resource: ${data.resource_id}`;
                if (data.status === 'approved') {
                     out.innerHTML += `<br><br>Token dispatched to Slack!<br>(If local, check Redis 'cred:*' keys)`;
                }
            } else {
                out.innerHTML = `Error: ${data.detail}`;
                out.style.borderColor = "var(--error)";
            }
        } catch (err) {
            console.error(err);
        }
    });

    // Mock buttons
    document.getElementById('mock-vm-btn').addEventListener('click', () => {
        const rid = `vm-${Math.random().toString(36).substr(2, 5)}`;
        registerResource(rid, 'vm');
    });
    document.getElementById('mock-db-btn').addEventListener('click', () => {
        const rid = `db-${Math.random().toString(36).substr(2, 5)}`;
        registerResource(rid, 'database');
    });
});

async function fetchResources() {
    try {
        const res = await fetch(`${API_URL}/resources`);
        const data = await res.json();
        
        const list = document.getElementById('resource-list');
        list.innerHTML = '';
        
        if (data.resources.length === 0) {
            list.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem;">No active resources. Click "Register Mock" buttons below to simulate cloud instances booting up.</div>';
            return;
        }

        data.resources.forEach(r => {
            const div = document.createElement('div');
            div.className = 'resource-item';
            div.innerHTML = `
                <strong>${r.resource_id}</strong> [${r.type}]
                <span>TTL: ${r.ttl_remaining}s left</span>
            `;
            div.onclick = () => {
                document.getElementById('res-id').value = r.resource_id;
            };
            list.appendChild(div);
        });
    } catch (err) {
        console.error(err);
    }
}

async function registerResource(id, type) {
    try {
        await fetch(`${API_URL}/register-resource`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resource_id: id, resource_type: type })
        });
        fetchResources(); // refresh
    } catch (err) {
        console.error(err);
    }
}
