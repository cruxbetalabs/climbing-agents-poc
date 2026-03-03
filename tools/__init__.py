from tools.db_tools import init_db_tools
from tools.profile_tools import init_profile_tools
from tools.registry import registry

# Import web_tools to trigger @registry.register decorators
import tools.web_tools  # noqa: F401


def init_all_tools(db_path: str) -> None:
    init_db_tools(db_path)
    init_profile_tools(db_path)
