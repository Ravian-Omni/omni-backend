let ws;
let sentCount = 0;
let receivedCount = 0;
let errorCount = 0;
let currentChatId = null;
let chatHistory = JSON.parse(localStorage.getItem('chatHistory') || '[]');

// Sidebar and resize functionality
let isResizing = false;
let isSidebarCollapsed = false;
let leftPanelWidth = 400;

window.onload = function () {
    const newChatBtn = document.getElementById("newChatBtn");
    const connectBtn = document.getElementById("connectBtn");
    const disconnectBtn = document.getElementById("disconnectBtn");
    const sendBtn = document.getElementById("sendBtn");
    const formatBtn = document.getElementById("formatBtn");
    const clearBtn = document.getElementById("clearBtn");
    const copyAllBtn = document.getElementById("copyAllBtn");
    const sidebarToggle = document.getElementById("sidebarToggle");
    const resizeHandle = document.getElementById("resizeHandle");

    // Event listeners
    newChatBtn.addEventListener("click", createNewChat);
    connectBtn.addEventListener("click", connect);
    disconnectBtn.addEventListener("click", disconnect);
    sendBtn.addEventListener("click", sendMessage);
    formatBtn.addEventListener("click", formatJSON);
    clearBtn.addEventListener("click", clearMessages);
    copyAllBtn.addEventListener("click", copyAllMessages);
    sidebarToggle.addEventListener("click", toggleSidebar);

    // Resize functionality
    resizeHandle.addEventListener("mousedown", startResize);
    document.addEventListener("mousemove", handleResize);
    document.addEventListener("mouseup", stopResize);

    // Load chat history on startup
    displayChatHistory();

    // Load saved panel width
    const savedWidth = localStorage.getItem('leftPanelWidth');
    if (savedWidth) {
        leftPanelWidth = parseInt(savedWidth);
        updatePanelWidths();
    }

    // Load sidebar state
    const savedSidebarState = localStorage.getItem('sidebarCollapsed');
    if (savedSidebarState === 'true') {
        toggleSidebar();
    }

    // Handle Enter key in textarea
    document.getElementById("jsonInput").addEventListener("keydown", (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            sendMessage();
        }
    });
};

// Sidebar toggle functionality
function toggleSidebar() {
    const leftPanel = document.getElementById("leftPanel");
    const rightPanel = document.getElementById("rightPanel");
    const resizeHandle = document.getElementById("resizeHandle");
    const sidebarToggle = document.getElementById("sidebarToggle");
    
    isSidebarCollapsed = !isSidebarCollapsed;
    
    if (isSidebarCollapsed) {
        leftPanel.classList.add("collapsed");
        resizeHandle.classList.add("collapsed");
        sidebarToggle.classList.add("active");
    } else {
        leftPanel.classList.remove("collapsed");
        resizeHandle.classList.remove("collapsed");
        sidebarToggle.classList.remove("active");
    }
    
    // Save state
    localStorage.setItem('sidebarCollapsed', isSidebarCollapsed);
}

// Resize functionality
function startResize(e) {
    if (isSidebarCollapsed) return;
    isResizing = true;
    document.getElementById("resizeHandle").classList.add("dragging");
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
}

function handleResize(e) {
    if (!isResizing || isSidebarCollapsed) return;
    
    const newWidth = e.clientX;
    if (newWidth >= 200 && newWidth <= window.innerWidth - 300) {
        leftPanelWidth = newWidth;
        updatePanelWidths();
    }
}

function stopResize() {
    if (!isResizing) return;
    isResizing = false;
    document.getElementById("resizeHandle").classList.remove("dragging");
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    
    // Save width
    localStorage.setItem('leftPanelWidth', leftPanelWidth);
}

function updatePanelWidths() {
    if (isSidebarCollapsed) return;
    
    const leftPanel = document.getElementById("leftPanel");
    leftPanel.style.width = leftPanelWidth + 'px';
}

// Toast notification system
function showToast(message, type = 'success') {
    const toast = document.getElementById("toast");
    const toastMessage = document.getElementById("toastMessage");
    
    toastMessage.textContent = message;
    toast.className = `toast ${type}`;
    toast.classList.add("show");
    
    setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

// Copy functionality
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast("Copied to clipboard!");
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showToast("Failed to copy to clipboard", "error");
    });
}

function copyAllMessages() {
    const messages = document.getElementById("messages");
    const messageElements = messages.querySelectorAll('.message-wrapper');
    let allText = '';
    
    messageElements.forEach((wrapper, index) => {
        const messageData = wrapper.getAttribute('data-message');
        if (messageData) {
            allText += `Message ${index + 1}:\n${messageData}\n\n`;
        }
    });
    
    if (allText.trim()) {
        copyToClipboard(allText.trim());
    } else {
        showToast("No messages to copy", "error");
    }
}

function copyMessage(messageData) {
    copyToClipboard(messageData);
}

// WebSocket connection functionality
function connect() {
    const clientId = document.getElementById("clientId").value.trim();
    if (!clientId) {
        showToast("Please enter a valid UUID!", "error");
        return;
    }

    updateStatus("connecting", "🔄", "Connecting...");
    updateButtons(false, false, false);

    const url = `ws://${location.host}/ws/runs/${clientId}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
        updateStatus("connected", "✅", "Connected");
        updateButtons(false, true, true);
        showMessage("", { type: "system", status: "WebSocket connected", timestamp: new Date().toISOString() }, "received");
    };

    ws.onmessage = (event) => {
        receivedCount++;
        updateStats();
        
        try {
            const json = JSON.parse(event.data);
            showMessage("", json, "received");
        } catch {
            showMessage("Raw", event.data, "error");
        }
    };

    ws.onclose = (event) => {
        updateStatus("disconnected", "❌", "Disconnected");
        updateButtons(true, false, false);
        
        const reason = event.code === 1000 ? "Normal closure" : 
                      event.code === 1001 ? "Going away" :
                      event.code === 1006 ? "Connection lost" :
                      `Code: ${event.code}`;
        showMessage("", { type: "system", status: `Disconnected: ${reason}`, timestamp: new Date().toISOString() }, "error");
    };

    ws.onerror = (error) => {
        errorCount++;
        updateStats();
        showMessage("", { type: "system", status: "WebSocket connection error", timestamp: new Date().toISOString() }, "error");
    };
}

function disconnect() {
    if (ws) {
        ws.close(1000, "User initiated disconnect");
    }
}

function sendMessage() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast("WebSocket is not connected.", "error");
        return;
    }

    const raw = document.getElementById("jsonInput").value.trim();
    if (!raw) {
        showToast("Please enter a message to send.", "error");
        return;
    }

    try {
        const parsed = JSON.parse(raw);
        const jsonText = JSON.stringify(parsed);
        ws.send(jsonText);
        
        sentCount++;
        updateStats();
        showMessage("", { type: "message", data: { source: "user", content: { type: "manual", task: JSON.stringify(parsed) }, timestamp: new Date().toISOString() } }, "sent");
    } catch (e) {
        showToast("Invalid JSON: " + e.message, "error");
    }
}

function formatJSON() {
    const textarea = document.getElementById("jsonInput");
    try {
        const parsed = JSON.parse(textarea.value);
        textarea.value = JSON.stringify(parsed, null, 2);
        showToast("JSON formatted successfully!");
    } catch (e) {
        showToast("Invalid JSON: " + e.message, "error");
    }
}

function clearMessages() {
    document.getElementById("messages").innerHTML = "";
    sentCount = 0;
    receivedCount = 0;
    errorCount = 0;
    updateStats();
    showToast("Messages cleared!");
}

function updateStatus(type, icon, text) {
    const status = document.getElementById("status");
    status.className = `status-container status-${type}`;
    status.innerHTML = `<span class="status-icon">${icon}</span><span>${text}</span>`;
}

function updateButtons(connectEnabled, disconnectEnabled, sendEnabled) {
    document.getElementById("connectBtn").disabled = !connectEnabled;
    document.getElementById("disconnectBtn").disabled = !disconnectEnabled;
    document.getElementById("sendBtn").disabled = !sendEnabled;
}

function updateStats() {
    document.getElementById("sentCount").textContent = sentCount;
    document.getElementById("receivedCount").textContent = receivedCount;
    document.getElementById("errorCount").textContent = errorCount;
}

function showMessage(type, data, className) {
    const messages = document.getElementById("messages");
    const timestamp = new Date().toLocaleTimeString();
    
    // Try to parse the message and determine its type
    let messageData = data;
    if (typeof data === 'string') {
        try {
            messageData = JSON.parse(data);
        } catch (e) {
            // Keep as string if not valid JSON
        }
    }
    
    // Create wrapper div for copy functionality
    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper";
    
    const div = document.createElement("div");
    
    // Store message data for copying
    const messageText = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    wrapper.setAttribute('data-message', messageText);
    
    // Helper function to format JSON content beautifully
    function formatJsonContent(content) {
        if (typeof content === 'string') {
            // Try to parse if it's a JSON string
            try {
                const parsed = JSON.parse(content);
                return createJsonDisplay(parsed);
            } catch (e) {
                return `<div class="text-content">${content}</div>`;
            }
        } else if (typeof content === 'object' && content !== null) {
            return createJsonDisplay(content);
        } else {
            return `<div class="text-content">${String(content)}</div>`;
        }
    }

    // Helper function to create beautiful JSON display
    function createJsonDisplay(obj) {
        if (typeof obj !== 'object' || obj === null) {
            return `<div class="text-content">${String(obj)}</div>`;
        }

        let html = '<div class="json-content">';
        for (const [key, value] of Object.entries(obj)) {
            const valueType = getValueType(value);
            const formattedValue = formatValue(value);
            html += `<div class="json-key-value"><div class="json-key">${key.replace(/_/g, ' ')}</div><div class="json-value ${valueType}">${formattedValue}</div></div>`;
        }
        html += '</div>';
        return html;
    }

    // Helper function to determine value type
    function getValueType(value) {
        if (value === null) return 'null';
        if (typeof value === 'string') return 'string';
        if (typeof value === 'number') return 'number';
        if (typeof value === 'boolean') return 'boolean';
        if (Array.isArray(value)) return 'array';
        return 'object';
    }

    // Helper function to format values
    function formatValue(value) {
        if (value === null) return 'null';
        if (typeof value === 'string') return value;
        if (typeof value === 'number') return value.toString();
        if (typeof value === 'boolean') return value.toString();
        if (Array.isArray(value)) {
            if (value.length === 0) return '[]';
            return `[${value.length} items]`;
        }
        if (typeof value === 'object') return JSON.stringify(value, null, 2);
        return String(value);
    }

    // Helper function to get message class and agent info based on source
    function getAgentInfo(source) {
        const agentMap = {
            'OMNI': { className: 'bot-message', icon: '🤖', name: 'OMNI' },
            'email_manager': { className: 'email-manager-message', icon: '📧', name: 'Email Manager' },
            'browser_manager': { className: 'browser-manager-message', icon: '🌐', name: 'Browser Manager' },
            'python_developer': { className: 'python-developer-message', icon: '🐍', name: 'Python Developer' },
            'file_finder': { className: 'file-finder-message', icon: '📁', name: 'File Finder' },
            'image_generator': { className: 'image-generator-message', icon: '🎨', name: 'Image Generator' }
        };
        return agentMap[source] || { className: 'bot-message', icon: '🤖', name: source };
    }
    
    // Create copy button for each message
    const copyBtn = document.createElement("button");
    copyBtn.className = "message-copy-btn";
    copyBtn.textContent = "Copy";
    copyBtn.onclick = () => copyMessage(messageText);
    
    // Handle different message types based on structure
    if (messageData && typeof messageData === 'object') {
        if (messageData.type === 'system') {
            // System/notification message - compact display
            div.className = "system-message";
            div.innerHTML = `
                <div class="message-header">
                    System <span class="timestamp">${timestamp}</span>
                </div>
                <div class="message-content">${messageData.status || 'notification'}</div>
            `;
        } else if (messageData.type === 'completion') {
            // Completion message - similar to system but with success styling
            div.className = "completion-message";
            div.innerHTML = `
                <div class="message-header">
                    ✅ Completed <span class="timestamp">${timestamp}</span>
                </div>
                <div class="message-content">${messageData.status || 'Task completed'}</div>
            `;
        } else if (messageData.type === 'message' && messageData.data?.source === 'user') {
            // User message
            div.className = "user-message";
            const content = messageData.data.content?.task || 
                          messageData.data.content?.content || 
                          formatJsonContent(messageData.data.content);
            div.innerHTML = `
                <div class="message-header">
                    <div class="user-info">You</div>
                    <span class="timestamp">${timestamp}</span>
                </div>
                <div class="message-content">${content}</div>
            `;
        } else if (messageData.type === 'message' && messageData.data?.source) {
            // Bot/Agent message (OMNI or specialized agents)
            const source = messageData.data.source;
            const agentInfo = getAgentInfo(source);
            
            div.className = agentInfo.className;
            
            // Extract and format content properly
            let content = '';
            if (messageData.data.content?.content) {
                content = formatJsonContent(messageData.data.content.content);
            } else if (messageData.data.content?.task) {
                content = `<div class="text-content">${messageData.data.content.task}</div>`;
            } else {
                content = formatJsonContent(messageData.data.content);
            }
            
            const role = messageData.data.content?.role || 'assistant';
            const name = messageData.data.content?.name || agentInfo.name;
            
            div.innerHTML = `
                <div class="message-header">
                    <div class="bot-info">${name} (${role})</div>
                    <span class="timestamp">${timestamp}</span>
                </div>
                <div class="message-content">${content}</div>
            `;
        } else {
            // Unknown structured message - use legacy display
            div.className = `legacy-message ${className}`;
            div.innerHTML = `
                <div class="message-header">
                    ${type} <span class="timestamp">${timestamp}</span>
                </div>
                <div class="message-content">${JSON.stringify(messageData, null, 2)}</div>
            `;
        }
    } else {
        // Simple string message or legacy format
        div.className = `legacy-message ${className}`;
        const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
        div.innerHTML = `
            <div class="message-header">
                ${type} <span class="timestamp">${timestamp}</span>
            </div>
            <div class="message-content">${content}</div>
        `;
    }
    
    // Append message and copy button to wrapper
    wrapper.appendChild(div);
    wrapper.appendChild(copyBtn);
    
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
}

// Chat management functionality
async function createNewChat() {
    const statusDiv = document.getElementById("chatCreationStatus");
    const newChatBtn = document.getElementById("newChatBtn");
    
    // Show loading state
    statusDiv.className = "chat-status loading";
    statusDiv.style.display = "flex";
    statusDiv.innerHTML = '<div class="spinner"></div> Creating new chat...';
    newChatBtn.disabled = true;

    try {
        const response = await fetch('http://localhost:8000/chats/new_chat', {
            method: 'POST',
            headers: {
                'accept': 'application/json',
            },
            body: ''
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        const chatId = data.chat_id;
        
        // Update UI with success
        currentChatId = chatId;
        document.getElementById("clientId").value = chatId;
        
        statusDiv.className = "chat-status success";
        statusDiv.innerHTML = `✅ New chat created successfully! Chat ID: <strong>${chatId}</strong>`;
        
        // Add to history
        addToChatHistory(chatId);
        
        // Hide status after 3 seconds
        setTimeout(() => {
            statusDiv.style.display = "none";
        }, 3000);

    } catch (error) {
        console.error('Error creating chat:', error);
        statusDiv.className = "chat-status error";
        statusDiv.innerHTML = `❌ Failed to create chat: ${error.message}`;
        
        // Hide error after 5 seconds
        setTimeout(() => {
            statusDiv.style.display = "none";
        }, 5000);
    } finally {
        newChatBtn.disabled = false;
    }
}

function addToChatHistory(chatId) {
    // Remove if already exists
    chatHistory = chatHistory.filter(id => id !== chatId);
    // Add to beginning
    chatHistory.unshift(chatId);
    // Keep only last 5
    chatHistory = chatHistory.slice(0, 5);
    
    // Save to localStorage
    localStorage.setItem('chatHistory', JSON.stringify(chatHistory));
    
    // Update display
    displayChatHistory();
}

function displayChatHistory() {
    const historyContainer = document.getElementById("recentChats");
    const historyDiv = document.getElementById("chatHistory");
    
    if (chatHistory.length === 0) {
        historyContainer.style.display = "none";
        return;
    }
    
    historyContainer.style.display = "block";
    historyDiv.innerHTML = "";
    
    chatHistory.forEach(chatId => {
        const chatItem = document.createElement("div");
        chatItem.className = "chat-item";
        chatItem.innerHTML = `
            <div class="chat-id">${chatId}</div>
            <div class="chat-actions">
                <button class="use-btn" onclick="useChatId('${chatId}')">Use</button>
                <button class="copy-btn" onclick="copySpecificChatId('${chatId}')">Copy</button>
                <button class="delete-btn" onclick="deleteChatId('${chatId}')">Del</button>
            </div>
        `;
        historyDiv.appendChild(chatItem);
    });
}

function useChatId(chatId) {
    document.getElementById("clientId").value = chatId;
    currentChatId = chatId;
    
    // Move to top of history
    addToChatHistory(chatId);
    showToast(`Using chat ID: ${chatId.substring(0, 8)}...`);
}

function copySpecificChatId(chatId) {
    copyToClipboard(chatId);
}

function deleteChatId(chatId) {
    if (confirm(`Are you sure you want to delete chat ID: ${chatId}?`)) {
        // Remove from history
        chatHistory = chatHistory.filter(id => id !== chatId);
        
        // Save to localStorage
        localStorage.setItem('chatHistory', JSON.stringify(chatHistory));
        
        // Update display
        displayChatHistory();
        
        showToast(`Chat ID deleted: ${chatId.substring(0, 8)}...`);
    }
}

// Template functions
function fillUserQuery() {
    const textarea = document.getElementById("jsonInput");
    const userQueryJson = {
        "type": "start",
        "task": "Enter Query Here",
        "files": []
    };
    textarea.value = JSON.stringify(userQueryJson, null, 2);
    showToast("User query template loaded!");
}

function fillManualVerification() {
    const textarea = document.getElementById("jsonInput");
    const manualVerificationJson = {
        "type": "input_response",
        "response": "Input response here",
        "files": []
    };
    textarea.value = JSON.stringify(manualVerificationJson, null, 2);
    showToast("Manual verification template loaded!");
}