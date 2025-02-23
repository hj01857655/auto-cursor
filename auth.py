import os
import sqlite3
import sys

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


async def update_auth(email: str, access_token: str, refresh_token: str) -> bool:
    """
    Updates Cursor authentication details in the database.

    :param email: New email address
    :param access_token: New access token
    :param refresh_token: New refresh token
    :return: bool - True if the update is successful, False otherwise.
    """

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
        print("No values provided for update.")
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