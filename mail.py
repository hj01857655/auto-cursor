import asyncio
import email
import imaplib
import traceback
from email.policy import default
from typing import Optional

from loguru import logger


async def fetch_email(imap_server: str, port: int, user: str, password: str, mailbox: str = "INBOX", timeout: int = 60) -> Optional[str]:
    """
    Connects to an IMAP server, checks for new emails every second for up to a minute,
    and returns the text of the first email if found.

    :param imap_server: IMAP server address
    :param port: IMAP server port (usually 993 for SSL)
    :param user: IMAP username
    :param password: IMAP password
    :param mailbox: Mailbox to check (default is "INBOX")
    :param timeout: Timeout in seconds to wait for an email (defaults to 60 seconds)
    :return: The matching email text or None if no match is found
    """

    def check_emails():
        """Fetch and check for new unseen emails synchronously (to be run in a thread)."""
        try:
            logger.info("Checking for new emails...")
            with imaplib.IMAP4_SSL(imap_server, port) as mail:
                mail.login(user, password)
                mail.select(mailbox)

                # Search for all unseen emails
                status, messages = mail.search(None, "UNSEEN")
                if status != "OK":
                    return None

                for num in messages[0].split():
                    logger.info("Found an email...")
                    # Fetch email
                    status, msg_data = mail.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    # Parse email content
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1], policy=default)

                            # Extract email text
                            email_text = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        payload = part.get_payload(decode=True)
                                        if isinstance(payload, bytes):
                                            email_text += payload.decode(part.get_content_charset() or "utf-8")
                            else:
                                payload = msg.get_payload(decode=True)
                                if isinstance(payload, bytes):
                                    email_text = payload.decode(msg.get_content_charset() or "utf-8")

                            return email_text
        except Exception as e:
            traceback.print_exc()
            logger.error(e)
        return None

    async def wait_for_email():
        """Keep checking emails every second until timeout is reached."""
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            email_text = await asyncio.to_thread(check_emails)
            if email_text:
                return email_text
            await asyncio.sleep(1)  # Wait for 1 second before checking again
        return None

    try:
        return await wait_for_email()
    except asyncio.CancelledError:
        return None