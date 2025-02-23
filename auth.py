import os
import sqlite3
import sys
import time
import psutil
from loguru import logger


def get_db_path():
    """ Retrieves the Cursor database path based on the operating system. """

    if sys.platform == "win32":  # Windows
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise EnvironmentError("APPDATA environment variable is not set")
        return os.path.join(appdata, "Cursor", "User", "globalStorage", "state.vscdb")

    elif sys.platform == "darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")

    elif sys.platform == "linux":  # Linux
        return os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")

    else:
        raise NotImplementedError(f"Unsupported operating system: {sys.platform}")


def gracefully_exit_cursor(timeout: int = 5) -> bool:
    """
    Gracefully terminates Cursor processes with a timeout.
    
    Args:
        timeout (int): Time to wait for processes to terminate naturally (seconds)
    Returns:
        bool: True if all processes were terminated successfully
    """
    try:
        logger.info("Starting Cursor process termination...")
        cursor_processes = []
        
        # Collect all Cursor processes
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'].lower() in ['cursor.exe', 'cursor']:
                    cursor_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not cursor_processes:
            logger.info("No running Cursor processes found")
            return True

        # Gracefully request process termination
        for proc in cursor_processes:
            try:
                if proc.is_running():
                    proc.terminate()  # Send termination signal
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Wait for processes to terminate naturally
        start_time = time.time()
        while time.time() - start_time < timeout:
            still_running = []
            for proc in cursor_processes:
                try:
                    if proc.is_running():
                        still_running.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not still_running:
                logger.info("All Cursor processes terminated successfully")
                return True
                
            time.sleep(0.5)  # Small delay between checks
            
        # If processes are still running after timeout
        if still_running := [str(p.pid) for p in still_running]:
            logger.warning(f"The following processes did not terminate within timeout: {', '.join(still_running)}")
            return False
            
        return True

    except Exception as e:
        logger.error(f"Error while terminating Cursor processes: {e}")
        return False


async def update_auth(email: str, access_token: str, refresh_token: str) -> bool:
    """
    Updates Cursor authentication details in the database.

    :param email: New email address
    :param access_token: New access token
    :param refresh_token: New refresh token
    :return: bool - True if the update is successful, False otherwise.
    """
    # First, gracefully terminate any running Cursor instances
    if not gracefully_exit_cursor():
        logger.warning("Could not terminate all Cursor processes gracefully")
        # Continue anyway as we might still be able to update the database

    db_path = get_db_path()

    updates = {
        "cursorAuth/cachedSignUpType": "Auth_0"  # Always update signup type
    }

    # Add provided values to the updates dictionary
    if email is not None:
        updates["cursorAuth/cachedEmail"] = email
    if access_token is not None:
        updates["cursorAuth/accessToken"] = access_token
    if refresh_token is not None:
        updates["cursorAuth/refreshToken"] = refresh_token

    if not updates:
        logger.warning("No values provided for update.")
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            for key, value in updates.items():
                # Check if key exists
                cursor.execute("SELECT COUNT(*) FROM itemTable WHERE key = ?", (key,))
                exists = cursor.fetchone()[0] > 0

                if exists:
                    cursor.execute("UPDATE itemTable SET value = ? WHERE key = ?", (value, key))
                    logger.debug(f"Updated: {key.split('/')[-1]}")
                else:
                    cursor.execute("INSERT INTO itemTable (key, value) VALUES (?, ?)", (key, value))
                    logger.debug(f"Inserted: {key.split('/')[-1]}")

            conn.commit()
            return True

    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

    return False