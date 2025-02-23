import asyncio
import re

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from loguru import logger

BASE_API_URL = "https://web2.temp-mail.org"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class Attachment:
    def __init__(self, attachment, temp_mail_class, token, email_id):
        self.temp_mail_class = temp_mail_class
        self.token = token
        self.email_id = email_id

        self.filename = attachment["filename"]
        self.attachment_id = attachment["_id"]
        self.size = attachment["size"]
        self.mimetype = attachment["mimetype"]

    async def download(self):
        url = f"{BASE_API_URL}/messages/{self.email_id}/attachment/{self.attachment_id}"
        headers = {
            "User-Agent": self.temp_mail_class.user_agent,
            "Authorization": self.token,
        }
        response_queue = asyncio.Queue()

        async def perform_request():
            def content_callback(chunk):
                response_queue.put_nowait(chunk)

            response = await self.temp_mail_class.session.get(
                url=url, headers=headers, content_callback=content_callback
            )
            await response_queue.put(None)

        stream_task = asyncio.create_task(perform_request())

        while True:
            chunk = await response_queue.get()
            if chunk is None:
                break
            yield chunk

    def __repr__(self):
        return f"Attachment(filename='{self.filename}', attachment_id='{self.attachment_id}', size={self.size}, mimetype='{self.mimetype}')"


class DetailedEmail:
    def __init__(self, detailed_email, temp_mail_class, token):
        self.email_id = detailed_email["_id"]
        self.sender = detailed_email["from"]
        self.subject = detailed_email["subject"]
        self.html_body = detailed_email["bodyHtml"]
        self.text_body = self.html_to_text(self.html_body)
        self.preview = detailed_email["bodyPreview"]
        self.attachments = {
            "count": detailed_email["attachmentsCount"],
            "files": [
                Attachment(attachment, temp_mail_class, token, self.email_id)
                for attachment in detailed_email["attachments"]
            ],
        }

    @staticmethod
    def html_to_text(html_body):
        plain_text = html_body.replace("<br>", "\n")
        soup = BeautifulSoup(plain_text, "html.parser")
        return soup.get_text()

    def __repr__(self):
        return f"DetailedEmail(email_id='{self.email_id}', sender='{self.sender}', subject='{self.subject}', attachments={self.attachments['count']})"


class PreviewEmail:
    def __init__(self, preview_email, temp_mail_class, token):
        self.temp_mail_class = temp_mail_class
        self.token = token

        self.email_id = preview_email["_id"]
        self.sender = preview_email["from"]
        self.subject = preview_email["subject"]
        self.preview = preview_email["bodyPreview"]
        self.attachments = {
            "count": preview_email["attachmentsCount"],
        }

    async def fetch_detailed_email(self):
        url = f"{BASE_API_URL}/messages/{self.email_id}"
        headers = {
            "User-Agent": self.temp_mail_class.user_agent,
            "Authorization": self.token,
        }

        response = await self.temp_mail_class.session.get(url, headers=headers)
        response_json = response.json()

        return DetailedEmail(response_json, self.temp_mail_class, self.token)

    def __repr__(self):
        return f"PreviewEmail(email_id='{self.email_id}', sender='{self.sender}', subject='{self.subject}', attachments={self.attachments['count']})"


class AsyncTempMail:
    def __init__(self, user_agent=None):
        self.user_agent = USER_AGENT if not user_agent else user_agent

    async def __aenter__(self):
        self.session = AsyncSession(impersonate="chrome120", timeout=300)
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def fetch_new_email_address(self):
        url = f"{BASE_API_URL}/mailbox"
        headers = {"User-Agent": self.user_agent}
        response = await self.session.post(url, headers=headers)
        response_json = response.json()

        return response_json

    async def fetch_all_emails(self, token):
        url = f"{BASE_API_URL}/messages"
        headers = {"User-Agent": self.user_agent, "Authorization": token}
        response = await self.session.get(url, headers=headers)
        response_json = response.json()

        return [PreviewEmail(email, self, token) for email in response_json["messages"]]


fetched_email_ids = []

def _filter_emails(all_emails):
    filtered_emails = []
    for email in all_emails:
        if email.email_id not in fetched_email_ids:
            fetched_email_ids.append(email.email_id)
            filtered_emails.append(email)

    return filtered_emails


async def get_new_email() -> list:
    async with AsyncTempMail() as temp_mail:
        response_json = await temp_mail.fetch_new_email_address()

        logger.debug(f"Email: {response_json['mailbox']}")
        logger.debug(f"Token: {response_json['token']}")

        return [response_json["mailbox"], response_json["token"]]


async def get_tempmail_confirmation_code(token: str) -> str:
    async with AsyncTempMail() as temp_mail:
        logger.debug("Waiting for the confirmation code...")
        while True:
            new_emails = _filter_emails(await temp_mail.fetch_all_emails(token))
            if len(new_emails) > 0:
                logger.debug("Got a new email!")
                for email in new_emails:
                    detailed_email = await email.fetch_detailed_email()

                    search_result = re.search(r'\b\d{6}\b', detailed_email.text_body)
                    if search_result:
                        return search_result.group(0)

            await asyncio.sleep(2)