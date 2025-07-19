# 🚀 Electron App Integration Guide for ARM64 macOS

This guide shows how to integrate the Python backend with bundled Python into your Electron app for Apple Silicon Macs.

## 📦 What's Bundled

Your executable now includes:

- **Python 3.12.7** (ARM64 native)
- **Base virtual environment** with common packages
- **Complete isolation** for each project
- **No Python installation required** for users

## 🏗️ Electron App Structure

```
your-electron-app/
├── main.js                          # Electron main process
├── preload.js                       # Preload script
├── renderer/
│   ├── index.html                   # Main UI
│   ├── style.css                    # Styles
│   └── renderer.js                  # Frontend logic
├── resources/                       # App resources
│   └── omni-backend-app            # Your bundled Python backend
├── package.json
└── electron-builder.yml            # Build configuration
```

## 📋 Step-by-Step Integration

### Step 1: Copy the Executable

```bash
# Copy your built executable to Electron resources
cp /Users/voidfinder/Work/Ravian/ravian-omni/omni-backend/dist/omni-backend-app your-electron-app/resources/
```

### Step 2: Main Process (main.js)

```javascript
const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

class OmniBackendManager {
  constructor() {
    this.backendProcess = null;
    this.backendPort = 8000;
    this.isReady = false;
  }

  getExecutablePath() {
    if (app.isPackaged) {
      // Production: bundled with app
      return path.join(process.resourcesPath, "omni-backend-app");
    } else {
      // Development: use local build
      return path.join(__dirname, "resources", "omni-backend-app");
    }
  }

  async start() {
    return new Promise((resolve, reject) => {
      const execPath = this.getExecutablePath();

      if (!fs.existsSync(execPath)) {
        reject(new Error(`Backend executable not found at: ${execPath}`));
        return;
      }

      console.log("Starting Omni backend...");
      this.backendProcess = spawn(execPath, [], {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          PYTHONPATH: "", // Clear to use bundled Python
        },
      });

      let startupTimeout = setTimeout(() => {
        reject(new Error("Backend startup timeout"));
      }, 30000);

      this.backendProcess.stdout.on("data", (data) => {
        const output = data.toString();
        console.log("[Backend]", output);

        if (
          output.includes("Application startup complete") ||
          output.includes("Uvicorn running")
        ) {
          clearTimeout(startupTimeout);
          this.isReady = true;
          resolve();
        }
      });

      this.backendProcess.stderr.on("data", (data) => {
        console.error("[Backend Error]", data.toString());
      });

      this.backendProcess.on("error", (error) => {
        clearTimeout(startupTimeout);
        reject(error);
      });

      this.backendProcess.on("exit", (code) => {
        console.log(`Backend exited with code: ${code}`);
        this.isReady = false;
      });
    });
  }

  async stop() {
    if (this.backendProcess) {
      this.backendProcess.kill("SIGTERM");

      // Wait for graceful shutdown
      await new Promise((resolve) => {
        if (this.backendProcess) {
          this.backendProcess.on("exit", resolve);
          setTimeout(() => {
            if (this.backendProcess) {
              this.backendProcess.kill("SIGKILL");
            }
            resolve();
          }, 5000);
        } else {
          resolve();
        }
      });

      this.backendProcess = null;
    }
  }

  getBaseUrl() {
    return `http://localhost:${this.backendPort}`;
  }
}

// Global backend manager
const omniBackend = new OmniBackendManager();

async function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  await win.loadFile("renderer/index.html");

  // Send backend URL to renderer
  win.webContents.send("backend-ready", {
    baseUrl: omniBackend.getBaseUrl(),
    isReady: omniBackend.isReady,
  });
}

// App lifecycle
app.whenReady(async () => {
  try {
    await omniBackend.start();
    console.log("✅ Backend started successfully");
    await createWindow();
  } catch (error) {
    console.error("❌ Failed to start backend:", error);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    await createWindow();
  }
});

app.on("before-quit", async () => {
  console.log("Stopping backend...");
  await omniBackend.stop();
});

// IPC handlers
ipcMain.handle("get-backend-url", () => {
  return omniBackend.getBaseUrl();
});

ipcMain.handle("is-backend-ready", () => {
  return omniBackend.isReady;
});
```

### Step 3: Preload Script (preload.js)

```javascript
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // Backend communication
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  isBackendReady: () => ipcRenderer.invoke("is-backend-ready"),

  // Listen for backend events
  onBackendReady: (callback) => {
    ipcRenderer.on("backend-ready", callback);
  },

  // Remove listeners
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  },
});
```

### Step 4: Frontend (renderer.js)

```javascript
class OmniClient {
    constructor() {
        this.baseUrl = null;
        this.websocket = null;
        this.sessionId = null;
        this.init();
    }

    async init() {
        // Get backend URL from main process
        this.baseUrl = await window.electronAPI.getBackendUrl();

        // Listen for backend ready event
        window.electronAPI.onBackendReady((event, data) => {
            console.log('Backend ready:', data);
            this.baseUrl = data.baseUrl;
            this.onBackendReady();
        });

        // Check if backend is ready
        const isReady = await window.electronAPI.isBackendReady();
        if (isReady) {
            this.onBackendReady();
        }
    }

    onBackendReady() {
        console.log('🚀 Backend is ready at:', this.baseUrl);
        document.getElementById('status').textContent = 'Backend Ready';
        document.getElementById('status').className = 'status ready';
    }

    generateSessionId() {
        return 'session-' + Math.random().toString(36).substr(2, 9);
    }

    async connectWebSocket() {
        this.sessionId = this.generateSessionId();
        const wsUrl = this.baseUrl.replace('http://', 'ws://') + `/ws/${this.sessionId}`;

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = () => {
            console.log('✅ WebSocket connected');
            document.getElementById('connection-status').textContent = 'Connected';
        };

        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };

        this.websocket.onclose = () => {
            console.log('❌ WebSocket disconnected');
            document.getElementById('connection-status').textContent = 'Disconnected';
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleMessage(data) {
        const outputDiv = document.getElementById('output');

        if (data.type === 'agent_message') {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message';
            messageDiv.innerHTML = \`
                <strong>\${data.agent}:</strong>
                <div class="content">\${data.content}</div>
            \`;
            outputDiv.appendChild(messageDiv);
        } else if (data.type === 'code_execution') {
            const codeDiv = document.createElement('div');
            codeDiv.className = 'code-execution';
            codeDiv.innerHTML = \`
                <strong>Code Execution (Exit Code: \${data.exit_code}):</strong>
                <pre class="code-output">\${data.output}</pre>
                <small>Venv: \${data.venv_path || 'Isolated Environment'}</small>
            \`;
            outputDiv.appendChild(codeDiv);
        }

        outputDiv.scrollTop = outputDiv.scrollHeight;
    }

    async sendQuery(query) {
        if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
            await this.connectWebSocket();

            // Wait for connection
            await new Promise(resolve => {
                const check = () => {
                    if (this.websocket.readyState === WebSocket.OPEN) {
                        resolve();
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            });
        }

        const message = {
            type: 'start',
            query: query,
            session_id: this.sessionId
        };

        this.websocket.send(JSON.stringify(message));
    }
}

// Initialize client when page loads
let omniClient;

document.addEventListener('DOMContentLoaded', () => {
    omniClient = new OmniClient();

    // Setup UI event handlers
    document.getElementById('send-button').addEventListener('click', async () => {
        const query = document.getElementById('query-input').value.trim();
        if (query) {
            await omniClient.sendQuery(query);
            document.getElementById('query-input').value = '';
        }
    });

    document.getElementById('query-input').addEventListener('keypress', async (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const query = e.target.value.trim();
            if (query) {
                await omniClient.sendQuery(query);
                e.target.value = '';
            }
        }
    });
});
```

### Step 5: HTML Interface (renderer/index.html)

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>Omni - AI Code Assistant</title>
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <div class="container">
      <header>
        <h1>🤖 Omni - AI Code Assistant</h1>
        <div class="status-bar">
          <span id="status" class="status">Starting...</span>
          <span id="connection-status" class="connection-status"
            >Not Connected</span
          >
        </div>
      </header>

      <main>
        <div class="output-container">
          <div id="output" class="output"></div>
        </div>

        <div class="input-container">
          <textarea
            id="query-input"
            placeholder="Ask me to write Python code... (e.g., 'Write code to analyze a CSV file')"
            rows="3"
          ></textarea>
          <button id="send-button">Send</button>
        </div>
      </main>
    </div>

    <script src="renderer.js"></script>
  </body>
</html>
```

### Step 6: Package Configuration

**package.json:**

```json
{
  "name": "omni-electron-app",
  "version": "1.0.0",
  "description": "AI Code Assistant with Python Runtime",
  "main": "main.js",
  "scripts": {
    "start": "electron .",
    "build": "electron-builder",
    "dist": "electron-builder --publish=never"
  },
  "build": {
    "appId": "com.yourcompany.omni",
    "productName": "Omni AI Assistant",
    "directories": {
      "output": "dist"
    },
    "files": ["main.js", "preload.js", "renderer/**/*", "package.json"],
    "extraResources": [
      {
        "from": "resources/omni-backend-app",
        "to": "omni-backend-app"
      }
    ],
    "mac": {
      "category": "public.app-category.developer-tools",
      "target": {
        "target": "default",
        "arch": ["arm64"]
      }
    }
  },
  "devDependencies": {
    "electron": "^28.0.0",
    "electron-builder": "^24.0.0"
  }
}
```

## 🎯 Key Benefits

### ✅ **Complete Self-Contained**

- No Python installation required
- No dependency conflicts
- Works on clean ARM64 Macs

### ✅ **Isolated Execution**

- Each project gets its own virtual environment
- No package conflicts between projects
- Clean execution environment

### ✅ **ARM64 Optimized**

- Native ARM64 Python (3.12.7)
- Optimized for Apple Silicon
- Fast startup and execution

## 🚀 Building Your App

```bash
# Install dependencies
npm install

# Run in development
npm start

# Build for distribution
npm run build
```

## 📱 User Experience

Users simply:

1. **Download your app** (.dmg file)
2. **Drag to Applications**
3. **Launch and start coding!**

No Python installation, no setup, no configuration needed! 🎉

## 🔧 Troubleshooting

### Backend Won't Start

- Check executable permissions: `chmod +x resources/omni-backend-app`
- Verify bundled Python: Look for bundled_python in the app bundle

### WebSocket Connection Issues

- Ensure backend started completely before frontend connection
- Check firewall settings for localhost connections

### Virtual Environment Creation Fails

- The bundled Python should handle this automatically
- Check logs for specific Python path issues

---

Your Electron app now has a complete, self-contained Python runtime with virtual environment isolation! 🚀
