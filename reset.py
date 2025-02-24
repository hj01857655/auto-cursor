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
    os_type = platform.system()

    paths = {
        "Darwin": "/Applications/Cursor.app/Contents/Resources/app",
        "Windows": os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Cursor", "resources", "app"),
        "Linux": ["/opt/Cursor/resources/app", "/usr/share/cursor/resources/app"]
    }

    if os_type not in paths:
        raise OSError(f"Unsupported OS: {os_type}")

    if os_type == "Linux":
        for base_path in paths["Linux"]:
            if os.path.exists(os.path.join(base_path, "package.json")):
                return os.path.join(base_path, "package.json"), os.path.join(base_path, "out/main.js")
    
    return "", ""


# ---------------------- Version Checking ----------------------

def read_version(pkg_path: str) -> str:
    """Reads and returns the Cursor version from `package.json`."""
    try:
        with open(pkg_path, encoding="utf-8") as f:
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

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file, open(main_path, "r", encoding="utf-8") as main_file:
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
    system = platform.system()
    logger.info(f"Detected OS: {system}")
    
    if system == "Windows":
        success = reset_machine_ids_windows()
        if not success:
            logger.error("Windows machine ID reset failed")
            return False
        return True

    if system == "Linux":
        success = reset_machine_ids_linux()
        if not success:
            logger.error("Linux machine ID reset failed")
            return False
        return True

    base_url = "https://aizaozao.com/accelerate.php/https://raw.githubusercontent.com/yuaotian/go-cursor-help/refs/heads/master/scripts/run"

    commands = {
        "Darwin": f"curl -fsSL {base_url}/cursor_mac_id_modifier.sh | sudo bash",
        "Linux": f"curl -fsSL {base_url}/cursor_linux_id_modifier.sh | sudo bash",
        "Windows": [
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile",
            "-Command", f"Start-Process powershell -Verb RunAs -ArgumentList \"irm {base_url}/cursor_win_id_modifier.ps1 | iex\""
        ]
    }

    if system not in commands:
        logger.error(f"Unsupported Operating System: {system}")
        return False

    logger.info(f"Executing reset script for {system}...")

    try:
        process = subprocess.Popen(
            commands[system],
            shell=(system != "Windows"),  # Use `shell=True` only for Unix-based OS
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",  # Force UTF-8 Encoding
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
            logger.info(f"Successfully executed reset script on {system}.")
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
            logger.warning("Failed to determine version, assuming it's at least 0.45.0.")
            version = "0.45.0"

        logger.info(f"Detected Cursor version: {version}")

        if is_version_valid(version, min_version="0.45.0"):
            logger.info("Using newer script-based method.")
            return run_reset_script()
        else:
            logger.info("Using legacy file modification method.")
            return modify_js_file(main_path)

    except Exception as e:
        logger.error(f"Unexpected Error: {e}")
        return False