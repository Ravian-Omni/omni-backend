// Advanced WebSocket Client Utilities
// Save this as: websocket-utils.js

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.pingInterval = null;
        this.connectionQuality = 'unknown';
        this.latency = 0;
        this.messageQueue = [];
        this.isOnline = navigator.onLine;
        this.listeners = new Map();
        
        this.setupOnlineDetection();
    }

    // Event system
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    off(event, callback) {
        if (this.listeners.has(event)) {
            const callbacks = this.listeners.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
    }

    emit(event, data) {
        if (this.listeners.has(event)) {
            this.listeners.get(event).forEach(callback => callback(data));
        }
    }

    // Online/Offline detection
    setupOnlineDetection() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.emit('online', true);
            if (this.ws && this.ws.readyState !== WebSocket.OPEN) {
                this.reconnect();
            }
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.emit('offline', true);
        });
    }

    // Connection with quality monitoring
    connect(url, protocols = []) {
        return new Promise((resolve, reject) => {
            if (!this.isOnline) {
                reject(new Error('No internet connection'));
                return;
            }

            this.ws = new WebSocket(url, protocols);
            const startTime = Date.now();

            this.ws.onopen = () => {
                this.latency = Date.now() - startTime;
                this.reconnectAttempts = 0;
                this.updateConnectionQuality();
                this.startPingMonitoring();
                this.flushMessageQueue();
                this.emit('connected', { latency: this.latency });
                resolve();
            };

            this.ws.onmessage = (event) => {
                this.emit('message', event);
            };

            this.ws.onclose = (event) => {
                this.stopPingMonitoring();
                this.emit('disconnected', event);
                
                if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.scheduleReconnect(url, protocols);
                }
            };

            this.ws.onerror = (error) => {
                this.emit('error', error);
                reject(error);
            };
        });
    }

    // Ping monitoring for connection quality
    startPingMonitoring() {
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                const pingStart = Date.now();
                const pingData = JSON.stringify({ type: 'ping', timestamp: pingStart });
                
                this.ws.send(pingData);
                
                // Listen for pong response (you'd need to implement this on the server)
                const pongHandler = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'pong' && data.timestamp === pingStart) {
                            this.latency = Date.now() - pingStart;
                            this.updateConnectionQuality();
                            this.emit('ping', { latency: this.latency });
                        }
                    } catch (e) {
                        // Not a pong message, ignore
                    }
                };
                
                // Remove the listener after a short timeout
                setTimeout(() => {
                    this.ws.removeEventListener('message', pongHandler);
                }, 5000);
                
                this.ws.addEventListener('message', pongHandler);
            }
        }, 30000); // Ping every 30 seconds
    }

    stopPingMonitoring() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    updateConnectionQuality() {
        if (this.latency < 100) {
            this.connectionQuality = 'excellent';
        } else if (this.latency < 300) {
            this.connectionQuality = 'good';
        } else if (this.latency < 1000) {
            this.connectionQuality = 'fair';
        } else {
            this.connectionQuality = 'poor';
        }
        
        this.emit('qualityChange', {
            quality: this.connectionQuality,
            latency: this.latency
        });
    }

    // Smart reconnection with exponential backoff
    scheduleReconnect(url, protocols) {
        this.reconnectAttempts++;
        const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );
        
        this.emit('reconnecting', {
            attempt: this.reconnectAttempts,
            maxAttempts: this.maxReconnectAttempts,
            delay: delay
        });

        setTimeout(() => {
            this.connect(url, protocols).catch(() => {
                // Reconnection failed, will try again if under max attempts
            });
        }, delay);
    }

    // Message queuing for offline scenarios
    send(data) {
        const message = {
            data: data,
            timestamp: Date.now(),
            id: this.generateMessageId()
        };

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(data);
            this.emit('messageSent', message);
            return message.id;
        } else {
            this.messageQueue.push(message);
            this.emit('messageQueued', message);
            return message.id;
        }
    }

    flushMessageQueue() {
        while (this.messageQueue.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
            const message = this.messageQueue.shift();
            this.ws.send(message.data);
            this.emit('messageSent', message);
        }
    }

    generateMessageId() {
        return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    disconnect() {
        this.stopPingMonitoring();
        if (this.ws) {
            this.ws.close(1000, 'User initiated disconnect');
        }
    }

    getStatus() {
        return {
            readyState: this.ws ? this.ws.readyState : WebSocket.CLOSED,
            connectionQuality: this.connectionQuality,
            latency: this.latency,
            isOnline: this.isOnline,
            queuedMessages: this.messageQueue.length,
            reconnectAttempts: this.reconnectAttempts
        };
    }
}

class MessageStore {
    constructor(maxMessages = 10000) {
        this.messages = [];
        this.maxMessages = maxMessages;
        this.searchIndex = new Map();
        this.filters = {
            type: 'all',
            source: 'all',
            dateRange: null,
            searchTerm: ''
        };
    }

    addMessage(message) {
        const enrichedMessage = {
            ...message,
            id: this.generateId(),
            timestamp: message.timestamp || Date.now(),
            searchText: this.extractSearchableText(message)
        };

        this.messages.unshift(enrichedMessage);
        this.updateSearchIndex(enrichedMessage);

        // Trim messages if over limit
        if (this.messages.length > this.maxMessages) {
            const removed = this.messages.splice(this.maxMessages);
            removed.forEach(msg => this.removeFromSearchIndex(msg));
        }

        return enrichedMessage.id;
    }

    extractSearchableText(message) {
        let text = '';
        
        if (typeof message.content === 'string') {
            text = message.content;
        } else if (typeof message.content === 'object') {
            text = JSON.stringify(message.content);
        }
        
        if (message.data && typeof message.data === 'object') {
            text += ' ' + JSON.stringify(message.data);
        }
        
        return text.toLowerCase();
    }

    updateSearchIndex(message) {
        const words = message.searchText.split(/\s+/);
        words.forEach(word => {
            if (word.length > 2) { // Index words longer than 2 characters
                if (!this.searchIndex.has(word)) {
                    this.searchIndex.set(word, new Set());
                }
                this.searchIndex.get(word).add(message.id);
            }
        });
    }

    removeFromSearchIndex(message) {
        const words = message.searchText.split(/\s+/);
        words.forEach(word => {
            if (this.searchIndex.has(word)) {
                this.searchIndex.get(word).delete(message.id);
                if (this.searchIndex.get(word).size === 0) {
                    this.searchIndex.delete(word);
                }
            }
        });
    }

    search(term) {
        if (!term) return this.messages;
        
        const searchWords = term.toLowerCase().split(/\s+/);
        let candidateIds = null;

        searchWords.forEach(word => {
            const matchingIds = this.searchIndex.get(word) || new Set();
            
            if (candidateIds === null) {
                candidateIds = new Set(matchingIds);
            } else {
                // Intersection of sets (AND operation)
                candidateIds = new Set([...candidateIds].filter(id => matchingIds.has(id)));
            }
        });

        if (!candidateIds) return [];
        
        return this.messages.filter(msg => candidateIds.has(msg.id));
    }

    filter(filters = {}) {
        this.filters = { ...this.filters, ...filters };
        
        let filtered = this.messages;

        // Apply search filter
        if (this.filters.searchTerm) {
            filtered = this.search(this.filters.searchTerm);
        }

        // Apply type filter
        if (this.filters.type !== 'all') {
            filtered = filtered.filter(msg => {
                switch (this.filters.type) {
                    case 'sent':
                        return msg.direction === 'sent' || msg.source === 'user';
                    case 'received':
                        return msg.direction === 'received' || msg.source !== 'user';
                    case 'system':
                        return msg.type === 'system' || msg.type === 'completion';
                    case 'error':
                        return msg.type === 'error' || msg.content?.includes('error');
                    default:
                        return true;
                }
            });
        }

        // Apply source filter
        if (this.filters.source !== 'all') {
            filtered = filtered.filter(msg => msg.source === this.filters.source);
        }

        // Apply date range filter
        if (this.filters.dateRange) {
            const { start, end } = this.filters.dateRange;
            filtered = filtered.filter(msg => {
                const msgDate = new Date(msg.timestamp);
                return msgDate >= start && msgDate <= end;
            });
        }

        return filtered;
    }

    exportMessages(format = 'json', filters = null) {
        const messages = filters ? this.filter(filters) : this.messages;
        
        switch (format.toLowerCase()) {
            case 'json':
                return JSON.stringify(messages, null, 2);
                
            case 'csv':
                const headers = ['Timestamp', 'Type', 'Source', 'Content'];
                const csvRows = messages.map(msg => {
                    const timestamp = new Date(msg.timestamp).toISOString();
                    const type = msg.type || 'unknown';
                    const source = msg.source || 'unknown';
                    const content = (typeof msg.content === 'object' ? 
                        JSON.stringify(msg.content) : msg.content || '').replace(/"/g, '""');
                    return `"${timestamp}","${type}","${source}","${content}"`;
                });
                return [headers.join(','), ...csvRows].join('\n');
                
            case 'txt':
                return messages.map(msg => {
                    const timestamp = new Date(msg.timestamp).toLocaleString();
                    const source = msg.source || 'unknown';
                    const content = typeof msg.content === 'object' ? 
                        JSON.stringify(msg.content, null, 2) : msg.content || '';
                    return `[${timestamp}] ${source}:\n${content}\n${'='.repeat(50)}`;
                }).join('\n');
                
            case 'html':
                const htmlMessages = messages.map(msg => {
                    const timestamp = new Date(msg.timestamp).toLocaleString();
                    const source = msg.source || 'unknown';
                    const content = typeof msg.content === 'object' ? 
                        `<pre>${JSON.stringify(msg.content, null, 2)}</pre>` : 
                        `<p>${msg.content || ''}</p>`;
                    return `
                        <div class="message">
                            <div class="header">
                                <strong>${source}</strong>
                                <span class="timestamp">${timestamp}</span>
                            </div>
                            <div class="content">${content}</div>
                        </div>
                    `;
                }).join('');
                
                return `
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Chat Export</title>
                        <style>
                            body { font-family: Arial, sans-serif; margin: 20px; }
                            .message { margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 10px; }
                            .header { display: flex; justify-content: space-between; margin-bottom: 10px; }
                            .timestamp { color: #666; font-size: 0.9em; }
                            pre { background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }
                        </style>
                    </head>
                    <body>
                        <h1>Chat Export - ${new Date().toLocaleDateString()}</h1>
                        ${htmlMessages}
                    </body>
                    </html>
                `;
                
            default:
                throw new Error(`Unsupported export format: ${format}`);
        }
    }

    generateId() {
        return `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    clear() {
        this.messages = [];
        this.searchIndex.clear();
    }

    getStats() {
        const stats = {
            total: this.messages.length,
            byType: {},
            bySource: {},
            dateRange: null
        };

        if (this.messages.length > 0) {
            stats.dateRange = {
                oldest: this.messages[this.messages.length - 1].timestamp,
                newest: this.messages[0].timestamp
            };
        }

        this.messages.forEach(msg => {
            // Count by type
            const type = msg.type || 'unknown';
            stats.byType[type] = (stats.byType[type] || 0) + 1;

            // Count by source
            const source = msg.source || 'unknown';
            stats.bySource[source] = (stats.bySource[source] || 0) + 1;
        });

        return stats;
    }
}

class VirtualScrollManager {
    constructor(container, itemHeight = 50, buffer = 10) {
        this.container = container;
        this.itemHeight = itemHeight;
        this.buffer = buffer;
        this.items = [];
        this.visibleStart = 0;
        this.visibleEnd = 0;
        this.scrollTop = 0;
        this.containerHeight = 0;
        
        this.setupContainer();
        this.setupScrollListener();
    }

    setupContainer() {
        this.container.style.position = 'relative';
        this.container.style.overflow = 'auto';
        
        // Create viewport and content containers
        this.viewport = document.createElement('div');
        this.viewport.style.position = 'absolute';
        this.viewport.style.top = '0';
        this.viewport.style.left = '0';
        this.viewport.style.right = '0';
        
        this.content = document.createElement('div');
        this.content.style.position = 'relative';
        
        this.viewport.appendChild(this.content);
        this.container.appendChild(this.viewport);
    }

    setupScrollListener() {
        this.container.addEventListener('scroll', () => {
            this.scrollTop = this.container.scrollTop;
            this.updateVisibleRange();
            this.render();
        });

        // Update container height on resize
        const resizeObserver = new ResizeObserver(() => {
            this.containerHeight = this.container.clientHeight;
            this.updateVisibleRange();
            this.render();
        });
        resizeObserver.observe(this.container);
    }

    setItems(items) {
        this.items = items;
        this.updateScrollHeight();
        this.updateVisibleRange();
        this.render();
    }

    updateScrollHeight() {
        const totalHeight = this.items.length * this.itemHeight;
        this.container.style.height = `${totalHeight}px`;
    }

    updateVisibleRange() {
        const containerHeight = this.container.clientHeight;
        const itemsPerPage = Math.ceil(containerHeight / this.itemHeight);
        
        this.visibleStart = Math.max(0, 
            Math.floor(this.scrollTop / this.itemHeight) - this.buffer
        );
        this.visibleEnd = Math.min(this.items.length - 1,
            this.visibleStart + itemsPerPage + (this.buffer * 2)
        );
    }

    render() {
        // Clear current content
        this.content.innerHTML = '';
        
        // Set the offset for visible items
        this.content.style.transform = `translateY(${this.visibleStart * this.itemHeight}px)`;
        
        // Render only visible items
        for (let i = this.visibleStart; i <= this.visibleEnd; i++) {
            if (this.items[i]) {
                const element = this.renderItem(this.items[i], i);
                element.style.height = `${this.itemHeight}px`;
                element.style.position = 'relative';
                element.dataset.index = i;
                this.content.appendChild(element);
            }
        }
    }

    renderItem(item, index) {
        // Override this method to customize item rendering
        const div = document.createElement('div');
        div.className = 'virtual-scroll-item';
        div.textContent = `Item ${index}: ${JSON.stringify(item)}`;
        return div;
    }

    scrollToIndex(index) {
        const targetScrollTop = index * this.itemHeight;
        this.container.scrollTop = targetScrollTop;
    }

    scrollToBottom() {
        this.container.scrollTop = this.container.scrollHeight;
    }
}

class PerformanceMonitor {
    constructor() {
        this.metrics = {
            messageCount: 0,
            renderTime: [],
            memoryUsage: [],
            connectionUptime: 0,
            reconnections: 0
        };
        this.startTime = Date.now();
        this.lastMemoryCheck = Date.now();
    }

    recordRenderTime(duration) {
        this.metrics.renderTime.push(duration);
        // Keep only last 100 measurements
        if (this.metrics.renderTime.length > 100) {
            this.metrics.renderTime.shift();
        }
    }

    recordMessage() {
        this.metrics.messageCount++;
    }

    recordReconnection() {
        this.metrics.reconnections++;
    }

    checkMemoryUsage() {
        if (performance.memory) {
            const usage = {
                used: performance.memory.usedJSHeapSize,
                total: performance.memory.totalJSHeapSize,
                limit: performance.memory.jsHeapSizeLimit,
                timestamp: Date.now()
            };
            
            this.metrics.memoryUsage.push(usage);
            // Keep only last hour of measurements (assuming check every minute)
            if (this.metrics.memoryUsage.length > 60) {
                this.metrics.memoryUsage.shift();
            }
        }
    }

    getAverageRenderTime() {
        if (this.metrics.renderTime.length === 0) return 0;
        const sum = this.metrics.renderTime.reduce((a, b) => a + b, 0);
        return sum / this.metrics.renderTime.length;
    }

    getMemoryTrend() {
        if (this.metrics.memoryUsage.length < 2) return 'stable';
        
        const recent = this.metrics.memoryUsage.slice(-5);
        const older = this.metrics.memoryUsage.slice(-10, -5);
        
        if (recent.length === 0 || older.length === 0) return 'stable';
        
        const recentAvg = recent.reduce((sum, m) => sum + m.used, 0) / recent.length;
        const olderAvg = older.reduce((sum, m) => sum + m.used, 0) / older.length;
        
        const change = (recentAvg - olderAvg) / olderAvg;
        
        if (change > 0.1) return 'increasing';
        if (change < -0.1) return 'decreasing';
        return 'stable';
    }

    getReport() {
        return {
            uptime: Date.now() - this.startTime,
            messageCount: this.metrics.messageCount,
            messagesPerMinute: this.metrics.messageCount / ((Date.now() - this.startTime) / 60000),
            averageRenderTime: this.getAverageRenderTime(),
            reconnections: this.metrics.reconnections,
            memoryTrend: this.getMemoryTrend(),
            currentMemory: this.metrics.memoryUsage[this.metrics.memoryUsage.length - 1] || null
        };
    }
}

// Touch gesture support for mobile
class TouchGestureHandler {
    constructor(element) {
        this.element = element;
        this.startX = 0;
        this.startY = 0;
        this.threshold = 50;
        this.restraint = 100;
        this.allowedTime = 300;
        this.startTime = 0;
        
        this.setupTouchEvents();
    }

    setupTouchEvents() {
        this.element.addEventListener('touchstart', (e) => {
            const touch = e.changedTouches[0];
            this.startX = touch.pageX;
            this.startY = touch.pageY;
            this.startTime = Date.now();
        }, { passive: true });

        this.element.addEventListener('touchend', (e) => {
            const touch = e.changedTouches[0];
            const distX = touch.pageX - this.startX;
            const distY = touch.pageY - this.startY;
            const elapsedTime = Date.now() - this.startTime;
            
            if (elapsedTime <= this.allowedTime) {
                if (Math.abs(distX) >= this.threshold && Math.abs(distY) <= this.restraint) {
                    // Horizontal swipe
                    const direction = distX > 0 ? 'right' : 'left';
                    this.onSwipe(direction, distX);
                } else if (Math.abs(distY) >= this.threshold && Math.abs(distX) <= this.restraint) {
                    // Vertical swipe
                    const direction = distY > 0 ? 'down' : 'up';
                    this.onSwipe(direction, distY);
                }
            }
        }, { passive: true });
    }

    onSwipe(direction, distance) {
        const event = new CustomEvent('swipe', {
            detail: { direction, distance }
        });
        this.element.dispatchEvent(event);
    }
}

// Export utilities for use in main application
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        WebSocketManager,
        MessageStore,
        VirtualScrollManager,
        PerformanceMonitor,
        TouchGestureHandler
    };
} else if (typeof window !== 'undefined') {
    window.WebSocketUtils = {
        WebSocketManager,
        MessageStore,
        VirtualScrollManager,
        PerformanceMonitor,
        TouchGestureHandler
    };
}