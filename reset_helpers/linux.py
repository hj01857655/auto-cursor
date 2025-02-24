import os
import sys
import json
import shutil
import uuid
import subprocess
import datetime
from loguru import logger

def run_command_as_sudo(cmd):
    """
    Runs the given command list. If the effective UID is not 0, prepends "sudo" to the command.
    Returns a CompletedProcess instance.
    """
    if os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    return subprocess.run(cmd, check=True)


def get_current_user():
    """
    Returns the invoking (non-root) user.
    If run as root and SUDO_USER is set, returns SUDO_USER.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user:
        return sudo_user
    return os.environ.get("USER", "unknown")



def backup_system_id(backup_dir):
    """
    Backs up the system machine-id and (if available) the DMI system UUID.
    Creates a backup file under backup_dir (with a timestamp in its name).
    """
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(
        backup_dir, f"system_id.backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    try:
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write(f"# Original System ID Backup - {datetime.datetime.now()}\n")
            f.write("## Machine ID:\n")
            if os.path.exists("/etc/machine-id"):
                with open("/etc/machine-id", "r", encoding="utf-8") as mid:
                    f.write(mid.read().strip() + "\n")
            else:
                f.write("N/A\n")
            f.write("\n## DMI System UUID:\n")
            try:
                result = run_command_as_sudo(["dmidecode", "-s", "system-uuid"])
                uuid_value = result.stdout.decode().strip() if result.stdout else ""
                f.write(uuid_value + "\n")
            except Exception:
                f.write("N/A\n")
        run_command_as_sudo(["chmod", "444", backup_file])
        logger.info("System ID has been backed up to: {}", backup_file)
    except Exception as e:
        logger.error("Failed to backup system ID: {}", e)
        return False
    return True


def backup_config(storage_file, backup_dir, current_user):
    """
    Backs up the configuration file to the backup directory.
    Uses sudo for setting ownership and permission if needed.
    """
    if not os.path.exists(storage_file):
        logger.warning("Configuration file not found: {}. Skipping backup.", storage_file)
        return True

    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(
        backup_dir, f"storage.json.backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        shutil.copy2(storage_file, backup_file)
        if os.geteuid() == 0:
            os.chmod(backup_file, 0o644)
            shutil.chown(backup_file, user=current_user)
        else:
            run_command_as_sudo(["chmod", "644", backup_file])
            run_command_as_sudo(["chown", current_user, backup_file])
        logger.info("Configuration file backed up to: {}", backup_file)
        return True
    except Exception as e:
        logger.error("Configuration backup failed: {}", e)
        return False



def generate_random_id(num_bytes=32):
    """
    Generates a random hexadecimal string from num_bytes.
    (Default 32 bytes yields 64 hex characters.)
    """
    return os.urandom(num_bytes).hex()


def generate_uuid():
    """
    Returns a new UUID (in lowercase).
    """
    return str(uuid.uuid4()).lower()


def update_machine_id_file(new_machine_id):
    """
    Backs up and overwrites /etc/machine-id with new_machine_id.
    Uses sudo if not running as root.
    """
    mid_path = "/etc/machine-id"
    if os.path.exists(mid_path):
        backup_path = mid_path + ".backup"
        try:
            # If running as root, do it directly; else, use sudo commands.
            if os.geteuid() == 0:
                shutil.copy2(mid_path, backup_path)
                with open(mid_path, "w", encoding="utf-8") as f:
                    f.write(new_machine_id + "\n")
                logger.info("/etc/machine-id updated successfully (backup at {}).", backup_path)
            else:
                run_command_as_sudo(["cp", mid_path, backup_path])
                # Use tee to write new_machine_id as root
                run_command_as_sudo(["bash", "-c", f"echo '{new_machine_id}' | tee {mid_path}"])
                logger.info("/etc/machine-id updated successfully using sudo (backup at {}).", backup_path)
        except Exception as e:
            logger.error("Failed to update /etc/machine-id: {}", e)
            return False
    else:
        logger.warning("/etc/machine-id not found; skipping system id update.")
    return True



def update_config(storage_file, telemetry_data):
    """
    Loads the JSON configuration file, updates (or adds) telemetry keys
    with new values, and writes the updated JSON back.
    Sets the file to read-only.
    """
    try:
        with open(storage_file, "r", encoding="utf-8") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}
    except Exception as e:
        logger.error("Failed to load configuration file {}: {}", storage_file, e)
        return False

    config["telemetry.machineId"]   = telemetry_data["machineId"]
    config["telemetry.macMachineId"] = telemetry_data["macMachineId"]
    config["telemetry.devDeviceId"]  = telemetry_data["devDeviceId"]
    config["telemetry.sqmId"]        = telemetry_data["sqmId"]

    try:
        with open(storage_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        # Set file to read-only. Use sudo if needed.
        if os.geteuid() == 0:
            os.chmod(storage_file, 0o444)
        else:
            run_command_as_sudo(["chmod", "444", storage_file])
        logger.info("Configuration file updated: {}", storage_file)
        return True
    except Exception as e:
        logger.error("Failed to write configuration file {}: {}", storage_file, e)
        return False


def generate_new_config(storage_file, backup_dir, current_user):
    """
    Performs the following steps:
      – Backs up the current system ID.
      – Generates a new random machine id (using only the first 32 hex characters).
      – Updates /etc/machine-id.
      – Generates new telemetry IDs: machineId (a prefix plus random hex),
         macMachineId (random hex), devDeviceId (UUID in lowercase),
         and sqmId (UUID in uppercase enclosed in braces).
      – Backs up and updates the configuration file.
      
    Returns the telemetry data dictionary on success, or None on failure.
    """
    logger.info("Modifying system ID...")

    if not backup_system_id(backup_dir):
        logger.error("System ID backup failed.")
        return None

    # Generate new machine-id for /etc/machine-id (use first 32 hex characters)
    new_machine_id = generate_random_id(16)  # 16 bytes => 32 hex chars
    if not update_machine_id_file(new_machine_id):
        logger.error("System machine-id update failed.")
        return None

    # Generate telemetry IDs
    prefix_hex = "auth0|user_".encode("utf-8").hex()
    random_part = generate_random_id(32)  # 32 bytes = 64 hex characters
    telemetry_machine_id = prefix_hex + random_part

    telemetry_mac_machine_id = generate_random_id()  # 32 bytes => 64 hex characters
    telemetry_dev_device_id = generate_uuid()
    telemetry_sqm_id = "{" + str(uuid.uuid4()).upper() + "}"

    telemetry_data = {
        "machineId": telemetry_machine_id,
        "macMachineId": telemetry_mac_machine_id,
        "devDeviceId": telemetry_dev_device_id,
        "sqmId": telemetry_sqm_id,
    }

    logger.info("Updating configuration file...")
    if not os.path.exists(storage_file):
        logger.error("Configuration file not found: {}", storage_file)
        logger.warning("Please ensure Cursor has been installed and run at least once before using this tool.")
        return None

    os.makedirs(os.path.dirname(storage_file), exist_ok=True)
    if not backup_config(storage_file, backup_dir, current_user):
        logger.error("Configuration backup failed.")
        return None

    if not update_config(storage_file, telemetry_data):
        logger.error("Configuration file update failed.")
        return None

    logger.debug("Updated telemetry data:")
    logger.debug("machineId: {}", telemetry_data["machineId"])
    logger.debug("macMachineId: {}", telemetry_data["macMachineId"])
    logger.debug("devDeviceId: {}", telemetry_data["devDeviceId"])
    logger.debug("sqmId: {}", telemetry_data["sqmId"])
    return telemetry_data


# -------------------------
# Main function for resetting IDs
# -------------------------

def reset_machine_ids_linux():
    """
    This function checks permissions, performs backups,
    generates and updates new system and telemetry IDs,
    and displays a basic file tree. It is the main function
    to reset machine IDs on Linux.
    """
    current_user = get_current_user()
    # Define important paths (using XDG_CONFIG_HOME if set, otherwise $HOME/.config)
    home = os.path.expanduser("~")
    config_base = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    storage_file = os.path.join(config_base, "Cursor", "User", "globalStorage", "storage.json")
    backup_dir = os.path.join(config_base, "Cursor", "User", "globalStorage", "backups")

    telemetry_data = generate_new_config(storage_file, backup_dir, current_user)
    
    logger.warning("==================================================")
    logger.warning("This will reset your machine ID and telemetry IDs.")
    logger.warning("For that we need sudo access.")
    logger.warning("Please enter your password below.")
    logger.warning("==================================================")

    if telemetry_data is None:
        logger.error("New configuration generation failed.")
        return False

    logger.info("Reset machine IDs successfully.")
    return True
