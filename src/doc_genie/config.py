"""Configuration management for Doc Genie."""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional
import toml
from loguru import logger

CONFIG_DIR = Path.home() / ".doc_genie"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Credentials:
    """Platform credentials."""
    notion_token: str
    quip_token: str = ""
    quip_base_url: str = "https://quip-amazon.com"


@dataclass
class Route:
    """Named sync route configuration."""
    name: str
    description: str
    source: str  # Path as string
    notion_database: str
    quip_folder: str = ""
    enabled: bool = True

    @property
    def source_path(self) -> Path:
        """Get source path as Path object."""
        return Path(self.source).expanduser()

    def is_directory(self) -> bool:
        """Check if source is a directory."""
        return self.source_path.is_dir()


class Config:
    """Manage user configuration in ~/.doc_genie/config.toml."""

    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / "config.toml"
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Ensure config directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Config directory: {}", self.config_dir)

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_file.exists()

    def load(self) -> dict:
        """Load configuration from file."""
        if not self.exists():
            logger.debug("Config file does not exist, returning empty config")
            return {}

        try:
            config_data = toml.load(self.config_file)
            logger.debug("Loaded config from {}", self.config_file)
            return config_data
        except Exception as e:
            logger.error("Failed to load config: {}", e)
            return {}

    def save(self, config_data: dict):
        """Save configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                toml.dump(config_data, f)
            logger.debug("Saved config to {}", self.config_file)
        except Exception as e:
            logger.error("Failed to save config: {}", e)
            raise

    def get_credentials(self) -> Credentials:
        """Get platform credentials."""
        data = self.load()
        creds = data.get('credentials', {})
        return Credentials(
            notion_token=creds.get('notion', {}).get('api_token', ''),
            quip_token=creds.get('quip', {}).get('api_token', ''),
            quip_base_url=creds.get('quip', {}).get('base_url', 'https://quip-amazon.com')
        )

    def save_credentials(self, notion_token: str, quip_token: str = "", quip_base_url: str = "https://quip-amazon.com"):
        """Save platform credentials."""
        data = self.load()
        data['credentials'] = {
            'notion': {'api_token': notion_token},
            'quip': {
                'api_token': quip_token,
                'base_url': quip_base_url
            }
        }
        self.save(data)
        logger.info("Credentials saved")

    def get_route(self, route_name: str) -> Optional[Route]:
        """Get a specific route by name."""
        data = self.load()
        routes = data.get('routes', {})
        route_data = routes.get(route_name)
        if not route_data:
            logger.warning("Route not found: {}", route_name)
            return None
        return Route(**route_data)

    def list_routes(self) -> List[Route]:
        """List all configured routes."""
        data = self.load()
        routes = data.get('routes', {})
        return [Route(**route_data) for route_data in routes.values()]

    def add_route(self, route: Route):
        """Add or update a route."""
        data = self.load()
        if 'routes' not in data:
            data['routes'] = {}
        data['routes'][route.name] = asdict(route)
        self.save(data)
        logger.info("Route added: {}", route.name)

    def get_default_route(self) -> Optional[str]:
        """Get the default route name."""
        data = self.load()
        return data.get('default_route')

    def set_default_route(self, route_name: str):
        """Set the default route."""
        # Verify route exists
        if not self.get_route(route_name):
            raise ValueError(f"Route not found: {route_name}")

        data = self.load()
        data['default_route'] = route_name
        self.save(data)
        logger.info("Default route set to: {}", route_name)

    def remove_route(self, route_name: str):
        """Remove a route."""
        data = self.load()
        if 'routes' in data and route_name in data['routes']:
            del data['routes'][route_name]
            # Clear default if it was the default route
            if data.get('default_route') == route_name:
                data.pop('default_route', None)
            self.save(data)
            logger.info("Route removed: {}", route_name)
        else:
            logger.warning("Route not found for removal: {}", route_name)
