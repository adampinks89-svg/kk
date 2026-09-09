/**
 * app.js – Logika frontendowa Multi-Agent AI Studio
 *
 * Obsługuje:
 *  - WebSocket z payloadami JSON (thought / file_event / message / approval_request / ...)
 *  - 3 panele: Myśli, Czat, Dziennik Plików
 *  - Human-in-the-Loop: modal z diff viewerem, approve/reject
 *  - Renderowanie bloków kodu z highlight.js
 *  - Statystyki sesji (narzędzia, pliki, added/removed)
 *  - Migawki (rollback) via HTTP API
 *  - Skrót Ctrl+Enter do wysyłania
 *  - Toast notyfikacje
 */

document.addEventListener('DOMContentLoaded', () => {
    // ─── Elementy DOM ─────────────────────────────────────────────
    const modelSelect       = document.getElementById('model-select');
    const roleSelect        = document.getElementById('role-select');
    const workspaceSelect   = document.getElementById('workspace-select');
    const browseWorkspaceBtn = document.getElementById('browse-workspace-btn');
    const workspaceModal    = document.getElementById('workspace-modal');
    const workspaceCloseBtn = document.getElementById('workspace-close-btn');
    const workspaceParentBtn = document.getElementById('workspace-parent-btn');
    const workspaceCurrentPath = document.getElementById('workspace-current-path');
    const workspaceDirectoryList = document.getElementById('workspace-directory-list');
    const workspaceUseBtn = document.getElementById('workspace-use-btn');
    const filetree = document.getElementById('filetree');
    const refreshFiletreeBtn = document.getElementById('refresh-filetree-btn');
    const clearCtxBtn       = document.getElementById('clear-ctx-btn');
    const showLogsBtn       = document.getElementById('show-logs-btn');
    const showSnapshotsBtn  = document.getElementById('show-snapshots-btn');

    const chatOutput        = document.getElementById('chat-output');
    const messageInput      = document.getElementById('message-input');
    const fileInput         = document.getElementById('file-input');
    const attachBtn         = document.getElementById('attach-btn');
    const attachmentList    = document.getElementById('attachment-list');
    const sendBtn           = document.getElementById('send-btn');
    const stopBtn           = document.getElementById('stop-btn');
    const agentWorking      = document.getElementById('agent-working');

    const ollamaStatus      = document.getElementById('ollama-status');
    const ollamaDot         = ollamaStatus.querySelector('.status-dot');

    // Statystyki
    const statTools         = document.getElementById('stat-tools');
    const statFiles         = document.getElementById('stat-files');
    const statAdded         = document.getElementById('stat-added');
    const statRemoved       = document.getElementById('stat-removed');

    // Modals
    const approvalModal     = document.getElementById('approval-modal');
    const approvalOperation = document.getElementById('approval-operation');
    const approvalPath      = document.getElementById('approval-path');
    const approvalAdded     = document.getElementById('approval-added');
    const approvalRemoved   = document.getElementById('approval-removed');
    const diffContent       = document.getElementById('diff-content');
    const approveBtn        = document.getElementById('approve-btn');
    const rejectBtn         = document.getElementById('reject-btn');

    const logsModal         = document.getElementById('logs-modal');
    const logsCloseBtn      = document.getElementById('logs-close-btn');
    const logsTextarea      = document.getElementById('logs-textarea');

    const snapshotsModal    = document.getElementById('snapshots-modal');
    const snapshotsCloseBtn = document.getElementById('snapshots-close-btn');
    const snapshotsList     = document.getElementById('snapshots-list');

    const toastContainer    = document.getElementById('toast-container');

    // ─── Stan aplikacji ───────────────────────────────────────────
    let ws = null;
    let isConnected = false;
    let currentApprovalId = null;
    let sessionStats = { tools: 0, files: 0, added: 0, removed: 0 };
    let thoughtCounter = 0;
    let fileCounter = 0;
    let attachments = [];
    let browsedWorkspacePath = '';

    // Konfiguracja parsera Markdown
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true, // zamienia \n na <br> tam, gdzie to sensowne
            gfm: true
        });
    }

    // Bufor aktywnego bloku myśli (strumieniowanie)
    let activeThoughtEl = null;
    let activeThoughtText = "";
    // Bufor aktywnego bloku wiadomości
    let activeMessageEl = null;
    let activeMessageText = "";
    let autoFollowChat = true;
    const chatBottomThreshold = 24;

    function isChatNearBottom() {
        return chatOutput.scrollHeight - chatOutput.scrollTop - chatOutput.clientHeight <= chatBottomThreshold;
    }

    function scrollChatToBottom() {
        if (autoFollowChat) {
            chatOutput.scrollTop = chatOutput.scrollHeight;
        }
    }

    chatOutput.addEventListener('scroll', () => {
        autoFollowChat = isChatNearBottom();
    });

    // ─── Inicjalizacja ────────────────────────────────────────────
    async function init() {
        try {
            const [statusRes, rolesRes, workspacesRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/roles'),
                fetch('/api/workspaces'),
            ]);

            const statusData = await statusRes.json();
            const roles = await rolesRes.json();
            const workspaces = await workspacesRes.json();

            // Status Ollama
            if (statusData.connected && statusData.models.length > 0) {
                ollamaStatus.innerHTML = '<span class="status-dot dot-green"></span>Ollama: POŁĄCZONO';
                modelSelect.innerHTML = '';
                statusData.models.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = m;
                    opt.textContent = m;
                    modelSelect.appendChild(opt);
                });
                const uncensored = statusData.models.find(m => m.toLowerCase().includes('uncensored'));
                if (uncensored) modelSelect.value = uncensored;
                appendSystem(`✅ Wykryto ${statusData.models.length} modeli. Wybrany: ${modelSelect.value}`);
            } else {
                ollamaStatus.innerHTML = '<span class="status-dot dot-red"></span>Ollama: BRAK POŁĄCZENIA';
                modelSelect.innerHTML = '<option>Brak połączenia</option>';
                appendError('⚠️ Nie można połączyć z Ollama. Sprawdź czy serwer jest uruchomiony.');
            }

            // Role
            roleSelect.innerHTML = '';
            roles.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r;
                opt.textContent = r;
                roleSelect.appendChild(opt);
            });

            workspaceSelect.innerHTML = '';
            workspaces.forEach(workspace => {
                const opt = document.createElement('option');
                opt.value = workspace.path;
                opt.textContent = workspace.name;
                workspaceSelect.appendChild(opt);
            });
            loadFiletree(workspaceSelect.value);

        } catch (e) {
            appendError(`❌ Błąd inicjalizacji: ${e.message}`);
        }

        connectWebSocket();
    }

    // ─── WebSocket ────────────────────────────────────────────────
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

        ws.onopen = () => {
            isConnected = true;
            appendSystem('🔌 Połączono z serwerem.');
            setTimeout(() => {
                ws.send(JSON.stringify({ action: 'set_role', role: roleSelect.value }));
                if (workspaceSelect.value) {
                    ws.send(JSON.stringify({ action: 'set_workspace', target_dir: workspaceSelect.value }));
                }
            }, 300);
        };

        ws.onmessage = (event) => {
            handlePayload(JSON.parse(event.data));
        };

        ws.onclose = () => {
            isConnected = false;
            appendError('❌ Rozłączono z serwerem. Odśwież stronę.');
            setWorking(false);
        };

        ws.onerror = (err) => {
            appendError('❌ Błąd WebSocket.');
        };
    }

    // ─── Obsługa payloadów ────────────────────────────────────────
    function handlePayload(data) {
        switch (data.type) {

            case 'thought':
                handleThought(data.text);
                break;

            case 'message':
                handleMessage(data.text, data.tag || 'agent');
                break;

            case 'file_event':
                handleFileEvent(data);
                break;
            case 'terminal_event':
                handleTerminalEvent(data);
                break;
            case 'approval_request':
                handleApprovalRequest(data);
                break;

            case 'loop_guard':
                handleLoopGuard(data);
                break;

            case 'task_update':
                // Możliwe rozszerzenie: wyświetl listę zadań
                break;

            case 'system':
                finalizeBlocks();
                appendSystem(data.text);
                break;

            case 'error':
                finalizeBlocks();
                appendError(data.text);
                break;

            case 'done':
                finalizeBlocks();
                setWorking(false);
                break;

            default:
                // Fallback dla starych formatów (string chunk)
                if (data.text) handleMessage(data.text, data.tag || 'agent');
        }
    }

    // ─── Panel Myśli ─────────────────────────────────────────────
    function handleThought(text) {
        clearPanelEmpty(chatOutput);

        if (!activeThoughtEl) {
            // Stwórz nowy blok myśli wewnątrz chatOutput
            thoughtCounter++;

            const block = document.createElement('div');
            block.className = 'thought-block animate-in';

            const header = document.createElement('div');
            header.className = 'thought-header';
            header.innerHTML = `<span class="thought-num">#${thoughtCounter}</span> 🤔 Myśl agenta`;
            block.appendChild(header);

            const body = document.createElement('div');
            body.className = 'thought-body';
            block.appendChild(body);

            chatOutput.appendChild(block);
            activeThoughtEl = body;
            activeThoughtText = "";
        }

        if (text) {
            activeThoughtText += text;
            activeThoughtEl.innerHTML = marked ? marked.parse(activeThoughtText) : activeThoughtText;
            scrollChatToBottom();
        }
    }

    // ─── Główny Czat ──────────────────────────────────────────────
    function handleMessage(text, tag) {
        clearPanelEmpty(chatOutput);

        if (tag === 'agent') {
            if (!activeMessageEl) {
                activeMessageEl = document.createElement('div');
                activeMessageEl.className = 'message message-agent animate-in';
                chatOutput.appendChild(activeMessageEl);
                activeMessageText = "";
            }
            // Dołącz tekst strumieniowo
            activeMessageText += text;

            // Renderuj markdown
            if (typeof marked !== 'undefined') {
                activeMessageEl.innerHTML = marked.parse(activeMessageText);
                // Podświetl bloki kodu wygenerowane przez marked
                activeMessageEl.querySelectorAll('pre code').forEach((block) => {
                    hljs.highlightElement(block);
                });
                addCopyButtons(activeMessageEl);
            } else {
                activeMessageEl.textContent = activeMessageText;
            }

            scrollChatToBottom();
        } else {
            // Inne tagi (code, tool, system, error) – osobne bańki
            finalizeMessageBlock();
            const el = document.createElement('div');
            el.className = `message message-${tag} animate-in`;
            if (typeof marked !== 'undefined') {
                el.innerHTML = marked.parse(text);
                el.querySelectorAll('pre code').forEach((block) => {
                    hljs.highlightElement(block);
                });
                addCopyButtons(el);
            } else {
                el.textContent = text;
            }
            chatOutput.appendChild(el);
            scrollChatToBottom();
        }
    }

    // ─── Dziennik Plików ──────────────────────────────────────────
    function handleFileEvent(data) {
        clearPanelEmpty(chatOutput);
        finalizeBlocks();

        fileCounter++;

        const tile = document.createElement('div');
        tile.className = `file-tile file-tile-${data.operation} animate-in`;

        // Ikona i nazwa
        const opIcons = { 'read': '👀', 'write': '✏️', 'create': '📄', 'delete': '🗑️', 'list': '🗂️' };
        const icon = opIcons[data.operation] || '🔧';

        const header = document.createElement('div');
        header.className = 'file-tile-header';
        header.innerHTML = `
            <span class="file-op-icon">${icon}</span>
            <span class="file-op-name">${data.operation}</span>
            <span class="file-path">${data.path}</span>
        `;
        tile.appendChild(header);

        // Diff i migawka
        if (data.operation === 'write' || data.operation === 'create') {
            const stats = document.createElement('div');
            stats.className = 'file-tile-stats';
            stats.innerHTML = `
                <span class="diff-stat stat-add">+${data.added || 0}</span>
                <span class="diff-stat stat-remove">-${data.removed || 0}</span>
                ${data.snapshot_id ? `<span class="snapshot-badge">Snap: ${data.snapshot_id}</span>` : ''}
            `;
            tile.appendChild(stats);

            // Mini diff if available
            if (data.diff_lines && data.diff_lines.length > 0) {
                const diffMini = document.createElement('div');
                diffMini.className = 'diff-mini';

                const linesToShow = data.diff_lines.slice(0, 6);
                linesToShow.forEach(l => {
                    const lineDiv = document.createElement('div');
                    let cl = 'diff-line';
                    if (l.op === '+') cl += ' diff-line-add';
                    else if (l.op === '-') cl += ' diff-line-remove';
                    else if (l.op === ' ') cl += ' diff-empty';
                    lineDiv.className = cl;
                    lineDiv.textContent = l.op + ' ' + l.content;
                    diffMini.appendChild(lineDiv);
                });

                if (data.diff_lines.length > 6) {
                    const more = document.createElement('div');
                    more.className = 'diff-more';
                    more.textContent = `... i ${data.diff_lines.length - 6} więcej zmian`;
                    diffMini.appendChild(more);
                }
                tile.appendChild(diffMini);
            }
        }

        chatOutput.appendChild(tile);
        scrollChatToBottom();

        updateStats();
    }

    // ─── Obsługa terminala ─────────────────────────────────────────
    function handleTerminalEvent(data) {
        clearPanelEmpty(chatOutput);
        finalizeBlocks();

        const terminalBlock = document.createElement('div');
        terminalBlock.className = 'terminal-block animate-in';

        const header = document.createElement('div');
        header.className = 'terminal-header';
        header.innerHTML = `
            <span class="terminal-icon">${data.shell === 'powershell' ? 'PS' : '▶'}</span>
            <span class="terminal-title">${data.shell === 'powershell' ? 'PowerShell' : 'Terminal'}</span>
            ${data.exit_code !== undefined ? `<span class="terminal-exit ${data.exit_code === 0 ? 'exit-ok' : 'exit-err'}">[Exit: ${data.exit_code}]</span>` : ''}
        `;
        terminalBlock.appendChild(header);

        const body = document.createElement('div');
        body.className = 'terminal-body';

        const commandLine = document.createElement('div');
        commandLine.className = 'terminal-command';
        commandLine.textContent = `$ ${data.command}`;
        body.appendChild(commandLine);

        if (data.output) {
            const outputLine = document.createElement('div');
            outputLine.className = 'terminal-output';
            outputLine.textContent = data.output;
            body.appendChild(outputLine);
        }

        if (data.error) {
            const errorLine = document.createElement('div');
            errorLine.className = 'terminal-error';
            errorLine.textContent = data.error;
            body.appendChild(errorLine);
        }

        if (data.cwd) {
            const cwdLine = document.createElement('div');
            cwdLine.className = 'terminal-cwd';
            cwdLine.textContent = `cwd: ${data.cwd}`;
            body.appendChild(cwdLine);
        }

        terminalBlock.appendChild(body);
        chatOutput.appendChild(terminalBlock);
        scrollChatToBottom();
    }

    // ─── Human-in-the-Loop ────────────────────────────────────────
    function handleApprovalRequest(data) {
        currentApprovalId = data.approval_id;
        approvalOperation.textContent = data.operation;
        approvalPath.textContent = data.path;
        approvalAdded.textContent = `+${data.added}`;
        approvalRemoved.textContent = `-${data.removed}`;

        // Renderuj diff
        diffContent.innerHTML = '';
        if (data.diff_lines && data.diff_lines.length > 0) {
            // Podziel na linie przed (left) i po (right)
            const leftLines = [];
            const rightLines = [];

            data.diff_lines.forEach(line => {
                if (line.op === ' ') {
                    leftLines.push({ cls: '', text: line.content });
                    rightLines.push({ cls: '', text: line.content });
                } else if (line.op === '-') {
                    leftLines.push({ cls: 'diff-line-remove', text: line.content });
                    rightLines.push({ cls: 'diff-empty', text: '' });
                } else if (line.op === '+') {
                    leftLines.push({ cls: 'diff-empty', text: '' });
                    rightLines.push({ cls: 'diff-line-add', text: line.content });
                }
            });

            const leftCol = document.createElement('div');
            leftCol.className = 'diff-col';
            const rightCol = document.createElement('div');
            rightCol.className = 'diff-col';

            const maxLines = Math.max(leftLines.length, rightLines.length);
            for (let i = 0; i < maxLines; i++) {
                const lLine = leftLines[i] || { cls: '', text: '' };
                const rLine = rightLines[i] || { cls: '', text: '' };

                const lEl = document.createElement('div');
                lEl.className = `diff-line ${lLine.cls}`;
                lEl.textContent = lLine.text || ' ';
                leftCol.appendChild(lEl);

                const rEl = document.createElement('div');
                rEl.className = `diff-line ${rLine.cls}`;
                rEl.textContent = rLine.text || ' ';
                rightCol.appendChild(rEl);
            }

            diffContent.appendChild(leftCol);
            diffContent.appendChild(rightCol);
        } else {
            diffContent.textContent = 'Brak zmian do wyświetlenia.';
        }

        approvalModal.classList.add('active');
        // Focus na Zatwierdź
        setTimeout(() => approveBtn.focus(), 100);
    }

    function sendApproval(approved) {
        if (!currentApprovalId) return;
        ws.send(JSON.stringify({
            action: approved ? 'approve' : 'reject',
            approval_id: currentApprovalId,
        }));
        currentApprovalId = null;
        approvalModal.classList.remove('active');
        showToast(approved ? '✅ Operacja zatwierdzona' : '⛔ Operacja odrzucona', approved ? 'success' : 'error');
    }

    // ─── Loop Guard ───────────────────────────────────────────────
    function handleLoopGuard(data) {
        finalizeBlocks();
        const el = document.createElement('div');
        el.className = 'loop-guard-alert animate-in';
        el.innerHTML = `
            <span class="loop-icon">🔒</span>
            <div>
                <strong>Loop Guard</strong> (iter. ${data.iteration})
                <div class="loop-reason">${data.reason}</div>
            </div>
        `;
        chatOutput.appendChild(el);
        scrollChatToBottom();
    }

    // ─── Helpers ──────────────────────────────────────────────────
    function finalizeBlocks() {
        if (activeThoughtEl) activeThoughtEl = null;
        if (activeMessageEl) {
            // Zamień tło po ukończeniu (opcjonalnie)
            activeMessageEl.classList.remove('animate-in');
            activeMessageEl = null;
        }
    }

    function finalizeMessageBlock() {
        activeMessageEl = null;
    }

    function appendSystem(text) {
        clearPanelEmpty(chatOutput);
        const el = document.createElement('div');
        el.className = 'message-inline message-system animate-in';
        if (typeof marked !== 'undefined') {
            el.innerHTML = marked.parseInline(text);
        } else {
            el.textContent = text;
        }
        chatOutput.appendChild(el);
        scrollChatToBottom();
    }

    function appendError(text) {
        clearPanelEmpty(chatOutput);
        const el = document.createElement('div');
        el.className = 'message message-error animate-in';
        el.textContent = text;
        chatOutput.appendChild(el);
        scrollChatToBottom();
    }

    function appendUserMessage(text) {
        clearPanelEmpty(chatOutput);
        finalizeBlocks();
        const el = document.createElement('div');
        el.className = 'message message-user animate-in';
        el.innerHTML = `<span class="user-label">Ty</span><p>${escapeHtml(text)}</p>`;
        chatOutput.appendChild(el);
        scrollChatToBottom();
    }

    function addCopyButtons(container) {
        container.querySelectorAll('pre').forEach((pre) => {
            if (pre.querySelector('.copy-code-btn')) return;

            const codeElement = pre.querySelector('code');
            const languageClass = Array.from(codeElement?.classList || [])
                .find(className => className.startsWith('language-'));
            const language = languageClass ? languageClass.replace('language-', '') : 'kod';
            const toolbar = document.createElement('div');
            toolbar.className = 'code-toolbar';

            const languageLabel = document.createElement('span');
            languageLabel.className = 'code-language';
            languageLabel.textContent = language;
            toolbar.appendChild(languageLabel);

            const button = document.createElement('button');
            button.className = 'copy-code-btn';
            button.type = 'button';
            button.textContent = 'Kopiuj';
            button.title = 'Skopiuj kod do schowka';
            button.addEventListener('click', async () => {
                const code = codeElement?.textContent || '';
                try {
                    await navigator.clipboard.writeText(code);
                    button.textContent = 'Skopiowano';
                    setTimeout(() => { button.textContent = 'Kopiuj'; }, 1400);
                } catch (error) {
                    showToast('Nie udało się skopiować kodu', 'error');
                }
            });
            toolbar.appendChild(button);
            pre.appendChild(toolbar);
        });
    }

    function renderAttachments() {
        attachmentList.innerHTML = '';
        attachments.forEach((attachment, index) => {
            const item = document.createElement('div');
            item.className = 'attachment-item';
            item.innerHTML = `<span>${attachment.type.startsWith('image/') ? '🖼️' : '📄'} ${escapeHtml(attachment.name)}</span>`;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'attachment-remove';
            remove.textContent = '×';
            remove.title = 'Usuń załącznik';
            remove.addEventListener('click', () => {
                attachments.splice(index, 1);
                renderAttachments();
            });
            item.appendChild(remove);
            attachmentList.appendChild(item);
        });
    }

    async function readAttachment(file) {
        const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
        const data = String(dataUrl);
        const base64 = data.includes(',') ? data.split(',')[1] : data;
        let content = '';
        if (!file.type.startsWith('image/')) {
            try {
                content = await file.text();
            } catch (error) {
                content = `[Nie można odczytać pliku ${file.name}]`;
            }
        }
        return { name: file.name, type: file.type || 'application/octet-stream', data: base64, content };
    }

    function clearPanelEmpty(panel) {
        const empty = panel.querySelector('.panel-empty');
        if (empty) empty.remove();
    }

    function setWorking(active) {
        if (active) {
            agentWorking.classList.remove('hidden');
            sendBtn.disabled = true;
            stopBtn.disabled = false;
            sessionStats.tools++;
            updateStats();
        } else {
            agentWorking.classList.add('hidden');
            sendBtn.disabled = false;
            stopBtn.disabled = true;
        }
    }

    function updateStats() {
        statTools.textContent = sessionStats.tools;
        statFiles.textContent = sessionStats.files;
        statAdded.textContent = `+${sessionStats.added}`;
        statRemoved.textContent = `-${sessionStats.removed}`;
    }

    function formatPath(path) {
        const parts = path.replace(/\\/g, '/').split('/');
        if (parts.length > 3) {
            return '.../' + parts.slice(-2).join('/');
        }
        return path;
    }

    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        setTimeout(() => toast.classList.add('toast-show'), 10);
        setTimeout(() => {
            toast.classList.remove('toast-show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ─── Wysyłanie wiadomości ─────────────────────────────────────
    function sendMessage() {
        const msg = messageInput.value.trim();
        if ((!msg && !attachments.length) || !isConnected) return;

        const attachmentText = attachments
            .filter(file => file.content)
            .map(file => `\n\n--- Załącznik: ${file.name} ---\n${file.content}`)
            .join('');
        const displayText = (msg || 'Załączniki') + (attachments.length ? `\n📎 Dołączono: ${attachments.map(file => file.name).join(', ')}` : '');
        appendUserMessage(displayText);
        messageInput.value = '';
        messageInput.style.height = 'auto';
        setWorking(true);

        ws.send(JSON.stringify({
            action: 'message',
            message: msg + attachmentText,
            model: modelSelect.value,
            workspace: workspaceSelect.value,
            attachments: attachments.map(({ name, type, data }) => ({ name, type, data })),
        }));
        attachments = [];
        renderAttachments();
    }

    // ─── Event Listeners ──────────────────────────────────────────
    sendBtn.addEventListener('click', sendMessage);

    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
        try {
            const selected = await Promise.all(Array.from(fileInput.files).map(readAttachment));
            attachments.push(...selected);
            renderAttachments();
        } catch (error) {
            showToast('Nie udało się odczytać załącznika', 'error');
        } finally {
            fileInput.value = '';
        }
    });

    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            sendMessage();
        }
        // Auto-resize textarea
        setTimeout(() => {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
        }, 0);
    });

    stopBtn.addEventListener('click', () => {
        if (ws && isConnected) ws.send(JSON.stringify({ action: 'stop' }));
    });

    clearCtxBtn.addEventListener('click', () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: 'clear', role: roleSelect.value }));
            // Wyczyść panele
            chatOutput.innerHTML = '';
            autoFollowChat = true;
            thoughtCounter = 0; fileCounter = 0;
            sessionStats = { tools: 0, files: 0, added: 0, removed: 0 };
            updateStats();
            showToast('Kontekst wyczyszczony', 'info');
        }
    });

    roleSelect.addEventListener('change', () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: 'set_role', role: roleSelect.value }));
            showToast(`Rola: ${roleSelect.value}`, 'info');
        }
    });

    workspaceSelect.addEventListener('change', () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: 'set_workspace', target_dir: workspaceSelect.value }));
            showToast(`Folder agenta: ${workspaceSelect.options[workspaceSelect.selectedIndex].text}`, 'info');
        }
        loadFiletree(workspaceSelect.value);
    });

    function fileIcon(entry) {
        if (entry.kind === 'directory') return '📁';
        const icons = {
            '.py': '🐍', '.js': '🟨', '.ts': '🔷', '.tsx': '⚛️', '.html': '🌐',
            '.css': '🎨', '.json': '⚙️', '.md': '📝', '.go': '🔵', '.rs': '🦀',
            '.java': '☕', '.sql': '🗃️', '.sh': '▣', '.bat': '▣',
        };
        return icons[entry.extension] || '📄';
    }

    async function loadFiletree(path) {
        if (!filetree || !path) return;
        filetree.innerHTML = '<p class="panel-empty">Ładowanie plików...</p>';
        try {
            const response = await fetch(`/api/filetree?path=${encodeURIComponent(path)}`);
            const data = await response.json();
            if (!response.ok || data.error) throw new Error(data.error || 'Nie udało się odczytać drzewa plików.');
            filetree.innerHTML = '';
            if (!data.entries.length) {
                filetree.innerHTML = '<p class="panel-empty">Folder jest pusty.</p>';
                return;
            }
            data.entries.forEach(entry => {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = `filetree-entry ${entry.kind}`;
                row.title = entry.path;
                row.innerHTML = `<span class="filetree-icon">${fileIcon(entry)}</span><span class="filetree-name">${escapeHtml(entry.name)}</span>`;
                if (entry.kind === 'directory') {
                    row.addEventListener('click', () => loadFiletree(entry.path));
                } else {
                    row.disabled = true;
                }
                filetree.appendChild(row);
            });
        } catch (error) {
            filetree.innerHTML = `<p class="panel-empty">${escapeHtml(error.message)}</p>`;
        }
    }

    refreshFiletreeBtn.addEventListener('click', () => loadFiletree(workspaceSelect.value));

    async function loadWorkspaceDirectory(path) {
        workspaceDirectoryList.innerHTML = '<p class="panel-empty">Ładowanie katalogów...</p>';
        try {
            const query = path ? `?path=${encodeURIComponent(path)}` : '';
            const endpoint = path ? `/api/directories${query}` : '/api/directory-roots';
            const response = await fetch(endpoint);
            const data = await response.json();
            if (!response.ok || data.error) throw new Error(data.error || 'Nie udało się odczytać katalogu.');

            if (!path) {
                browsedWorkspacePath = '';
                workspaceCurrentPath.textContent = 'Wybierz dysk';
                workspaceCurrentPath.dataset.parent = '';
                workspaceParentBtn.disabled = true;
                workspaceDirectoryList.innerHTML = '';
                if (!data.roots.length) {
                    workspaceDirectoryList.innerHTML = '<p class="panel-empty">Brak dostępnych dysków.</p>';
                    return;
                }
                data.roots.forEach(root => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'workspace-directory';
                    button.innerHTML = `<span>💽</span><span>${escapeHtml(root.name)}</span>`;
                    button.addEventListener('click', () => loadWorkspaceDirectory(root.path));
                    workspaceDirectoryList.appendChild(button);
                });
                return;
            }

            browsedWorkspacePath = data.path;
            workspaceCurrentPath.textContent = data.path;
            workspaceCurrentPath.dataset.parent = data.parent || '';
            workspaceParentBtn.disabled = !data.parent;
            workspaceDirectoryList.innerHTML = '';

            if (!data.directories.length) {
                workspaceDirectoryList.innerHTML = '<p class="panel-empty">Brak podkatalogów.</p>';
                return;
            }
            data.directories.forEach(directory => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'workspace-directory';
                button.innerHTML = `<span>📁</span><span>${escapeHtml(directory.name)}</span>`;
                button.addEventListener('click', () => loadWorkspaceDirectory(directory.path));
                workspaceDirectoryList.appendChild(button);
            });
        } catch (error) {
            workspaceDirectoryList.innerHTML = '';
            appendError(`❌ ${error.message}`);
        }
    }

    function closeWorkspaceModal() {
        workspaceModal.classList.remove('active');
    }

    browseWorkspaceBtn.addEventListener('click', () => {
        workspaceModal.classList.add('active');
        loadWorkspaceDirectory('');
    });
    workspaceCloseBtn.addEventListener('click', closeWorkspaceModal);
    workspaceParentBtn.addEventListener('click', () => {
        if (!workspaceParentBtn.disabled) loadWorkspaceDirectory(workspaceCurrentPath.dataset.parent || '');
    });
    workspaceUseBtn.addEventListener('click', () => {
        const option = Array.from(workspaceSelect.options).find(item => item.value === browsedWorkspacePath);
        if (option) {
            workspaceSelect.value = browsedWorkspacePath;
        } else {
            const newOption = document.createElement('option');
            newOption.value = browsedWorkspacePath;
            newOption.textContent = browsedWorkspacePath.split(/[\\/]/).pop() || browsedWorkspacePath;
            workspaceSelect.appendChild(newOption);
            workspaceSelect.value = browsedWorkspacePath;
        }
        workspaceSelect.dispatchEvent(new Event('change'));
        closeWorkspaceModal();
    });

    // Toggles paneli
    // Usunięto nasłuchiwacze togli paneli, ponieważ zrezygnowaliśmy z nich na rzecz pojedynczego widoku.

    // Modal Zatwierdzania
    approveBtn.addEventListener('click', () => sendApproval(true));
    rejectBtn.addEventListener('click', () => sendApproval(false));

    document.addEventListener('keydown', (e) => {
        if (approvalModal.classList.contains('active')) {
            if (e.key === 'Escape') sendApproval(false);
            if (e.ctrlKey && e.key === 'Enter') sendApproval(true);
        }
        if (e.key === 'Escape' && workspaceModal.classList.contains('active')) {
            closeWorkspaceModal();
        }
    });

    // Modal Logów
    showLogsBtn.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/logs');
            const data = await res.json();
            logsTextarea.value = data.logs;
            logsModal.classList.add('active');
        } catch (e) {
            showToast('Błąd pobierania logów', 'error');
        }
    });

    logsCloseBtn.addEventListener('click', () => logsModal.classList.remove('active'));

    // Modal Migawek
    showSnapshotsBtn.addEventListener('click', async () => {
        snapshotsList.innerHTML = '<p class="panel-empty">Ładowanie...</p>';
        snapshotsModal.classList.add('active');
        try {
            const res = await fetch('/api/snapshots');
            const data = await res.json();
            renderSnapshots(data.snapshots || []);
        } catch (e) {
            snapshotsList.innerHTML = '<p class="panel-empty">Błąd pobierania migawek.</p>';
        }
    });

    snapshotsCloseBtn.addEventListener('click', () => snapshotsModal.classList.remove('active'));

    function renderSnapshots(snapshots) {
        if (!snapshots.length) {
            snapshotsList.innerHTML = '<p class="panel-empty">Brak migawek. Zostaną tu po pierwszej modyfikacji pliku.</p>';
            return;
        }
        snapshotsList.innerHTML = '';
        snapshots.forEach(snap => {
            const item = document.createElement('div');
            item.className = 'snapshot-item';
            item.innerHTML = `
                <div class="snapshot-info">
                    <strong>${snap.id}</strong>
                    <span class="snapshot-path">${formatPath(snap.original_path)}</span>
                    <span class="snapshot-date">${new Date(snap.created_at).toLocaleString('pl')}</span>
                </div>
                <button class="btn btn-secondary btn-sm" data-id="${snap.id}" data-path="${snap.original_path}">
                    ↩ Przywróć
                </button>
            `;
            const rollbackBtn = item.querySelector('button');
            rollbackBtn.addEventListener('click', async () => {
                rollbackBtn.disabled = true;
                rollbackBtn.textContent = 'Przywracanie...';
                try {
                    const res = await fetch('/api/rollback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ snapshot_id: snap.id }),
                    });
                    const result = await res.json();
                    showToast(result.message, result.success ? 'success' : 'error');
                    snapshotsModal.classList.remove('active');
                } catch (e) {
                    showToast('Błąd rollbacku', 'error');
                    rollbackBtn.disabled = false;
                    rollbackBtn.textContent = '↩ Przywróć';
                }
            });
            snapshotsList.appendChild(item);
        });
    }

    // Zamykanie modali przez kliknięcie tła
    [logsModal, snapshotsModal, workspaceModal].forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('active');
        });
    });

    // ─── Start ────────────────────────────────────────────────────
    appendSystem('⚡ Multi-Agent AI Studio — inicjalizacja...');
    init();
});
