# Python Code Executor with Virtual Environment Isolation

This document explains the updated Python code execution system that provides virtual environment isolation for each project.

## Overview

The previous implementation used the old `UserProxyAgent` with basic code execution configuration. The new implementation uses the modern `LocalCommandLineCodeExecutor` from AutoGen with virtual environment isolation.

## Key Improvements

### 1. Virtual Environment Isolation

- Each new chat/project gets its own Python virtual environment
- Prevents package conflicts between different projects
- Isolates dependencies for each project

### 2. Base Virtual Environment Bundling

- A base virtual environment with common packages is created during build
- This base environment is copied for each new project to save time
- Common packages include: requests, beautifulsoup4, pandas, numpy, etc.

### 3. Modern AutoGen Code Executor

- Uses `LocalCommandLineCodeExecutor` instead of deprecated `UserProxyAgent`
- Better error handling and output capture
- More reliable code execution

## File Structure

```
utilities/
├── venv_manager.py          # Manages virtual environments
capabilities/python_developer/
├── manager.py               # Updated to use new code executor
build/
├── base_venv/              # Base virtual environment (created during build)
create_base_venv.py         # Script to create base virtual environment
test_code_executor.py       # Test script for new implementation
```

## How It Works

### Development Mode (uvicorn)

1. Each new chat creates a fresh virtual environment in `{chat_dir}/.venv`
2. Basic packages are installed in this environment
3. Code execution happens within this isolated environment

### Production Mode (executable)

1. A base virtual environment is bundled with the executable
2. For each new chat, the base environment is copied to `{chat_dir}/.venv`
3. This provides faster project setup while maintaining isolation

## Building the Executable

The build process now includes creating a base virtual environment:

```bash
python build_executable.py
```

This will:

1. Create a base virtual environment with common packages
2. Bundle it with the executable via PyInstaller
3. Create the final executable with all dependencies

## Testing

Run the test script to verify the new implementation:

```bash
python test_code_executor.py
```

This will test:

- Virtual environment creation
- Code execution in isolated environment
- Package installation and import

## Benefits

1. **Isolation**: Each project has its own Python environment
2. **Reliability**: No conflicts between project dependencies
3. **Performance**: Base environment copying is faster than fresh installs
4. **Portability**: Works in both development and production modes
5. **Modern**: Uses latest AutoGen features instead of deprecated APIs

## Migration Notes

The changes are backward compatible. Existing functionality remains the same, but now with better isolation and reliability.

### Key Changes in `manager.py`:

- Import `LocalCommandLineCodeExecutor` and `VenvManager`
- Create virtual environment in `__init__`
- Updated `get_code_executor()` to use `ConversableAgent` with new executor
- Added `install_packages()` and `get_venv_info()` methods

### New Files:

- `utilities/venv_manager.py`: Handles virtual environment management
- `create_base_venv.py`: Creates base environment for bundling
- `test_code_executor.py`: Test script for validation
