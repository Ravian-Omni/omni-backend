/**
 * WebSocket Test Script for Omni Backend
 * Run with: node test_websocket.js
 * 
 * Make sure to install ws package first:
 * npm install ws
 */

const WebSocket = require('ws');

class WebSocketTester {
    constructor(url, chatId) {
        this.url = url;
        this.chatId = chatId;
        this.ws = null;
        this.messageCount = 0;
    }

    log(message, type = 'INFO') {
        const timestamp = new Date().toISOString();
        console.log(`[${timestamp}] [${type}] ${message}`);
    }

    async connect() {
        const fullUrl = `${this.url}${this.chatId}`;
        
        this.log(`Connecting to: ${fullUrl}`);
        
        return new Promise((resolve, reject) => {
            try {
                this.ws = new WebSocket(fullUrl);
                
                this.ws.onopen = () => {
                    this.log('✅ WebSocket connected successfully!', 'SUCCESS');
                    resolve();
                };
                
                this.ws.onmessage = (event) => {
                    this.messageCount++;
                    this.log(`📥 Received message #${this.messageCount}: ${event.data}`, 'RECEIVE');
                    
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'pong') {
                            this.log('🏓 Pong received', 'PING');
                        } else if (data.type === 'error') {
                            this.log(`❌ Server error: ${data.error}`, 'ERROR');
                        }
                    } catch (e) {
                        this.log(`📄 Non-JSON message received`, 'RECEIVE');
                    }
                };
                
                this.ws.onclose = (event) => {
                    this.log(`🔌 WebSocket closed. Code: ${event.code}, Reason: ${event.reason}`, 'CLOSE');
                };
                
                this.ws.onerror = (error) => {
                    this.log(`❌ WebSocket error: ${error.message}`, 'ERROR');
                    reject(error);
                };
                
            } catch (error) {
                this.log(`❌ Failed to create WebSocket: ${error.message}`, 'ERROR');
                reject(error);
            }
        });
    }

    sendMessage(message) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.log('❌ WebSocket is not connected', 'ERROR');
            return false;
        }
        
        const messageStr = JSON.stringify(message);
        this.ws.send(messageStr);
        this.log(`📤 Sent: ${messageStr}`, 'SEND');
        return true;
    }

    ping() {
        return this.sendMessage({ type: 'ping' });
    }

    start(task) {
        return this.sendMessage({ 
            type: 'start', 
            task: task || 'Test task from Node.js client'
        });
    }

    stop(reason) {
        return this.sendMessage({ 
            type: 'stop', 
            reason: reason || 'Test stop from Node.js client'
        });
    }

    inputResponse(response) {
        return this.sendMessage({ 
            type: 'input_response', 
            response: response 
        });
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.log('🔌 Disconnecting...', 'INFO');
        }
    }

    async runTestSequence() {
        this.log('🚀 Starting automated test sequence...', 'TEST');
        
        const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
        
        try {
            // Test 1: Ping
            this.log('Test 1: Sending ping...', 'TEST');
            this.ping();
            await delay(1000);
            
            // Test 2: Start task
            this.log('Test 2: Starting task...', 'TEST');
            this.start('Automated test task - please respond with a simple message');
            await delay(2000);
            
            // Test 3: Another ping
            this.log('Test 3: Sending another ping...', 'TEST');
            this.ping();
            await delay(1000);
            
            // Test 4: Input response
            this.log('Test 4: Sending input response...', 'TEST');
            this.inputResponse('Yes, continue with the test');
            await delay(1000);
            
            // Test 5: Stop
            this.log('Test 5: Stopping task...', 'TEST');
            this.stop('Test sequence completed');
            await delay(1000);
            
            this.log('✅ Test sequence completed!', 'SUCCESS');
            
        } catch (error) {
            this.log(`❌ Test sequence failed: ${error.message}`, 'ERROR');
        }
    }
}

// Main execution
async function main() {
    // Configuration
    const config = {
        url: 'ws://localhost:8000/ws/runs/',
        chatId: 'test-node-client-' + Date.now(),
        runTests: true
    };
    
    console.log('🔌 WebSocket Test Client for Omni Backend');
    console.log('==========================================');
    console.log(`URL: ${config.url}`);
    console.log(`Chat ID: ${config.chatId}`);
    console.log('');
    
    const tester = new WebSocketTester(config.url, config.chatId);
    
    try {
        // Connect
        await tester.connect();
        
        if (config.runTests) {
            // Wait a bit before starting tests
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Run automated test sequence
            await tester.runTestSequence();
            
            // Wait a bit before disconnecting
            await new Promise(resolve => setTimeout(resolve, 2000));
        } else {
            // Manual testing mode - keep connection open
            tester.log('💡 Manual testing mode. Connection will stay open.', 'INFO');
            tester.log('💡 You can send messages using the tester object methods:', 'INFO');
            tester.log('💡 tester.ping(), tester.start("task"), tester.stop(), etc.', 'INFO');
            
            // Keep the process alive
            process.stdin.resume();
        }
        
    } catch (error) {
        tester.log(`❌ Connection failed: ${error.message}`, 'ERROR');
        process.exit(1);
    }
    
    // Graceful shutdown
    process.on('SIGINT', () => {
        tester.log('🛑 Received SIGINT, closing connection...', 'INFO');
        tester.disconnect();
        process.exit(0);
    });
    
    // Auto-disconnect after tests
    if (config.runTests) {
        setTimeout(() => {
            tester.disconnect();
            process.exit(0);
        }, 5000);
    }
}

// Export for programmatic use
module.exports = WebSocketTester;

// Run if called directly
if (require.main === module) {
    main().catch(console.error);
}
