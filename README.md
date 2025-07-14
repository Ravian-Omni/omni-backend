# Omni Backend

A FastAPI-based backend application that can run both in development mode and as a standalone executable. The application features capabilities for browser automation, email management, file operations, image generation, and Python development assistance.

## Features

- **Multi-mode Operation**: Development server (port 8000) and executable mode (port 8001)
- **Browser Automation**: Web scraping and automation capabilities
- **Email Management**: Send and manage emails
- **File Operations**: File finding and management
- **Image Generation**: AI-powered image creation
- **Python Development**: Code execution and assistance
- **WebSocket Support**: Real-time communication
- **MongoDB Integration**: Database operations
- **Logging**: Comprehensive logging system

## Prerequisites

- Python 3.12+
- MongoDB instance
- Virtual environment (recommended)

## Environment Setup

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd omni-backend
```

### 2. Create Virtual Environment

```bash
python -m venv omniEnv
source omniEnv/bin/activate  # On macOS/Linux
# or
omniEnv\Scripts\activate     # On Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env  # If you have an example file
# or create manually with required variables
```

Required environment variables:
- `MONGODB_URI`: MongoDB connection string
- `PROJECT_NAME`: Name of your project
- Other API keys and configuration as needed

## Development Mode

### Running the Development Server

```bash
# Activate virtual environment
source omniEnv/bin/activate

# Run the development server
python main.py
```

The development server will:
- Run on `http://0.0.0.0:8000`
- Enable hot reload for code changes
- Use the current directory as the working directory

### Development Features

- **Hot Reload**: Automatic restart on code changes
- **Debug Mode**: Enhanced error messages
- **API Documentation**: Available at `/autogen/api/v1/docs`

## Building the Executable

### 1. Build Process

Run the build script:

```bash
python build_executable.py
```

Or use the alternative build script:

```bash
python run_build.py
```

### 2. Build Output

The executable will be created at:
```
dist/omni-backend-app
```

### 3. What Gets Included

The build process includes:
- All Python dependencies
- Configuration files
- Static assets
- Templates
- Capability modules
- Required data files

## Running the Executable

### 1. Execute the Binary

```bash
./dist/omni-backend-app
```

### 2. Executable Features

The executable will:
- Run on `http://0.0.0.0:8001` (or next available port)
- Use the directory containing the binary as working directory
- Create necessary subdirectories (`browser`, `code/output`, `images`, etc.)
- Load `.env` file from the binary's directory if it exists
- Disable hot reload for better performance

### 3. Port Management

If port 8001 is busy, the application will automatically find the next available port in the range 8001-8010.

## Utility Scripts

### Port Management

If you encounter port conflicts, use the port flush script:

```bash
python flush_ports.py
```

This script will:
- Check ports 8000-8020 for usage
- Kill processes occupying these ports
- Provide status feedback
- Attempt aggressive cleanup if needed

### Build Scripts

- `build_executable.py`: Main build script using PyInstaller
- `run_build.py`: Alternative build runner
- `main.spec`: PyInstaller specification file

## Project Structure

```
omni-backend/
├── main.py                 # Main application entry point
├── initialization.py       # Application initialization logic
├── dependencies.py         # Dependency injection and managers
├── build_executable.py     # Executable build script
├── flush_ports.py         # Port management utility
├── main.spec              # PyInstaller configuration
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── capabilities/          # Feature modules
│   ├── browser_manager/
│   ├── email_manager/
│   ├── file_finder/
│   ├── image_generator/
│   └── python_developer/
├── configs/               # Configuration management
├── routers/               # FastAPI route handlers
├── utilities/             # Utility functions
├── templates/             # HTML templates
├── static/                # Static assets
└── dist/                  # Build output (generated)
```

## API Endpoints

### Main Endpoints

- `GET /`: Main application interface
- `GET /autogen/`: Redirect to API documentation
- `GET /autogen/api/v1/docs`: OpenAPI documentation

### WebSocket

- `WS /ws/*`: WebSocket connections for real-time communication

### Chat Management

- `POST /chats/*`: Chat-related operations

## Configuration

### Settings

The application uses `configs/settings.py` for configuration management. Key settings include:

- Database connections
- API configurations
- Logging levels
- Feature toggles

### Logging

Logs are written to:
- Console output
- `logs/app.log` file

Log levels and formats can be configured in the logging utility.

## Development Workflow

### 1. Development Cycle

```bash
# 1. Activate environment
source omniEnv/bin/activate

# 2. Make changes to code
# ... edit files ...

# 3. Test in development mode
python main.py

# 4. Build and test executable
python build_executable.py
./dist/omni-backend-app
```

### 2. Adding New Features

1. Create feature module in `capabilities/`
2. Add route handlers in `routers/`
3. Update dependencies in `dependencies.py`
4. Test in development mode
5. Rebuild executable

### 3. Debugging

- Use development mode for detailed error messages
- Check `logs/app.log` for application logs
- Use port flush script for port conflicts
- Monitor MongoDB connections

## Troubleshooting

### Common Issues

1. **Port Already in Use**
   ```bash
   python flush_ports.py
   ```

2. **Module Import Errors in Executable**
   - Add missing modules to `main.spec` hiddenimports
   - Rebuild executable

3. **MongoDB Connection Issues**
   - Check `.env` file configuration
   - Verify MongoDB is running
   - Check network connectivity

4. **Build Failures**
   - Ensure all dependencies are installed
   - Check for missing data files
   - Review PyInstaller logs

### Performance Tips

- Use executable mode for production
- Development mode for active development
- Monitor resource usage with multiple capabilities
- Optimize MongoDB queries

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Test both development and executable modes
5. Submit a pull request

## License

[Add your license information here]