import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Tuple

from loguru import logger

from reset_helpers.linux import reset_machine_ids_linux
from reset_helpers.windows import reset_machine_ids_windows

# ---------------------- Constants ----------------------
MIN_VERSION = "0.45.0"
DEFAULT_ENCODING = "utf-8"
SCRIPT_BASE_URL = "https://aizaozao.com/accelerate.php/https://raw.githubusercontent.com/yuaotian/go-cursor-help/refs/heads/master/scripts/run"

# 缓存平台信息，避免重复调用
CURRENT_PLATFORM = platform.system()
# ---------------------- Cursor Paths ----------------------

def get_db_path() -> str:
    """Retrieves the Cursor database path based on the operating system."""
    os_paths = {
        "win32": os.path.join(os.getenv("APPDATA", ""), "Cursor", "User", "globalStorage", "state.vscdb"),
        "darwin": os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"),
        "linux": os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb"),
    }
    return os_paths.get(sys.platform, None) or (lambda: (_ for _ in ()).throw(
        NotImplementedError(f"Unsupported OS: {sys.platform}")))()


def get_cursor_paths() -> Tuple[str, str]:
    """Get Cursor installation paths based on the OS."""
    paths = {
        "Darwin": "/Applications/Cursor.app/Contents/Resources/app",
        "Windows": os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Cursor", "resources", "app"),
        "Linux": ["/opt/Cursor/resources/app", "/usr/share/cursor/resources/app"]
    }

    if CURRENT_PLATFORM not in paths:
        raise OSError(f"Unsupported OS: {CURRENT_PLATFORM}")

    if CURRENT_PLATFORM == "Linux":
        for base_path in paths["Linux"]:
            if os.path.exists(os.path.join(base_path, "package.json")):
                return os.path.join(base_path, "package.json"), os.path.join(base_path, "out/main.js")

    return "", ""


# ---------------------- Version Checking ----------------------

def read_version(pkg_path: str) -> str:
    """Reads and returns the Cursor version from `package.json`."""
    try:
        with open(pkg_path, encoding=DEFAULT_ENCODING) as f:
            return json.load(f)["version"]
    except Exception as e:
        logger.warning(f"Failed to read version: {e}")
        return ""


def is_version_valid(version: str, min_version: str = "", max_version: str = "") -> bool:
    """Validates version format and range."""
    version_pattern = r"^\d+\.\d+\.\d+$"
    if not re.match(version_pattern, version):
        logger.error(f"Invalid version format: {version}")
        return False

    def parse_version(ver):
        return tuple(map(int, ver.split(".")))

    current_version = parse_version(version)

    if min_version and current_version < parse_version(min_version):
        logger.error(f"Version {version} is below the minimum required {min_version}")
        return False

    if max_version and current_version > parse_version(max_version):
        logger.error(f"Version {version} exceeds the maximum allowed {max_version}")
        return False

    return True


# ---------------------- Older Version (File Modification) ----------------------

def modify_js_file(main_path: str) -> bool:
    """Modifies `main.js` to patch machine ID functions."""
    try:
        original_stat = os.stat(main_path)
        tmp_path = None

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file, open(main_path, "r", encoding=DEFAULT_ENCODING) as main_file:
            content = main_file.read()

            patterns = {
                r"async getMachineId\(\)\{return [^??]+\?\?([^}]+)\}": r"async getMachineId(){return \1}",
                r"async getMacMachineId\(\)\{return [^??]+\?\?([^}]+)\}": r"async getMacMachineId(){return \1}",
            }

            for pattern, replacement in patterns.items():
                content = re.sub(pattern, replacement, content)

            tmp_file.write(content)
            tmp_path = tmp_file.name

        shutil.copy2(main_path, f"{main_path}.old")  # Backup
        shutil.move(tmp_path, main_path)

        os.chmod(main_path, original_stat.st_mode)
        if os.name != "nt":
            os.chown(main_path, original_stat.st_uid, original_stat.st_gid)

        logger.info("Modification successful.")
        return True

    except Exception as e:
        logger.error(f"Error modifying main.js: {e}")
        if tmp_path:
            os.unlink(tmp_path)
        return False


# ---------------------- Newer Version (Script Execution) ----------------------

def run_reset_script() -> bool:
    """Runs the appropriate reset script based on the operating system with real-time output streaming and UTF-8 encoding."""
    logger.info(f"Detected OS: {CURRENT_PLATFORM}")

    if CURRENT_PLATFORM == "Windows":
        success = reset_machine_ids_windows()
        if not success:
            logger.error("Windows machine ID reset failed")
            return False
        return True

    if CURRENT_PLATFORM == "Linux":
        success = reset_machine_ids_linux()
        if not success:
            logger.error("Linux machine ID reset failed")
            return False
        return True

    commands = {
        "Darwin": f"curl -fsSL {SCRIPT_BASE_URL}/cursor_mac_id_modifier.sh | sudo bash",
        "Linux": f"curl -fsSL {SCRIPT_BASE_URL}/cursor_linux_id_modifier.sh | sudo bash",
        "Windows": [
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile",
            "-Command", f"Start-Process powershell -Verb RunAs -ArgumentList \"irm {SCRIPT_BASE_URL}/cursor_win_id_modifier.ps1 | iex\""
        ]
    }

    if CURRENT_PLATFORM not in commands:
        logger.error(f"Unsupported Operating System: {CURRENT_PLATFORM}")
        return False

    logger.info(f"Executing reset script for {CURRENT_PLATFORM}...")

    try:
        process = subprocess.Popen(
            commands[CURRENT_PLATFORM],
            shell=(CURRENT_PLATFORM != "Windows"),  # Use `shell=True` only for Unix-based OS
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=DEFAULT_ENCODING,  # Force UTF-8 Encoding
            errors="replace"  # Replace unsupported characters instead of crashing
        )

        # Stream output
        if process.stdout:
            for line in process.stdout:
                logger.info(f"OUTPUT: {line.strip()}")
        if process.stderr:
            for line in process.stderr:
                logger.error(f"ERROR: {line.strip()}")

        process.wait()

        if process.returncode == 0:
            logger.info(f"Successfully executed reset script on {CURRENT_PLATFORM}.")
            return True
        else:
            logger.error(f"Reset script failed with exit code {process.returncode}.")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")

    return False

# ---------------------- Main Execution ----------------------

def reset_machine_ids() -> bool:
    """
    Determines Cursor version and executes the appropriate reset method.
    Returns:
        bool: True if reset was successful, False otherwise.
    """
    logger.info("Starting Cursor machine ID reset process...")

    try:
        pkg_path, main_path = get_cursor_paths()
        version = read_version(pkg_path)

        if not version:
            logger.warning(f"Failed to determine version, assuming it's at least {MIN_VERSION}.")
            version = MIN_VERSION

        logger.info(f"Detected Cursor version: {version}")

        if is_version_valid(version, min_version=MIN_VERSION):
            logger.info("Using newer script-based method.")
            return run_reset_script()
        else:
            logger.info("Using legacy file modification method.")
            return modify_js_file(main_path)

    except Exception as e:
        logger.error(f"Unexpected Error: {e}")
        return False