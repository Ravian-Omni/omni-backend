# api/initialization.py
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel

from configs.settings import Settings


class _AppPaths(BaseModel):
    """Internal model representing all application paths"""

    app_root: Path
    browser_root: Path
    browser_gif: Path
    python_coder_root: Path
    image_gen_root: Path
    # config_dir: Path
    # database_uri: str


class AppInitializer:
    """Handles application initialization including paths and environment setup"""

    def __init__(self, settings: Settings, app_path: str):
        """
        Initialize the application structure.

        Args:
            settings (Settings): Application settings
            app_path (str): Path to the application code directory
        """
        self.settings = settings
        self._app_path = Path(app_path)
        self._paths = self._init_paths()
        self._create_directories()
        self._load_environment()
        logger.info(f"Initializing application data folder: {self.app_root} ")

    def _get_app_root(self) -> Path:
        """Determine application root directory"""
        if app_dir := os.getenv("_APPDIR"):
            return Path(app_dir)
        return Path.home() / ".ravian_ai"

    # def _get_database_uri(self, app_root: Path) -> str:
    #     """Generate database URI based on settings or environment"""
    #     if db_uri := os.getenv("DATABASE_URI"):
    #         return db_uri
    #     return self.settings.DATABASE_URI.replace("./", str(app_root) + "/")

    def _init_paths(self) -> _AppPaths:
        """Initialize and return AppPaths instance"""
        # app_root = self._get_app_root()
        app_root = self._app_path
        return _AppPaths(
            app_root=app_root,
            browser_root=app_root / "browser",
            browser_gif=app_root / "browser" / "gif",
            python_coder_root=app_root / "code" / "output",
            image_gen_root=self._app_path / "images",
            # config_dir=app_root / self.settings.CONFIG_DIR,
            # database_uri=self._get_database_uri(app_root),
        )

    def _create_directories(self) -> None:
        """Create all required directories"""
        self.app_root.mkdir(parents=True, exist_ok=True)
        dirs = [self.browser_root, self.browser_gif, self.python_coder_root, self.image_gen_root]
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)

    def _load_environment(self) -> None:
        """Load environment variables from .env file if it exists"""
        env_file = self.app_root / ".env"
        if env_file.exists():
            # logger.info(f"Loading environment variables from {env_file}")
            load_dotenv(str(env_file))

    # Properties for accessing paths
    @property
    def app_root(self) -> Path:
        """Root directory for the application"""
        return self._paths.app_root

    @property
    def browser_root(self) -> Path:
        """Directory for static files"""
        return self._paths.browser_root
    
    @property
    def browser_gif(self) -> Path:
        """Directory for static files"""
        return self._paths.browser_gif

    @property
    def python_coder_root(self) -> Path:
        """Directory for user files"""
        return self._paths.python_coder_root

    @property
    def image_gen_root(self) -> Path:
        """Directory for UI files"""
        return self._paths.image_gen_root

    # @property
    # def config_dir(self) -> Path:
    #     """Directory for configuration files"""
    #     return self._paths.config_dir

    # @property
    # def database_uri(self) -> str:
    #     """Database connection URI"""
    #     return self._paths.database_uri
