import asyncio
import os
import random
import re
import socket
import string
import sys
import ctypes
from typing import Optional

import zendriver as zd
from dotenv import load_dotenv
from loguru import logger
from zendriver.core.browser import Browser

from auth import update_auth
from mail import fetch_email
from reset import reset_machine_ids
from reset_helpers.windows import check_admin
from temp_mail import get_new_email, get_tempmail_confirmation_code

if os.path.exists(".env"):
    load_dotenv()
else:
    logger.error("No .env file found")
    logger.info("Create one using .env.example")
    exit(1)

login_url = "https://authenticator.cursor.sh"
sign_up_url = "https://authenticator.cursor.sh/sign-up"

def request_admin_elevation():
    """Request admin privileges if not already running as admin."""
    if os.name == 'nt':  # Windows
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
            return False
        except Exception as e:
            logger.error("Failed to request administrator privileges: {}", e)
            return False
    else:  # Unix-like systems
        return True


async def sign_up(browser: Browser, email: str, token: Optional[str] = None) -> Optional[str]:
    """
    Registers a new Cursor account.
    Requires user interaction.

    Returns:
    The session token on success or None on failure.
    """

    tab = await browser.get(sign_up_url)

    first_name = random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=5))
    last_name = random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=5))
    password = ''.join(random.choices(string.ascii_uppercase + string.digits + string.punctuation, k=12))

    logger.debug(f"First name: {first_name} | Last name: {last_name} | Password: {password} | Email: {email}")

    await tab

    await tab.wait(1)

    logger.info("Inputting fields...")
    first_name_box = await tab.select("input[name='first_name']")
    await first_name_box.send_keys(first_name)

    last_name_box = await tab.select("input[name='last_name']")
    await last_name_box.send_keys(last_name)

    email_box = await tab.select("input[name='email']")
    await email_box.send_keys(email)

    await asyncio.sleep(1)

    logger.info("Submitting...")
    submit_button = await tab.select("button[type='submit']")
    await submit_button.click()

    password_box = None
    logger.warning("Please tick the turnstile checkbox...")
    while not password_box:
        try:
            password_box = await tab.select("input[name='password']", timeout=1)
        except Exception:
            pass

    logger.info("Entering the password...")
    await password_box.send_keys(password)

    logger.info("Submitting...")
    submit_button = await tab.select("button[type='submit']")
    await submit_button.click()

    code_input_box = None
    logger.warning("Please tick the turnstile checkbox...")
    while not code_input_box:
        try:
            code_input_box = await tab.select("input[name='code']", timeout=1)
        except Exception:
            pass

    if not os.getenv("USE_TEMPMAIL", "false").lower() == "true":
        email_content = await fetch_email(
            os.getenv("IMAP_SERVER", ""),
            int(os.getenv("IMAP_PORT", "0")),
            os.getenv("IMAP_USER", ""),
            os.getenv("IMAP_PASS", ""),
        )
        
        if email_content is None:
            logger.error("Failed to fetch email")
            return None

        code_search = re.search(r'\b\d{6}\b', email_content)
        if not code_search:
            logger.error("Couldn't find a code in your email.")
            return None

        code = code_search.group(0)
    else:
        if token is None:
            logger.error("Token is required for temp mail but was not provided")
            return None
        code = await get_tempmail_confirmation_code(token)

    logger.info("Got verification code: " + code)

    await code_input_box.send_keys(code)

    await tab.wait(5)

    cookies = await browser.cookies.get_all()

    for cookie in cookies:
        if cookie.name == "WorkosCursorSessionToken" and cookie.value:
            if os.getenv("NO_INSTALL", "false").lower() == "false":
                return cookie.value.split("%3A%3A")[1]
            else:
                return cookie.value

    return None

def exit_with_confirmation(exit_code: int = 1):
    input("Press enter to exit...")
    exit(exit_code)
    

def check_nekobox_availability():
    if os.getenv("USE_NEKOBOX_IF_AVAILABLE", "false").lower() == "true":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            result = sock.connect_ex(("127.0.0.1", int(os.getenv("NEKOBOX_PORT", 2080))))
            if result == 0:
                logger.info("Nekobox is available, using it for proxy.")
                return True
    return False


async def main():
    logger.info("Starting...")

    # Check for admin rights at startup
    if not request_admin_elevation():
        exit(0)
        
    if check_nekobox_availability():
        proxies = {"https": f"socks5://127.0.0.1:{os.getenv('NEKOBOX_PORT', 2080)}"}
    elif os.getenv("PROXY_URL", None):
        proxies = {"https": os.getenv("PROXY_URL")}
    else:
        proxies = None

    try:
        browser = await zd.start(
            lang="en_US", 
            headless=False, 
            browser_executable_path=os.getenv("BROWSER_PATH", None),
            no_sandbox=os.getenv("NO_SANDBOX", "false").lower() == "true"
        )
    except Exception as error:
        logger.exception(error)
        logger.critical("Failed to start the browser.")
        exit_with_confirmation()

    if os.getenv("USE_TEMPMAIL", "false").lower() == "true":
        try:
            email, token = await get_new_email(proxies=proxies)
        except Exception as error:
            logger.critical(f"Failed to get a temporary email address: {error}")
            exit_with_confirmation()
    else:
        email = os.getenv('EMAIL_ADDRESS_PREFIX', 'cur') + "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(4, 8))) + "@" + os.getenv("DOMAIN", "example.com")
        token = None

    session_token = await sign_up(browser, email, token)
    if not session_token:
        logger.error("Couldn't find a session token.")
        exit_with_confirmation()

    await browser.stop()
    
    if os.getenv("NO_INSTALL", "false").lower() == "true":
        logger.info("Generated session token is: " + str(session_token))
        exit_with_confirmation(0)

    logger.info("Updating the local Cursor database...")
    success = await update_auth(email, session_token, session_token)  # type: ignore
    if not success:
        logger.error("Couldn't update the local Cursor database.")
        exit_with_confirmation()

    logger.info("Resetting machine IDs...")
    success = reset_machine_ids()
    if not success:
        logger.error("Failed to reset machine IDs.")
        exit_with_confirmation()

    logger.success("Complete!")
    await asyncio.sleep(1)
    input("Press enter to exit...")


if __name__ == "__main__":
    asyncio.run(main())