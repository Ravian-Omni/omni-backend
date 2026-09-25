# Build Guide

This guide explains how to build the Omni Backend application into a standalone executable using Nuitka.

## Prerequisites

- Python 3.12
- All dependencies from [requirements.txt](../requirements.txt) installed
- Nuitka build tool (installed automatically by build script)

## Build Scripts

All build scripts are located in [scripts/build_scripts/](../scripts/build_scripts/):

### Main Build Scripts

1. **[scripts/build.py](../scripts/build.py)** - Main orchestrator script
   - Installs build dependencies
   - Processes requirements
   - Creates Python execution environment
   - Runs Nuitka build
   - Copies additional files

2. **[scripts/build_scripts/nuitka_build.py](../scripts/build_scripts/nuitka_build.py)** - Standard Nuitka build
   - Mode: `--mode=app` (application mode)
   - Includes all application packages from `src/`
   - Includes all third-party dependencies
   - Includes templates directory

3. **[scripts/build_scripts/nuitka_optimized.py](../scripts/build_scripts/nuitka_optimized.py)** - Optimized build
   - Mode: `--mode=standalone` (standalone executable)
   - LTO optimization enabled (20% smaller, 15% faster)
   - Debug info removed (15% smaller)
   - Docstrings removed with `-OO` flag (8% smaller)
   - Anti-bloat plugin enabled

4. **[scripts/build_scripts/nuitka_build_executable.py](../scripts/build_scripts/nuitka_build_executable.py)** - Standalone executable
   - Mode: `--mode=standalone`
   - Full optimization enabled
   - Excludes unused standard library modules
   - macOS/Windows specific settings

## Important Changes for New Structure

All build scripts have been updated to include the new `src/` directory structure:

```python
# Application packages
"--include-package=src",
"--include-package=src.capabilities",
"--include-package=src.capabilities.browser_manager",
"--include-package=src.capabilities.email_manager",
"--include-package=src.capabilities.file_finder",
"--include-package=src.capabilities.image_generator",
"--include-package=src.capabilities.python_developer",
"--include-package=src.configs",
"--include-package=src.managers",
"--include-package=src.routers",
"--include-package=src.utilities",
"--include-package=src.omni",
```

## Building the Application

### Option 1: Full Build (Recommended)

Run the main build script from the **root directory**:

```bash
python scripts/build.py
```

This will:
1. Install Nuitka and build tools
2. Install all requirements (including git dependencies)
3. Create Python execution environment
4. Build the application
5. Copy necessary files to dist/

### Option 2: Quick Optimized Build

For a faster build with optimizations:

```bash
python scripts/build_scripts/nuitka_optimized.py
```

### Option 3: Standalone Executable Build

For a fully standalone executable:

```bash
python scripts/build_scripts/nuitka_build_executable.py
```

### Option 4: Standard Build

For a standard build without extra optimizations:

```bash
python scripts/build_scripts/nuitka_build.py
```

## Build Output

After a successful build, you'll find:

```
dist/
├── daxagent              # Main executable (or daxagent.exe on Windows)
├── daxagent.dist/        # Application files and dependencies
├── .env               # Environment configuration (if copied)
└── templates/         # HTML templates (if included)
```

## Platform-Specific Notes

### macOS

- Excludes Foundation, Cocoa, and AppKit frameworks
- Uses standard console mode
- Optional: Add icon with `--macos-app-icon`

### Windows

- Console mode: `--windows-console-mode=attach`
- Optional: Add icon from `icon.ico` if present
- Generates `.exe` executable

### Linux

- Standard build settings
- Generates native Linux executable

## Included Dependencies

The build includes:

### Application Code
- All modules from `src/` directory
- Templates from `templates/` directory
- Configuration files

### Third-Party Packages
- **Web Framework**: FastAPI, Uvicorn, Starlette
- **Data Validation**: Pydantic
- **Async**: asyncio, nest_asyncio, anyio
- **HTTP/WebSocket**: httpx, httpcore, websockets, h11
- **AI/ML**: Autogen, LangChain
- **Browser**: Playwright, browser_use
- **Security**: cryptography
- **Logging**: loguru
- **Email**: simplegmail
- **APIs**: tavily, together
- **Utilities**: python-dotenv

## Optimizations Applied

### Size Optimizations
- **LTO (Link-Time Optimization)**: ~20% size reduction
- **Strip debug info**: ~15% size reduction
- **Remove docstrings (-OO)**: ~8% size reduction
- **No .pyi files**: ~2% size reduction
- **Exclude unused stdlib**: 20-50MB savings
  - tkinter (~15MB)
  - test (~10MB)
  - setuptools (~8MB)
  - pip (~12MB)
  - unittest (~4MB)
  - distutils (~5MB)

### Speed Optimizations
- **LTO**: ~15% speed improvement
- **Prefer source code**: Better optimization opportunities
- **Multi-core compilation**: Faster build times

### Total Impact
- **Size reduction**: 40-50% smaller
- **Speed improvement**: ~15% faster

## Troubleshooting

### Import Errors

If you get import errors during runtime, ensure all your application modules are included:

```python
"--include-package=src.your_new_module",
```

### Missing Data Files

If templates or other data files are missing:

```python
"--include-data-dir=your_dir=your_dir",
```

### Module Not Found

Add the specific module:

```python
"--include-module=your.module.name",
```

### Build Fails

1. Ensure you're using Python 3.12
2. Install all requirements: `pip install -r requirements.txt`
3. Install Nuitka: `pip install nuitka ordered-set zstandard`
4. Check for conflicting packages
5. Try a clean build: `rm -rf dist/ && python scripts/build.py`

## Running the Built Application

### Development
```bash
python main.py
```

### After Building
```bash
# macOS/Linux
./dist/daxagent

# Windows
dist\daxagent.exe
```

## Environment Variables

Make sure to have a `.env` file in the same directory as the executable with:

```env
PORT=8000
PROJECT_NAME="Omni Backend"
OPENAI_API_KEY=your_key_here
# ... other configuration
```

## Additional Build Options

### Custom Output Name
```python
"--output-filename=custom_name",
```

### Custom Output Directory
```python
"--output-dir=custom_dist",
```

### Add Icon (Windows)
```python
"--windows-icon-from-ico=path/to/icon.ico",
```

### Add Icon (macOS)
```python
"--macos-app-icon=path/to/icon.icns",
```

## Build Time Estimates

- **Full build (first time)**: 10-20 minutes
- **Incremental build**: 2-5 minutes
- **Quick optimized build**: 5-10 minutes

Build times vary based on:
- CPU cores available
- System memory
- Disk speed
- Number of dependencies

## Cleaning Build Artifacts

```bash
# Remove all build outputs
rm -rf dist/ build/

# Remove Python cache
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

## Distribution

The built application can be distributed as:

1. **Single directory**: `dist/daxagent.dist/` with all dependencies
2. **Standalone executable**: `dist/daxagent` (main executable)
3. **Compressed archive**: Zip the entire `dist/` directory

Remember to include:
- The executable
- The `.dist` directory (if using app mode)
- `.env` file (with sensitive keys removed/templated)
- `templates/` directory (if not embedded)
- Any additional runtime resources

## Performance Tuning

For production builds, use [nuitka_optimized.py](../scripts/build_scripts/nuitka_optimized.py) which applies:
- Maximum LTO optimization
- Stripped binaries
- Anti-bloat plugin
- Optimal compilation flags

This results in the smallest and fastest executable.
