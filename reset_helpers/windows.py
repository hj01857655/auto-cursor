import os
import sys
import json
import shutil
import random
import uuid
import datetime
import subprocess
import ctypes
from typing import Tuple, Dict, Any

import psutil
try:
    import winreg
except ImportError:
    pass # since it's not available on linux
from loguru import logger


def check_admin() -> bool:
    """
    Checks whether the current process has administrator privileges.
    Returns True if so, otherwise False.
    """
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as e:
        logger.error("Failed to check administrator rights: {}", e)
        return False


# def get_cursor_version():
#     """
#     Attempts to read the Cursor package.json file from two possible locations
#     and returns the version if found.
#     """
#     local_appdata = os.environ.get("LOCALAPPDATA", "")
#     possible_paths = [
#         os.path.join(local_appdata, "Programs", "cursor", "resources", "app", "package.json"),
#         os.path.join(local_appdata, "cursor", "resources", "app", "package.json")
#     ]
#     for path in possible_paths:
#         if os.path.exists(path):
#             try:
#                 with open(path, "r", encoding="utf-8") as f:
#                     package = json.load(f)
#                 version_val = package.get("version")
#                 if version_val:
#                     logger.info("Detected Cursor version: {}", version_val)
#                     return version_val
#             except Exception as e:
#                 logger.error("Error reading {}: {}", path, e)
#     logger.warning("Cursor version not detected.")
#     return None


def close_process(process_name):
    """
    Attempts to kill all processes with the given process name.
    """
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            # Compare process name case-insensitively.
            if proc.info.get("name", "").lower() == process_name.lower():
                logger.info("Killing process {} (PID: {})", process_name, proc.pid)
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error("Failed to kill process {}: {}", process_name, e)


def close_cursor_processes():
    """
    Kills any running processes named "Cursor" or "cursor".
    """
    for name in ["Cursor", "cursor"]:
        close_process(name)


def backup_file(original_file, backup_dir):
    """
    Creates a backup copy of the given file into backup_dir with a timestamp.
    Returns the backup file path on success or None on failure.
    """
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"storage.json.backup_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_filename)
    try:
        shutil.copy2(original_file, backup_path)
        logger.info("Backed up file {} to {}", original_file, backup_path)
        return backup_path
    except Exception as e:
        logger.error("Failed to backup {}: {}", original_file, e)
        return None


def get_random_hex(length):
    """
    Generates a random hexadecimal string representing (length) bytes.
    (Resulting string will be twice as long.)
    """
    return os.urandom(length).hex()


def new_standard_machine_id():
    """
    Generates a standard GUID string using the template:
    "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
    """
    template = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"

    def repl(ch):
        if ch == "x":
            return format(random.randint(0, 15), "x")
        elif ch == "y":
            return format((random.randint(0, 15) & 0x3) | 0x8, "x")
        return ch

    return "".join(repl(ch) if ch in "xy" else ch for ch in template)


def generate_ids() -> Tuple[str, str, str, str]:
    """
    Generates new identifiers:
      - machine_id: A hex string composed of UTF8-encoded prefix "auth0|user_" and 32 random bytes.
      - mac_machine_id: A standard machine GUID.
      - dev_device_id: A new UUID.
      - sqm_id: A new uppercase GUID wrapped in curly brackets.
    Returns a tuple: (machine_id, mac_machine_id, dev_device_id, sqm_id)
    """
    mac_machine_id = new_standard_machine_id()
    dev_device_id = str(uuid.uuid4())
    prefix = "auth0|user_".encode("utf-8").hex()
    random_part = get_random_hex(32)  # 32 random bytes -> 64 hex characters.
    machine_id = prefix + random_part
    sqm_id = "{" + str(uuid.uuid4()).upper() + "}"
    return machine_id, mac_machine_id, dev_device_id, sqm_id


def backup_registry(backup_file):
    """
    Uses reg.exe to export the "SOFTWARE\\Microsoft\\Cryptography" key to a .reg file.
    """
    try:
        cmd = ["reg", "export", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography", backup_file, "/y"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Registry backed up to {}", backup_file)
        else:
            logger.warning("Registry backup failed: {}", result.stderr)
        return result.returncode == 0
    except Exception as e:
        logger.error("Registry backup exception: {}", e)
        return False


def update_machine_guid():
    """
    Updates the MachineGuid registry value under "SOFTWARE\\Microsoft\\Cryptography"
    to a new GUID.
    A registry backup is attempted first.
    """
    registry_path = r"SOFTWARE\Microsoft\Cryptography"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            original_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            logger.info("Current MachineGuid: {}", original_guid)
            # Create a backup file path under APPDATA (as in the original script)
            appdata = os.environ.get("APPDATA", "")
            backup_dir = os.path.join(appdata, "Cursor", "User", "globalStorage", "backups")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            backup_file_path = os.path.join(backup_dir, f"MachineGuid_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.reg")
            backup_registry(backup_file_path)
            # Generate new GUID and update registry
            new_guid = str(uuid.uuid4())
            winreg.SetValueEx(key, "MachineGuid", 0, winreg.REG_SZ, new_guid)
        # Verification step: re-open the key and confirm the new value.
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_READ) as key_read:
            verify_guid, _ = winreg.QueryValueEx(key_read, "MachineGuid")
        if verify_guid == new_guid:
            logger.info("Registry updated successfully. New MachineGuid: {}", new_guid)
            return True
        else:
            raise Exception(f"Verification failed: expected {new_guid}, got {verify_guid}")
    except Exception as e:
        logger.error("Failed to update MachineGuid: {}", e)
        return False


def update_config(storage_file: str, machine_id: str, mac_machine_id: str, 
                 dev_device_id: str, sqm_id: str) -> bool:
    """
    Updates the configuration file (in JSON) at storage_file.
    It backs up the file first then updates the telemetry key values.
    """
    try:
        with open(storage_file, "r", encoding="utf-8") as f:
            config: Dict[str, Any] = json.load(f)
    except Exception as e:
        logger.error("Failed to load configuration file {}: {}", storage_file, e)
        return False

    appdata = os.environ.get("APPDATA", "")
    backup_dir = os.path.join(appdata, "Cursor", "User", "globalStorage", "backups")
    backup_file(storage_file, backup_dir)

    try:
        # Update the JSON keys. The keys are assumed to be:
        # "telemetry.machineId", "telemetry.macMachineId", etc.
        # If they already exist, they will be overwritten.
        config["telemetry.machineId"] = machine_id
        config["telemetry.macMachineId"] = mac_machine_id
        config["telemetry.devDeviceId"] = dev_device_id
        config["telemetry.sqmId"] = sqm_id
    except Exception as e:
        logger.error("Failed to update configuration data: {}", e)
        return False

    try:
        # Write out the updated configuration using UTF-8 encoding (without BOM)
        with open(storage_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info("Configuration updated successfully in {}", storage_file)
        return True
    except Exception as e:
        logger.error("Failed to write configuration file {}: {}", storage_file, e)
        return False


def request_admin_elevation():
    """
    Attempts to restart the current Python process with admin privileges.
    Returns True if elevation was successful or already running as admin.
    """
    if check_admin():
        return True
        
    logger.info("Requesting administrator privileges...")
    try:
        if getattr(sys, 'frozen', False):
            # If running as a frozen executable
            script = sys.executable
            args = sys.argv[1:]
        else:
            # If running as a Python script
            script = sys.executable
            args = [sys.argv[0]] + sys.argv[1:]
            
        shell32 = ctypes.windll.shell32
        ret = shell32.ShellExecuteW(None, "runas", script, f'"{" ".join(args)}"', None, 1)
        if ret <= 32:  # ShellExecute returns a value <= 32 on error
            logger.error("Failed to elevate privileges. Error code: {}", ret)
            return False
        return True
    except Exception as e:
        logger.error("Failed to request administrator privileges: {}", e)
        return False


def reset_machine_ids_windows():
    """
    Main function:
      - Closes running Cursor processes.
      - Updates the configuration file with new device IDs.
      - Updates the registry for MachineGuid.
    Returns:
      - True if successful, False if operation failed
    """
    # Kill running Cursor processes.
    close_cursor_processes()

    # Determine configuration file paths.
    appdata = os.environ.get("APPDATA", "")
    storage_file = os.path.join(appdata, "Cursor", "User", "globalStorage", "storage.json")

    if not os.path.exists(storage_file):
        logger.error("Configuration file not found: {}", storage_file)
        return False

    # Generate new IDs.
    machine_id, mac_machine_id, dev_device_id, sqm_id = generate_ids()

    # Update the configuration file.
    if not update_config(storage_file, machine_id, mac_machine_id, dev_device_id, sqm_id):
        logger.error("Failed to update configuration file.")
        return False

    # Update registry MachineGuid.
    if not update_machine_guid():
        logger.error("Failed to update machine GUID.")
        return False

    logger.info("All tasks completed successfully.")
    return True


if __name__ == '__main__':
    success = reset_machine_ids_windows()
    sys.exit(0 if success else 1)