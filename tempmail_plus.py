import asyncio
import re

from curl_cffi.requests import AsyncSession
from loguru import logger

BASE_API_URL = "https://tempmail.plus"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class TempMailPlusEmail:
    """表示一封来自 TempMail.Plus 的邮件"""

    def __init__(self, email_data):
        # 根据真实的 API 响应结构更新字段映射
        self.id = str(email_data.get('mail_id', ''))
        self.sender = email_data.get('from_mail', '')
        self.sender_name = email_data.get('from_name', '')
        self.subject = email_data.get('subject', '')
        self.time = email_data.get('time', '')
        self.is_new = email_data.get('is_new', False)
        self.attachment_count = email_data.get('attachment_count', 0)

        # 为了兼容现有代码，保留这些字段
        self.body = ''  # 需要单独获取邮件内容
        self.text_body = ''  # 需要单独获取邮件内容
        self.timestamp = 0

    def __repr__(self):
        return f"TempMailPlusEmail(id='{self.id}', sender='{self.sender}', subject='{self.subject}', time='{self.time}')"


class AsyncTempMailPlus:
    """TempMail.Plus 异步客户端"""

    def __init__(self, user_agent=None, proxies=None):
        self.user_agent = USER_AGENT if not user_agent else user_agent
        self.proxies = proxies
        self.session = None
        self.email_address = None
        self.token = None
        # 缓存环境变量，避免重复读取
        import os
        self.epin = os.getenv("TEMPMAIL_PLUS_EPIN", "")
        self.polling_interval = int(os.getenv("POLLING_INTERVAL_SECONDS", "10"))
        self.cleanup_emails = os.getenv("CLEANUP_EMAILS_AFTER_USE", "false").lower() == "true"
        self.cleanup_mode = os.getenv("CLEANUP_MODE", "single").lower()

        # 预构建请求头
        self.headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "User-Agent": self.user_agent,
            "Priority": "u=1, i",
            "Sec-Ch-Ua": '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://tempmail.plus/zh/",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        }
    
    async def __aenter__(self):
        self.session = AsyncSession(
            impersonate="chrome120",
            timeout=300,
            proxies=self.proxies,
            verify=False  # 禁用 SSL 证书验证
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()



    def _handle_api_response(self, response_data: dict, operation: str = "API operation") -> tuple:
        """
        统一处理API响应，检查错误并返回结果
        返回: (success: bool, data: any, error_msg: str)
        """
        if not isinstance(response_data, dict):
            return False, None, f"Invalid response format for {operation}"

        if response_data.get('result') == True:
            return True, response_data, ""

        # 检查是否是 PIN 验证错误
        if response_data.get('result') == False:
            err = response_data.get('err', {})
            if err.get('code') == 1021:
                error_msg = f"PIN validation failed: {err.get('msg', 'Pin not valid')}"
                logger.error(f"{error_msg} during {operation}")
                logger.error("Please check your TEMPMAIL_PLUS_EPIN configuration in .env file")
                raise ValueError(error_msg)

        return False, response_data, f"{operation} failed"

    async def _make_request(self, method: str, url: str, email_address: str,
                           params: dict = None, data: dict = None,
                           content_type: str = None, operation: str = "API request"):
        """
        统一的HTTP请求处理方法
        """
        try:
            # 设置请求头
            self.headers["Cookie"] = f"email={email_address}"
            if content_type:
                self.headers["Content-Type"] = content_type

            # 发送请求
            if method.upper() == "GET":
                response = await self.session.get(url, params=params, headers=self.headers)
            elif method.upper() == "DELETE":
                response = await self.session.delete(url, data=data, headers=self.headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.debug(f"{operation} response: {data}")
                    return self._handle_api_response(data, operation)
                except Exception as e:
                    logger.error(f"Failed to parse JSON response for {operation}: {e}")
                    logger.debug(f"Response content: {response.text[:500]}")
                    return False, None, f"JSON parse error for {operation}"
            else:
                logger.debug(f"{operation} failed with status {response.status_code}")
                logger.debug(f"Response: {response.text[:500]}")
                return False, None, f"HTTP {response.status_code} error for {operation}"

        except Exception as e:
            logger.error(f"Error during {operation}: {e}")
            return False, None, f"Request error for {operation}: {str(e)}"

    async def fetch_emails_initial(self, email_address: str) -> tuple:
        """
        初始获取邮箱中的邮件（使用 limit 参数）
        返回: (emails_list, last_id) - 邮件列表和最后一封邮件的ID
        """
        api_url = f"{BASE_API_URL}/api/mails"
        params = {
            'email': email_address,
            'limit': '20',
            'epin': self.epin
        }

        logger.debug("Fetching initial emails with limit=20")
        success, response_data, error_msg = await self._make_request(
            "GET", api_url, email_address, params=params, operation="fetch initial emails"
        )

        if success:
            mail_list = response_data.get('mail_list', [])
            first_id = response_data.get('first_id', 0)
            count = response_data.get('count', 0)

            logger.info(f"Found {count} existing emails, first_id: {first_id}")
            emails = [TempMailPlusEmail(email) for email in mail_list]
            return emails, first_id
        else:
            logger.debug(f"API response indicates failure: {error_msg}")
            return [], 0

    async def fetch_new_emails(self, email_address: str, first_id: int) -> tuple:
        """
        轮询获取新邮件（使用 first_id 参数）
        返回: (emails_list, last_id) - 新邮件列表和最后一封邮件的ID
        """
        api_url = f"{BASE_API_URL}/api/mails"
        params = {
            'email': email_address,
            'first_id': str(first_id),
            'epin': self.epin
        }

        logger.debug(f"Polling for new emails with first_id={first_id}")
        success, response_data, error_msg = await self._make_request(
            "GET", api_url, email_address, params=params, operation="fetch new emails"
        )

        if success:
            mail_list = response_data.get('mail_list', [])
            new_first_id = response_data.get('first_id', 0)
            count = response_data.get('count', 0)

            if count > 0:
                logger.info(f"Found {count} new emails!")
                emails = [TempMailPlusEmail(email) for email in mail_list]
                return emails, new_first_id
            else:
                logger.debug("No new emails found")
                return [], first_id
        else:
            logger.debug(f"API response indicates failure: {error_msg}")
            return [], first_id

    async def fetch_email_content(self, email_address: str, mail_id: str) -> str:
        """
        获取邮件的详细内容
        使用 /api/mails/{mail_id} 接口
        """
        api_url = f"{BASE_API_URL}/api/mails/{mail_id}"
        params = {
            'email': email_address,
            'epin': self.epin
        }

        logger.debug(f"Fetching content for email {mail_id}")
        success, response_data, error_msg = await self._make_request(
            "GET", api_url, email_address, params=params, operation="fetch email content"
        )

        if success:
            # 优先使用文本内容，如果没有则使用HTML内容
            text_content = response_data.get('text', '')
            html_content = response_data.get('html', '')
            content = text_content if text_content.strip() else html_content
            logger.debug(f"Extracted content: {content[:100]}...")
            return content
        else:
            logger.debug(f"Failed to get email content: {error_msg}")
            return ""

    async def delete_emails(self, email_address: str, first_id: int = 0) -> bool:
        """
        删除邮件
        使用 DELETE /api/mails/ 接口
        """
        api_url = f"{BASE_API_URL}/api/mails/"
        form_data = {
            'email': email_address,
            'first_id': str(first_id),
            'epin': self.epin
        }

        logger.debug(f"Deleting emails with first_id={first_id}")
        success, _, error_msg = await self._make_request(
            "DELETE", api_url, email_address, data=form_data,
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
            operation="delete emails"
        )

        if success:
            logger.info("Successfully deleted emails")
            return True
        else:
            logger.debug(f"Delete failed: {error_msg}")
            return False

    async def delete_single_email(self, email_address: str, mail_id: str) -> bool:
        """
        删除单个邮件
        使用 DELETE /api/mails/{mail_id} 接口
        """
        api_url = f"{BASE_API_URL}/api/mails/{mail_id}"
        form_data = {
            'email': email_address,
            'epin': self.epin
        }

        logger.debug(f"Deleting single email with mail_id={mail_id}")
        success, _, error_msg = await self._make_request(
            "DELETE", api_url, email_address, data=form_data,
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
            operation="delete single email"
        )

        if success:
            logger.info(f"Successfully deleted email {mail_id}")
            return True
        else:
            logger.debug(f"Delete single email failed: {error_msg}")
            return False

    def _extract_verification_code(self, email_subject: str, email_content: str) -> str:
        """
        从邮件内容中提取验证码
        返回: 验证码字符串，如果未找到则返回空字符串
        """
        search_content = f"{email_subject} {email_content}"

        # 尝试多种验证码模式
        patterns = [
            # Cursor 特有格式：带空格分隔的6位数字 "8 1 3 9 1 8"
            r'(\d\s+\d\s+\d\s+\d\s+\d\s+\d)',
            # 标准6位数字
            r'\b(\d{6})\b',
            # "code: 123456" 格式
            r'code[:\s]*(\d{6})',
            # "verification: 123456" 格式
            r'verification[:\s]*(\d{6})',
            # 任何6位数字
            r'(\d{6})',
        ]

        for pattern in patterns:
            search_result = re.search(pattern, search_content, re.IGNORECASE)
            if search_result:
                raw_code = search_result.group(1)

                # 处理带空格的验证码格式
                if ' ' in raw_code:
                    # 移除所有空格：'8 1 3 9 1 8' -> '813918'
                    code = re.sub(r'\s+', '', raw_code)
                else:
                    code = raw_code

                if len(code) == 6 and code.isdigit():
                    logger.info(f"Found verification code: {code} (extracted from: '{raw_code}')")
                    return code

        return ""

    async def _cleanup_email_after_use(self, email_address: str, email_id: str):
        """
        根据配置清理邮件
        """
        if self.cleanup_emails:
            if self.cleanup_mode == "single":
                logger.debug(f"Cleaning up single email {email_id} after successful verification code extraction...")
                await self.delete_single_email(email_address, email_id)
            else:
                logger.debug("Cleaning up all emails after successful verification code extraction...")
                await self.delete_emails(email_address, 0)


async def get_tempmail_plus_confirmation_code(email_address: str, proxies=None) -> str:
    """
    从 TempMail.Plus 获取验证码
    使用正确的两阶段轮询机制：
    1. 初始获取（limit=20）确定基线
    2. 轮询检查（first_id=last_id）获取新邮件
    """
    async with AsyncTempMailPlus(proxies=proxies) as temp_mail:
        logger.debug(f"Waiting for confirmation code from TempMail.Plus for {email_address}...")

        # 第一阶段：获取当前所有邮件，确定基线
        logger.debug("Phase 1: Getting current emails to establish baseline...")
        current_emails, first_id = await temp_mail.fetch_emails_initial(email_address)

        # 无论是否有邮件，都使用 API 返回的 first_id 作为轮询起点
        # 如果没有邮件，first_id 通常为 0
        # 如果有邮件，first_id 为最新一封邮件的 ID
        polling_id = first_id
        logger.debug(f"Found {len(current_emails)} existing emails, will start polling from ID: {polling_id}")

        # 第二阶段：轮询检查新邮件
        logger.debug(f"Phase 2: Starting polling for new emails from ID {polling_id}")
        max_attempts = 60  # 最多尝试60次（约3分钟）
        attempt = 0

        while attempt < max_attempts:
            try:
                # 轮询获取新邮件
                new_emails, new_first_id = await temp_mail.fetch_new_emails(email_address, polling_id)

                if len(new_emails) > 0:
                    logger.debug(f"Got {len(new_emails)} new email(s) from TempMail.Plus!")

                    for email in new_emails:
                        logger.debug(f"Processing email from {email.sender}: {email.subject}")

                        # 获取邮件的详细内容
                        email_content = await temp_mail.fetch_email_content(email_address, email.id)

                        if email_content:
                            logger.debug(f"Got email content: {email_content[:100]}...")

                            # 使用提取的验证码方法
                            code = temp_mail._extract_verification_code(email.subject, email_content)
                            if code:
                                # 清理邮箱（如果配置了的话）
                                await temp_mail._cleanup_email_after_use(email_address, email.id)
                                return code

                            # 如果没有找到验证码，记录邮件内容用于调试
                            logger.debug(f"No verification code found in email content: {email_content[:200]}...")
                        else:
                            logger.debug(f"Failed to get email content for mail_id: {email.id}")

                    # 更新轮询ID为最新的邮件ID
                    polling_id = new_first_id

                attempt += 1
                logger.debug(f"Attempt {attempt}/{max_attempts} - No new emails with verification code")

                # 使用配置的轮询间隔（默认10秒，与官方网页保持一致）
                await asyncio.sleep(temp_mail.polling_interval)

            except Exception as e:
                logger.error(f"Error fetching emails from TempMail.Plus: {e}")
                attempt += 1

                # 出错时也使用相同的间隔
                await asyncio.sleep(temp_mail.polling_interval)

        raise TimeoutError(f"Failed to get verification code after {max_attempts} attempts")