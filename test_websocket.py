#!/usr/bin/env python3
"""
WebSocket Test Script for Omni Backend
Run with: python test_websocket.py

Make sure to install websockets package first:
pip install websockets
"""

import asyncio
import json
import websockets
import time
from datetime import datetime
from typing import Optional


class WebSocketTester:
    def __init__(self, url: str, chat_id: str):
        self.url = url
        self.chat_id = chat_id
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.message_count = 0
        
    def log(self, message: str, msg_type: str = "INFO"):
        timestamp = datetime.now().isoformat()
        print(f"[{timestamp}] [{msg_type}] {message}")
    
    async def connect(self):
        """Connect to the WebSocket server"""
        full_url = f"{self.url}{self.chat_id}"
        self.log(f"Connecting to: {full_url}")
        
        try:
            self.websocket = await websockets.connect(full_url)
            self.log("✅ WebSocket connected successfully!", "SUCCESS")
            
            # Start listening for messages
            asyncio.create_task(self._listen_for_messages())
            
        except Exception as e:
            self.log(f"❌ Failed to connect: {str(e)}", "ERROR")
            raise
    
    async def _listen_for_messages(self):
        """Listen for incoming messages"""
        try:
            async for message in self.websocket:
                self.message_count += 1
                self.log(f"📥 Received message #{self.message_count}: {message}", "RECEIVE")
                
                try:
                    data = json.loads(message)
                    if data.get("type") == "pong":
                        self.log("🏓 Pong received", "PING")
                    elif data.get("type") == "error":
                        self.log(f"❌ Server error: {data.get('error')}", "ERROR")
                except json.JSONDecodeError:
                    self.log("📄 Non-JSON message received", "RECEIVE")
                    
        except websockets.exceptions.ConnectionClosed:
            self.log("🔌 Connection closed by server", "CLOSE")
        except Exception as e:
            self.log(f"❌ Error listening for messages: {str(e)}", "ERROR")
    
    async def send_message(self, message: dict) -> bool:
        """Send a message to the server"""
        if not self.websocket or self.websocket.closed:
            self.log("❌ WebSocket is not connected", "ERROR")
            return False
        
        try:
            message_str = json.dumps(message)
            await self.websocket.send(message_str)
            self.log(f"📤 Sent: {message_str}", "SEND")
            return True
        except Exception as e:
            self.log(f"❌ Failed to send message: {str(e)}", "ERROR")
            return False
    
    async def ping(self):
        """Send a ping message"""
        return await self.send_message({"type": "ping"})
    
    async def start(self, task: str = None):
        """Send a start message"""
        return await self.send_message({
            "type": "start",
            "task": task or "Test task from Python client"
        })
    
    async def stop(self, reason: str = None):
        """Send a stop message"""
        return await self.send_message({
            "type": "stop", 
            "reason": reason or "Test stop from Python client"
        })
    
    async def input_response(self, response: str):
        """Send an input response"""
        return await self.send_message({
            "type": "input_response",
            "response": response
        })
    
    async def disconnect(self):
        """Disconnect from the WebSocket server"""
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
            self.log("🔌 Disconnected", "INFO")
    
    async def run_test_sequence(self):
        """Run an automated test sequence"""
        self.log("🚀 Starting automated test sequence...", "TEST")
        
        try:
            # Test 1: Ping
            self.log("Test 1: Sending ping...", "TEST")
            await self.ping()
            await asyncio.sleep(1)
            
            # Test 2: Start task
            self.log("Test 2: Starting task...", "TEST")
            await self.start("Automated test task - please respond with a simple message")
            await asyncio.sleep(2)
            
            # Test 3: Another ping
            self.log("Test 3: Sending another ping...", "TEST")
            await self.ping()
            await asyncio.sleep(1)
            
            # Test 4: Input response
            self.log("Test 4: Sending input response...", "TEST")
            await self.input_response("Yes, continue with the test")
            await asyncio.sleep(1)
            
            # Test 5: Stop
            self.log("Test 5: Stopping task...", "TEST")
            await self.stop("Test sequence completed")
            await asyncio.sleep(1)
            
            self.log("✅ Test sequence completed!", "SUCCESS")
            
        except Exception as e:
            self.log(f"❌ Test sequence failed: {str(e)}", "ERROR")


async def main():
    """Main function"""
    # Configuration
    config = {
        "url": "ws://localhost:8000/ws/runs/",
        "chat_id": f"test-python-client-{int(time.time())}",
        "run_tests": True
    }
    
    print("🔌 WebSocket Test Client for Omni Backend")
    print("==========================================")
    print(f"URL: {config['url']}")
    print(f"Chat ID: {config['chat_id']}")
    print("")
    
    tester = WebSocketTester(config["url"], config["chat_id"])
    
    try:
        # Connect
        await tester.connect()
        
        if config["run_tests"]:
            # Wait a bit before starting tests
            await asyncio.sleep(1)
            
            # Run automated test sequence
            await tester.run_test_sequence()
            
            # Wait a bit before disconnecting
            await asyncio.sleep(2)
        else:
            # Manual testing mode
            tester.log("💡 Manual testing mode. Use the tester object methods:", "INFO")
            tester.log("💡 await tester.ping(), await tester.start('task'), etc.", "INFO")
            
            # Keep connection alive for manual testing
            while True:
                await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        tester.log("🛑 Received keyboard interrupt, closing connection...", "INFO")
    except Exception as e:
        tester.log(f"❌ Connection failed: {str(e)}", "ERROR")
    finally:
        await tester.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
