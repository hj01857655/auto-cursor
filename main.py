import asyncio
import base64
import hashlib
import json
import os
import random
import string
import sys
import uuid
import ctypes
from typing import Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

import zendriver as zd
from dotenv import load_dotenv
from loguru import logger
from zendriver.core.browser import Browser

from auth import update_auth
from reset import reset_machine_ids
from reset_helpers.windows import check_admin
from tempmail_plus import get_tempmail_plus_confirmation_code

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


async def get_long_term_tokens(browser: Browser, session_token: str) -> Optional[Tuple[str, str]]:
    """
    获取长期有效的访问令牌和刷新令牌
    使用PKCE OAuth2流程和注册时获取的session token

    Args:
        browser: 浏览器实例
        session_token: 注册时获取的 WorkosCursorSessionToken cookie值

    Returns:
        tuple: (access_token, refresh_token) 如果成功，否则返回 None
    """
    try:
        # 获取verifier和challenge
        verifier, challenge = generate_pkce_pair()

        # 生成UUID
        uuid_val = str(uuid.uuid4())
        logger.info(f"【令牌获取】生成UUID: {uuid_val}")

        # 生成授权登录URL
        login_url = f"https://www.cursor.com/loginDeepControl?challenge={challenge}&uuid={uuid_val}&mode=login"
        logger.info(f"【令牌获取】生成的登录URL: {login_url}")

        # 直接使用浏览器方式访问登录URL
        logger.info(f"【令牌获取】直接使用浏览器方式访问登录URL: {login_url}")
        tab = await browser.get(login_url)
        logger.info("【令牌获取】等待登录页面加载...")

        # 等待页面加载
        await asyncio.sleep(2)

        # 等待页面加载并检查是否需要用户交互
        try:
            logger.info("【令牌获取】等待页面加载完成...")
            await asyncio.sleep(3)

            # 检查是否需要点击"Yes, Log In"按钮（使用find方法）
            try:
                logger.info("【令牌获取】检查页面是否需要授权...")
                
                # 等待页面加载
                await asyncio.sleep(3)
                
                # 使用find方法查找包含"Yes, Log In"文本的元素
                yes_login_btn = await tab.find("Yes, Log In", best_match=True)
                
                if yes_login_btn:
                    logger.info("【令牌获取】找到'Yes, Log In'按钮，准备点击")
                    await yes_login_btn.click()
                    logger.info("【令牌获取】已点击'Yes, Log In'按钮")

                    # 点击授权后等待授权完成，避免太快访问导致重定向回登录页面
                    logger.info("【令牌获取】等待授权完成...")
                    await asyncio.sleep(8)  # 等待8秒让授权完成
                    logger.info("【令牌获取】授权等待完成，继续轮询令牌")
                else:
                    logger.error("【令牌获取】未找到'Yes, Log In'按钮，无法完成授权，流程中断")
                    return None
                    
            except Exception as click_error:
                logger.error(f"【令牌获取】点击按钮失败: {click_error}")
                return None

        except Exception as auth_error:
            logger.error(f"【令牌获取】检查授权页面失败: {auth_error}")
            logger.info("【令牌获取】继续执行令牌轮询...")

        except Exception as e:
            logger.warning(f"【令牌获取】页面检查时出错: {e}")
            logger.info("【令牌获取】继续执行令牌轮询...")

        # 构建轮询URL
        auth_poll_url = f"https://api2.cursor.sh/auth/poll?uuid={uuid_val}&verifier={verifier}"

        # 从 session_token 中提取cookie值
        if session_token.startswith("WorkosCursorSessionToken="):
            cookie_value = session_token.split("=", 1)[1]
        else:
            cookie_value = session_token

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Cursor/0.48.6 Chrome/132.0.6834.210 Electron/34.3.4 Safari/537.36",
            "Accept": "*/*",
            "Cookie": f"WorkosCursorSessionToken={cookie_value}"
        }

        logger.info(f"【令牌获取】使用session token进行认证: WorkosCursorSessionToken={cookie_value[:15]}...")

        logger.info(f"【令牌获取】开始轮询获取令牌，轮询地址: {auth_poll_url}")

        # 尝试30次，每次等待1秒
        for i in range(30):
            logger.info(f"【令牌获取】轮询获取令牌... (第{i+1}次/共30次)")
            try:
                # 创建请求对象
                req = Request(auth_poll_url)
                for key, value in headers.items():
                    req.add_header(key, value)

                # 发送请求
                with urlopen(req, timeout=5) as response:
                    status_code = response.getcode()
                    response_text = response.read().decode('utf-8')

                logger.info(f"【令牌获取】轮询响应状态码: {status_code}")

                if status_code == 200:
                    # 检查响应内容是否为空
                    if not response_text.strip():
                        logger.warning("【令牌获取】轮询响应内容为空")
                        continue

                    try:
                        data = json.loads(response_text)
                        logger.info(f"【令牌获取】轮询返回数据: {str(data)[:100]}...")

                        access_token = data.get("accessToken")
                        refresh_token = data.get("refreshToken")
                        auth_id = data.get("authId", "")

                        if access_token:
                            logger.info("【令牌获取】成功获取access_token")
                        if refresh_token:
                            logger.info("【令牌获取】成功获取refresh_token")
                        if auth_id:
                            logger.info(f"【令牌获取】获取到auth_id: {auth_id}")

                        if access_token or refresh_token:
                            token_preview = (access_token or refresh_token)[:15]
                            logger.info(f"【令牌获取】成功获取长期令牌: {token_preview}...")
                            return access_token, refresh_token
                        else:
                            logger.warning("【令牌获取】未在响应中找到令牌")

                    except json.JSONDecodeError as json_error:
                        logger.error(f"【令牌获取】解析轮询响应JSON失败: {str(json_error)}")
                        logger.error(f"【令牌获取】轮询响应内容: {response_text[:200]}...")

                else:
                    logger.error(f"【令牌获取】轮询请求失败，状态码: {status_code}")

            except (URLError, Exception) as poll_error:
                logger.error(f"【令牌获取】轮询请求出错: {str(poll_error)}")

            logger.info("【令牌获取】轮询等待1秒...")
            await asyncio.sleep(1)

        logger.error("【令牌获取】轮询超时，未能获取到令牌")
        return None

    except Exception as e:
        logger.error(f"【令牌获取】获取长期令牌时出错: {e}")
        return None


def save_account_info(email: str, password: str, session_token: str, access_token: str = None, refresh_token: str = None, trial_info: dict = None, usage_info: str = None, user_id: str = None, long_term_cookie: str = None):
    """
    保存账户信息到文件

    Args:
        email: 注册邮箱
        password: 注册密码
        session_token: 短期session token
        access_token: 长期访问令牌（可选）
        refresh_token: 刷新令牌（可选）
        trial_info: 试用信息（可选）
        usage_info: 使用量信息（可选）
        user_id: 用户ID（可选，如果未提供会从session_token中提取）
        long_term_cookie: 使用长期令牌构建的cookie（可选）
    """
    import datetime

    # 如果没有提供user_id，尝试从session_token中提取
    if not user_id:
        try:
            if session_token.startswith("WorkosCursorSessionToken="):
                cookie_value = session_token.split("=", 1)[1]
            else:
                cookie_value = session_token
            user_id = cookie_value.split("%3A%3A")[0]  # %3A%3A 是 :: 的URL编码
            logger.info(f"【账户存储】从session token中提取用户ID: {user_id}")
        except Exception as e:
            logger.warning(f"【账户存储】无法从session token中提取用户ID: {e}")
            user_id = "unknown"

    account_info = {
        "user_id": user_id,
        "email": email,
        "password": password,
        "session_token": session_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "long_term_cookie": long_term_cookie,
        "trial_info": trial_info or {},
        "usage_info": usage_info or "unknown/unknown",
        "created_at": datetime.datetime.now().isoformat(),
        "status": "active"
    }

    # 保存到JSON文件
    accounts_file = "cursor_accounts.json"
    accounts_list = []

    # 读取现有账户（如果文件存在）
    if os.path.exists(accounts_file):
        try:
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts_list = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            accounts_list = []

    # 添加新账户
    accounts_list.append(account_info)

    # 保存到文件
    try:
        with open(accounts_file, 'w', encoding='utf-8') as f:
            json.dump(accounts_list, f, indent=2, ensure_ascii=False)
        logger.info(f"【账户存储】账户信息已保存到 {accounts_file}")
        logger.info(f"【账户存储】用户ID: {user_id}")
        logger.info(f"【账户存储】邮箱: {email}")
        logger.info(f"【账户存储】密码: {password}")
        if access_token:
            logger.info(f"【账户存储】访问令牌: {access_token[:15]}...")
        if refresh_token:
            logger.info(f"【账户存储】刷新令牌: {refresh_token[:15]}...")
        if long_term_cookie:
            logger.info(f"【账户存储】长期Cookie: {long_term_cookie[:50]}...")
        if trial_info:
            logger.info(f"【账户存储】试用信息: {trial_info}")
        if usage_info:
            logger.info(f"【账户存储】使用量信息: {usage_info}")
    except Exception as e:
        logger.error(f"【账户存储】保存账户信息失败: {e}")


def load_account_info(email: str = None):
    """
    读取账户信息

    Args:
        email: 指定邮箱地址，如果为None则返回所有账户

    Returns:
        dict or list: 指定邮箱的账户信息或所有账户列表
    """
    accounts_file = "cursor_accounts.json"

    if not os.path.exists(accounts_file):
        logger.warning(f"【账户读取】账户文件 {accounts_file} 不存在")
        return None if email else []

    try:
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts_list = json.load(f)

        if email:
            # 查找指定邮箱的账户
            for account in accounts_list:
                if account.get('email') == email:
                    logger.info(f"【账户读取】找到账户: {email}")
                    return account
            logger.warning(f"【账户读取】未找到邮箱 {email} 的账户信息")
            return None
        else:
            # 返回所有账户
            logger.info(f"【账户读取】读取到 {len(accounts_list)} 个账户")
            return accounts_list

    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"【账户读取】读取账户信息失败: {e}")
        return None if email else []


def update_account_cookie(email: str, new_long_term_cookie: str) -> bool:
    """
    更新账户文件中的长期Cookie

    Args:
        email: 账户邮箱
        new_long_term_cookie: 新的长期Cookie

    Returns:
        bool: 更新成功返回True，失败返回False
    """
    accounts_file = "cursor_accounts.json"

    if not os.path.exists(accounts_file):
        logger.error(f"【Cookie更新】账户文件 {accounts_file} 不存在")
        return False

    try:
        # 读取现有账户
        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts_list = json.load(f)

        # 查找并更新指定邮箱的账户
        updated = False
        for account in accounts_list:
            if account.get('email') == email:
                old_cookie = account.get('long_term_cookie', 'None')
                account['long_term_cookie'] = new_long_term_cookie

                # 更新时间戳
                import datetime
                account['cookie_updated_at'] = datetime.datetime.now().isoformat()

                logger.info(f"【Cookie更新】已更新账户 {email} 的长期Cookie")
                logger.info(f"【Cookie更新】旧Cookie: {old_cookie[:50]}...")
                logger.info(f"【Cookie更新】新Cookie: {new_long_term_cookie[:50]}...")
                updated = True
                break

        if not updated:
            logger.warning(f"【Cookie更新】未找到邮箱 {email} 的账户")
            return False

        # 保存更新后的账户列表
        with open(accounts_file, 'w', encoding='utf-8') as f:
            json.dump(accounts_list, f, indent=2, ensure_ascii=False)

        logger.info(f"【Cookie更新】账户文件已更新")
        return True

    except Exception as e:
        logger.error(f"【Cookie更新】更新失败: {e}")
        return False


def extract_user_id(session_token: str) -> str:
    """
    从session token中提取用户ID

    Args:
        session_token: WorkosCursorSessionToken cookie值

    Returns:
        str: 用户ID，如果提取失败返回 "unknown"
    """
    try:
        if session_token.startswith("WorkosCursorSessionToken="):
            cookie_value = session_token.split("=", 1)[1]
        else:
            cookie_value = session_token

        user_id = cookie_value.split("%3A%3A")[0]  # %3A%3A 是 :: 的URL编码
        logger.info(f"【用户ID】提取成功: {user_id}")
        return user_id
    except Exception as e:
        logger.warning(f"【用户ID】提取失败: {e}")
        return "unknown"


def build_long_term_cookie(user_id: str, long_term_token: str) -> str:
    """
    使用长期令牌构建新的 WorkosCursorSessionToken cookie
    这是 extract_user_id 的逆向操作

    原理：
    - 原始cookie格式: WorkosCursorSessionToken=user_01JX0MN6AD21E0ZS8MDEJHPN3S%3A%3A短期令牌
    - 新cookie格式: WorkosCursorSessionToken=user_01JX0MN6AD21E0ZS8MDEJHPN3S%3A%3A长期令牌
    - %3A%3A 是 :: 的URL编码

    Args:
        user_id: 用户ID (如: user_01JX0MN6AD21E0ZS8MDEJHPN3S)
        long_term_token: 长期令牌 (access_token 或 refresh_token，有效期2个月)

    Returns:
        str: 新的 WorkosCursorSessionToken cookie值，有效期2个月
    """
    try:
        # 构建新的cookie值：user_id + %3A%3A + long_term_token
        # 这样替换了原来短期令牌（<2小时）为长期令牌（2个月）
        cookie_value = f"{user_id}%3A%3A{long_term_token}"
        full_cookie = f"WorkosCursorSessionToken={cookie_value}"

        logger.info(f"【长期Cookie】构建成功，有效期2个月")
        logger.info(f"【长期Cookie】用户ID: {user_id}")
        logger.info(f"【长期Cookie】长期令牌: {long_term_token[:15]}...")
        logger.info(f"【长期Cookie】新Cookie: WorkosCursorSessionToken={user_id}%3A%3A{long_term_token[:15]}...")

        return full_cookie

    except Exception as e:
        logger.error(f"【长期Cookie】构建失败: {e}")
        return None


def verify_jwt_expiry(jwt_token: str) -> dict:
    """
    验证JWT令牌的有效期（使用手动解码方式，稳定可靠）

    Args:
        jwt_token: JWT令牌字符串

    Returns:
        dict: 包含有效期信息的字典
    """
    try:
        import datetime
        import base64

        logger.info("【JWT验证】开始验证JWT令牌有效期...")

        # 手动解码JWT（稳定可靠的方式）
        parts = jwt_token.split('.')
        if len(parts) != 3:
            logger.error("【JWT验证】JWT格式错误，不是标准的三段式结构")
            return {"valid": False, "error": "Invalid JWT format"}

        try:
            # 解码header
            header_part = parts[0]
            padding = 4 - len(header_part) % 4
            if padding != 4:
                header_part += '=' * padding
            header_bytes = base64.urlsafe_b64decode(header_part)
            header = json.loads(header_bytes.decode('utf-8'))

            # 解码payload
            payload_part = parts[1]
            padding = 4 - len(payload_part) % 4
            if padding != 4:
                payload_part += '=' * padding
            payload_bytes = base64.urlsafe_b64decode(payload_part)
            payload = json.loads(payload_bytes.decode('utf-8'))

            logger.info("【JWT验证】✅ JWT解码成功")
            logger.info(f"【JWT验证】算法: {header.get('alg')}, 类型: {header.get('typ')}")

        except Exception as decode_error:
            logger.error(f"【JWT验证】JWT解码失败: {decode_error}")
            return {"valid": False, "error": f"JWT decode error: {decode_error}"}

        # 获取过期时间（exp字段）
        exp_timestamp = payload.get('exp')
        if not exp_timestamp:
            logger.warning("【JWT验证】JWT中没有找到exp字段")
            return {"valid": False, "error": "No exp field in JWT"}

        # 转换为可读时间
        exp_datetime = datetime.datetime.fromtimestamp(exp_timestamp)
        current_datetime = datetime.datetime.now()

        # 计算剩余有效期
        remaining_time = exp_datetime - current_datetime
        remaining_days = remaining_time.days
        remaining_hours = remaining_time.seconds // 3600

        logger.info(f"【JWT验证】JWT过期时间: {exp_datetime}")
        logger.info(f"【JWT验证】当前时间: {current_datetime}")
        logger.info(f"【JWT验证】剩余有效期: {remaining_days}天 {remaining_hours}小时")

        # 判断是否为长期令牌（至少30天）
        is_long_term = remaining_days >= 30

        result = {
            "valid": True,
            "exp_timestamp": exp_timestamp,
            "exp_datetime": exp_datetime.isoformat(),
            "current_datetime": current_datetime.isoformat(),
            "remaining_days": remaining_days,
            "remaining_hours": remaining_hours,
            "is_long_term": is_long_term,
            "payload": payload,
            "header": header,
            "algorithm": header.get("alg", "unknown"),
            "token_type": header.get("typ", "unknown")
        }

        if is_long_term:
            logger.info(f"【JWT验证】✅ 确认为长期令牌，有效期约{remaining_days}天")
            logger.info(f"【JWT验证】算法: {header.get('alg')}, 类型: {header.get('typ')}")
        else:
            logger.warning(f"【JWT验证】❌ 短期令牌，有效期仅{remaining_days}天{remaining_hours}小时")
            logger.warning("【JWT验证】该令牌将被pass掉，不会用于构建长期Cookie")

        return result

    except Exception as e:
        logger.error(f"【JWT验证】JWT验证失败: {e}")
        return {"valid": False, "error": str(e)}


def get_trial_info(session_token: str) -> dict:
    """
    获取试用信息

    Args:
        session_token: WorkosCursorSessionToken cookie值

    Returns:
        dict: 试用信息，包含membershipType、daysRemainingOnTrial等
    """
    try:
        logger.info("【试用信息】开始获取试用信息...")

        # 从 session_token 中提取cookie值
        if session_token.startswith("WorkosCursorSessionToken="):
            cookie_value = session_token.split("=", 1)[1]
        else:
            cookie_value = session_token

        # 构建请求头
        headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "content-type": "application/json",
            "priority": "u=1, i",
            "sec-ch-ua": "\"Chromium\";v=\"136\", \"Microsoft Edge\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
            "sec-ch-ua-arch": "\"x86\"",
            "sec-ch-ua-bitness": "\"64\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-ch-ua-platform-version": "\"19.0.0\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "cookie": f"WorkosCursorSessionToken={cookie_value}",
            "Referer": "https://www.cursor.com/dashboard",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        }

        # 发送请求
        req = Request("https://www.cursor.com/api/auth/stripe")
        for key, value in headers.items():
            req.add_header(key, value)

        with urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            response_text = response.read().decode('utf-8')

        logger.info(f"【试用信息】API响应状态码: {status_code}")

        if status_code == 200:
            try:
                trial_data = json.loads(response_text)
                logger.info(f"【试用信息】获取成功: {trial_data}")

                # 解析试用信息（只保留需要的字段）
                membership_type = trial_data.get("membershipType", "unknown")
                days_remaining = trial_data.get("daysRemainingOnTrial", 0)

                logger.info(f"【试用信息】会员类型: {membership_type}")
                logger.info(f"【试用信息】剩余试用天数: {days_remaining}")

                # 只返回需要的字段
                return {
                    "membershipType": membership_type,
                    "daysRemainingOnTrial": days_remaining
                }

            except json.JSONDecodeError as e:
                logger.error(f"【试用信息】解析响应JSON失败: {e}")
                logger.error(f"【试用信息】响应内容: {response_text}")
                return {}
        else:
            logger.error(f"【试用信息】API请求失败，状态码: {status_code}")
            logger.error(f"【试用信息】响应内容: {response_text}")
            return {}

    except Exception as e:
        logger.error(f"【试用信息】获取试用信息失败: {e}")
        return {}


def get_usage_info(session_token: str) -> str:
    """
    获取使用量信息

    Args:
        session_token: WorkosCursorSessionToken cookie值

    Returns:
        str: 使用量信息，格式为 "已使用/总限制" (如: "0/150")
    """
    try:
        logger.info("【使用量信息】开始获取使用量信息...")

        # 从 session_token 中提取cookie值和user ID
        if session_token.startswith("WorkosCursorSessionToken="):
            cookie_value = session_token.split("=", 1)[1]
        else:
            cookie_value = session_token

        # 从cookie值中提取user ID (格式: user_01JX0MN6AD21E0ZS8MDEJHPN3S%3A%3A...)
        try:
            user_id = cookie_value.split("%3A%3A")[0]  # %3A%3A 是 :: 的URL编码
            logger.info(f"【使用量信息】提取到用户ID: {user_id}")
        except Exception as e:
            logger.error(f"【使用量信息】提取用户ID失败: {e}")
            return "unknown/unknown"

        # 构建请求头
        headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "priority": "u=1, i",
            "sec-ch-ua": "\"Chromium\";v=\"136\", \"Microsoft Edge\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
            "sec-ch-ua-arch": "\"x86\"",
            "sec-ch-ua-bitness": "\"64\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-ch-ua-platform-version": "\"19.0.0\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "cookie": f"WorkosCursorSessionToken={cookie_value}",
            "Referer": "https://www.cursor.com/dashboard",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        }

        # 构建API URL
        usage_url = f"https://www.cursor.com/api/usage?user={user_id}"
        logger.info(f"【使用量信息】请求URL: {usage_url}")

        # 发送请求
        req = Request(usage_url)
        for key, value in headers.items():
            req.add_header(key, value)

        with urlopen(req, timeout=10) as response:
            status_code = response.getcode()
            response_text = response.read().decode('utf-8')

        logger.info(f"【使用量信息】API响应状态码: {status_code}")

        if status_code == 200:
            try:
                usage_data = json.loads(response_text)
                logger.info(f"【使用量信息】获取成功: {usage_data}")

                # 提取GPT-4使用量信息
                gpt4_data = usage_data.get("gpt-4", {})
                premium_usage = gpt4_data.get("numRequestsTotal", 0)
                max_premium_usage = gpt4_data.get("maxRequestUsage", 150)

                usage_format = f"{premium_usage}/{max_premium_usage}"
                logger.info(f"【使用量信息】GPT-4使用量: {usage_format}")

                return usage_format

            except json.JSONDecodeError as e:
                logger.error(f"【使用量信息】解析响应JSON失败: {e}")
                logger.error(f"【使用量信息】响应内容: {response_text}")
                return "error/error"
        else:
            logger.error(f"【使用量信息】API请求失败，状态码: {status_code}")
            logger.error(f"【使用量信息】响应内容: {response_text}")
            return "error/error"

    except Exception as e:
        logger.error(f"【使用量信息】获取使用量信息失败: {e}")
        return "error/error"


async def visit_dashboard_page(browser: Browser, session_token: str = None) -> bool:
    """
    访问 Cursor Dashboard 页面并获取试用信息

    Args:
        browser: 浏览器实例
        session_token: 可选的session token，用于获取试用信息

    Returns:
        bool: 访问成功返回 True，失败返回 False
    """
    try:
        logger.info("【Dashboard页面】开始访问 Cursor Dashboard 页面...")

        # 访问Dashboard页面
        await browser.get("https://www.cursor.com/dashboard")
        logger.info("【Dashboard页面】已导航到Dashboard页面")

        # 等待页面加载（增加等待时间，确保授权状态稳定）
        logger.info("【Dashboard页面】等待页面完全加载...")
        await asyncio.sleep(8)  # 增加到8秒，确保页面完全加载

        # 检查页面是否正确加载
        current_url = await browser.current_url()
        if "cursor.com/dashboard" in current_url:
            logger.info("【Dashboard页面】Dashboard页面加载成功，注册确认完成")

            # 如果提供了session token，获取试用信息和使用量信息
            if session_token:
                trial_info = get_trial_info(session_token)
                usage_info = get_usage_info(session_token)

                if trial_info:
                    logger.info("【Dashboard页面】试用信息获取成功")
                if usage_info and usage_info != "error/error":
                    logger.info(f"【Dashboard页面】使用量信息获取成功: {usage_info}")

                return True
            else:
                logger.info("【Dashboard页面】未提供session token，跳过信息获取")
                return True
        else:
            logger.warning(f"【Dashboard页面】页面重定向到: {current_url}")
            return False

    except Exception as e:
        logger.error(f"【Dashboard页面】访问Dashboard页面失败: {e}")
        return False


def generate_pkce_pair():
    """
    生成PKCE配对用于OAuth2授权码流程

    Returns:
        tuple: (verifier, challenge) - PKCE验证器和挑战码
    """
    logger.info("【令牌获取】开始生成PKCE配对……")

    # 生成verifier：43字节的随机字符串
    verifier = base64.urlsafe_b64encode(os.urandom(43)).decode('utf-8').rstrip('=')

    # 生成challenge_bytes: 是verifier的sha256哈希值
    challenge_bytes = hashlib.sha256(verifier.encode('utf-8')).digest()

    # 生成challenge：base64编码的challenge_bytes
    challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

    logger.info(f"【令牌获取】PKCE配对生成成功[verifier:{verifier},challenge:{challenge}]")
    return verifier, challenge


async def sign_up(browser: Browser, email: str, temp_email: str) -> Optional[Tuple[str, str]]:
    """
    Registers a new Cursor account.
    Requires user interaction.

    Args:
        browser: 浏览器实例
        email: 注册邮箱
        temp_email: 用于接收验证码的临时邮箱

    Returns:
        tuple: (session_token, password) 成功时返回令牌和密码，失败时返回 None
    """

    tab = await browser.get(sign_up_url)

    # 等待页面加载后再检查title是否为"请稍候"
    await asyncio.sleep(3)
    try:
        title = tab.title
        if "请稍候" in title:
            logger.error("【注册中断】页面加载后title仍为'请稍候'，自动退出注册流程并关闭浏览器")
            await browser.stop()
            return None
    except Exception as e:
        logger.warning(f"【注册检查】获取页面title失败: {e}")

    first_name = random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=5))
    last_name = random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=5))
    password = ''.join(random.choices(string.ascii_uppercase + string.digits + string.punctuation, k=12))

    logger.debug(f"First name: {first_name} | Last name: {last_name} | Password: {password} | Email: {email}")

    await tab

    # 添加随机延迟，模拟人类行为
    random_delay = random.uniform(2, 4)
    logger.debug(f"【人类模拟】等待 {random_delay:.1f} 秒...")
    await asyncio.sleep(random_delay)

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

    # 添加随机延迟，模拟人类输入行为
    random_delay = random.uniform(1, 3)
    logger.debug(f"【人类模拟】输入密码前等待 {random_delay:.1f} 秒...")
    await asyncio.sleep(random_delay)

    logger.info(f"Entering the password...{password}")
    await password_box.send_keys(password)

    logger.info("Submitting...")
    submit_button = await tab.select("button[type='submit']")
    await submit_button.click()

    # 等待页面响应并检查是否成功到达验证码页面
    await tab.wait(5)
    try:
        page_content = await tab.get_content()

        # 检查是否出现域名黑名单错误
        if "Sign up is restricted" in page_content:
            logger.error("【域名黑名单】检测到 'Sign up is restricted' 错误")
            logger.error("【域名黑名单】当前邮箱域名已被 Cursor 加入黑名单")
            logger.error(f"【域名黑名单】被限制的域名: {email.split('@')[1]}")
            logger.info("【解决方案】需要更换邮箱域名:")
            logger.info("  1. 使用其他邮箱服务商的域名")
            logger.info("  2. 购买新的域名用于注册")
            logger.info("  3. 使用企业邮箱域名")
            logger.info("【程序退出】由于域名被限制，无法继续注册")
            return None

        # 检查是否成功到达验证码页面
        elif "token" in page_content.lower() or "verification" in page_content.lower() or "code" in page_content.lower():
            logger.info("【注册成功】✅ 密码提交成功，已到达验证码页面")
            logger.info("【注册成功】邮箱域名未被限制，可以继续注册流程")
        else:
            # 检查其他可能的错误
            error_patterns = [
                "error", "blocked", "forbidden", "not allowed", "invalid"
            ]
            found_errors = []
            for pattern in error_patterns:
                if pattern in page_content.lower():
                    found_errors.append(pattern)

            if found_errors:
                logger.warning(f"【注册警告】检测到可能的错误: {', '.join(found_errors)}")
                logger.debug(f"【注册调试】页面内容片段: {page_content[:500]}...")
            else:
                logger.info("【注册检查】密码提交成功，准备继续验证码流程")

    except Exception as error_check:
        logger.debug(f"【注册调试】检查页面状态失败: {error_check}")

    # 修改流程：先获取邮箱中的验证码
    logger.info("【验证码获取】开始获取验证码邮件...")
    code = None
    retry_count = 0
    max_retries = 5
    
    while not code and retry_count < max_retries:
        try:
            # 使用 TempMail.Plus 获取验证码（从临时邮箱）
            # 假设 get_tempmail_plus_confirmation_code 函数可以获取最新邮件
            code = await get_tempmail_plus_confirmation_code(temp_email)
            
            if code:
                logger.info(f"【验证码获取】成功获取验证码: {code}")
                break
            else:
                retry_count += 1
                logger.warning(f"【验证码获取】未找到验证码，第{retry_count}次重试...")
                # 等待一段时间再重试
                await asyncio.sleep(5)
        except Exception as e:
            retry_count += 1
            logger.error(f"【验证码获取】获取验证码出错: {e}，第{retry_count}次重试...")
            await asyncio.sleep(5)
    
    # 确保验证码成功获取
    if not code:
        logger.error("【注册中断】多次尝试后仍未能获取验证码，无法继续注册流程")
        await browser.stop()
        return None
    
    # 然后等待验证码输入框出现
    code_input_box = None
    logger.warning("Please tick the turnstile checkbox...")
    input_retry_count = 0
    max_input_retries = 10
    
    while not code_input_box and input_retry_count < max_input_retries:
        try:
            code_input_box = await tab.select("input[name='code']", timeout=1)
            if code_input_box:
                logger.info("【验证码输入】找到验证码输入框")
            else:
                input_retry_count += 1
                logger.warning(f"【验证码输入】未找到验证码输入框，第{input_retry_count}次重试...")
                await asyncio.sleep(1)
        except Exception:
            input_retry_count += 1
            logger.warning(f"【验证码输入】查找验证码输入框失败，第{input_retry_count}次重试...")
            await asyncio.sleep(1)
    
    if not code_input_box:
        logger.error("【注册中断】未能找到验证码输入框，无法继续注册流程")
        await browser.stop()
        return None
        
    logger.info(f"【验证码输入】准备输入验证码: {code}")
    await code_input_box.send_keys(code)

    await tab.wait(5)

    cookies = await browser.cookies.get_all()

    for cookie in cookies:
        if cookie.name == "WorkosCursorSessionToken" and cookie.value:
            logger.info(f"WorkosCursorSessionToken={cookie.value}")
            # 返回session token和密码
            return f"WorkosCursorSessionToken={cookie.value}", password

    return None

async def sign_in(browser: Browser, email: str) -> Optional[dict]:
    """
    登录到 Cursor 账户（使用验证码方式）

    Args:
        browser: 浏览器实例
        email: 邮箱地址

    Returns:
        登录成功时返回包含完整信息的字典，失败时返回 None
        字典包含: email, session_token, long_term_tokens, trial_info, usage_info, user_id
    """
    logger.info(f"【登录】开始登录过程，邮箱: {email}")
    
    # 打开登录页面
    tab = await browser.get(login_url)
    
    # 等待页面加载后再检查title是否为"请稍候"
    await asyncio.sleep(3)
    try:
        title = tab.title
        if "请稍候" in title:
            logger.error("【登录中断】页面加载后title仍为'请稍候'，自动退出登录流程并关闭浏览器")
            await browser.stop()
            return None
    except Exception as e:
        logger.warning(f"【登录检查】获取页面title失败: {e}")
    
    # 等待页面加载
    await tab
    
    # 添加随机延迟，模拟人类行为
    random_delay = random.uniform(1, 2)
    logger.debug(f"【人类模拟】等待 {random_delay:.1f} 秒...")
    await asyncio.sleep(random_delay)
    
    # 输入邮箱
    logger.info("【登录】输入邮箱...")
    try:
        email_box = await tab.select("input[name='email']")
        await email_box.send_keys(email)
    except Exception as e:
        logger.error(f"【登录失败】无法找到邮箱输入框: {e}")
        return None
    
    await asyncio.sleep(1)
    
    # 点击提交按钮
    logger.info("【登录】提交邮箱...")
    try:
        submit_button = await tab.select("button[type='submit']")
        await submit_button.click()
    except Exception as e:
        logger.error(f"【登录失败】无法找到或点击提交按钮: {e}")
        return None

    # 等待页面加载，然后直接选择验证码登录方式
    await asyncio.sleep(3)

    logger.info("【登录】选择验证码登录方式...")
    try:
        # 直接点击"Email sign-in code"按钮，跳过密码输入
        email_code_button = await tab.select("button[name='intent'][value='magic-code']")
        await email_code_button.click()
        logger.info("【登录】已选择验证码登录方式")
    except Exception as e:
        logger.error(f"【登录失败】无法找到或点击验证码登录按钮: {e}")
        return None
    
    # 等待登录完成
    logger.info("【登录】等待登录完成...")
    await tab.wait(5)
    
    # 检查是否需要输入验证码
    try:
        # 检查页面内容，判断是否需要输入验证码
        page_content = await tab.get_content()
        
        # 检查是否有错误信息
        error_patterns = [
            "incorrect password", "invalid email", "error", "not found", "invalid credentials"
        ]
        found_errors = []
        for pattern in error_patterns:
            if pattern in page_content.lower():
                found_errors.append(pattern)
        
        if found_errors:
            logger.error(f"【登录失败】检测到错误: {', '.join(found_errors)}")
            logger.debug(f"【登录调试】页面内容片段: {page_content[:500]}...")
            return None
        
        # 检查是否需要验证码
        if "verification" in page_content.lower() or "code" in page_content.lower() or "token" in page_content.lower():
            logger.info("【登录】检测到需要输入验证码")
            
            # 获取验证码
            logger.info("【验证码获取】开始获取验证码邮件...")
            code = None
            retry_count = 0
            max_retries = 5
            
            # 登录时需要使用配置的临时邮箱接收验证码，而不是登录邮箱本身
            temp_email = os.getenv("TEMPMAIL_PLUS_EMAIL", "uhbedk@mailto.plus").strip()
            
            while not code and retry_count < max_retries:
                try:
                    # 使用 TempMail.Plus 获取验证码
                    code = await get_tempmail_plus_confirmation_code(temp_email)
                    
                    if code:
                        logger.info(f"【验证码获取】成功获取验证码: {code}")
                        break
                    else:
                        retry_count += 1
                        logger.warning(f"【验证码获取】未找到验证码，第{retry_count}次重试...")
                        await asyncio.sleep(5)
                except Exception as e:
                    retry_count += 1
                    logger.error(f"【验证码获取】获取验证码出错: {e}，第{retry_count}次重试...")
                    await asyncio.sleep(5)
            
            # 确保验证码成功获取
            if not code:
                logger.error("【登录中断】多次尝试后仍未能获取验证码，无法继续登录流程")
                await browser.stop()
                return None
            
            # 等待验证码输入框出现
            code_input_box = None
            input_retry_count = 0
            max_input_retries = 10
            
            logger.warning("【登录】等待验证码输入框出现...")
            while not code_input_box and input_retry_count < max_input_retries:
                try:
                    code_input_box = await tab.select("input[name='code']", timeout=1)
                    if code_input_box:
                        logger.info("【验证码输入】找到验证码输入框")
                    else:
                        input_retry_count += 1
                        logger.warning(f"【验证码输入】未找到验证码输入框，第{input_retry_count}次重试...")
                        await asyncio.sleep(1)
                except Exception:
                    input_retry_count += 1
                    logger.warning(f"【验证码输入】查找验证码输入框失败，第{input_retry_count}次重试...")
                    await asyncio.sleep(1)
            
            if not code_input_box:
                logger.error("【登录中断】未能找到验证码输入框，无法继续登录流程")
                await browser.stop()
                return None
            
            # 输入验证码
            logger.info(f"【验证码输入】准备输入验证码: {code}")
            await code_input_box.send_keys(code)
            
            # 提交验证码
            try:
                submit_button = await tab.select("button[type='submit']")
                await submit_button.click()
                logger.info("【验证码】已提交验证码")
                
                # 等待验证完成
                await tab.wait(5)
            except Exception as e:
                logger.error(f"【登录失败】提交验证码失败: {e}")
                return None
        
    except Exception as error_check:
        logger.debug(f"【登录调试】检查页面状态失败: {error_check}")
    
    # 获取Cookie
    logger.info("【登录】获取Session Token...")
    cookies = await browser.cookies.get_all()

    session_token = None
    for cookie in cookies:
        if cookie.name == "WorkosCursorSessionToken" and cookie.value:
            session_token = f"WorkosCursorSessionToken={cookie.value}"
            logger.info(f"【登录成功】获取到WorkosCursorSessionToken")
            break

    if not session_token:
        logger.error("【登录失败】未能获取到WorkosCursorSessionToken")
        return None

    # 登录成功后，执行和注册一样的后续流程
    logger.info("【登录后续】开始执行登录后续流程...")

    # 使用短期session token获取长期有效令牌
    logger.info("【令牌获取】开始获取长期有效令牌...")
    long_term_tokens = await get_long_term_tokens(browser, session_token)

    # 访问Dashboard页面并获取试用信息
    logger.info("【Dashboard页面】准备访问用户Dashboard页面...")
    await asyncio.sleep(5)  # 等待授权完全完成

    dashboard_success = await visit_dashboard_page(browser, session_token)
    if dashboard_success:
        logger.info("【Dashboard页面】Dashboard页面访问成功，登录流程完成")
    else:
        logger.warning("【Dashboard页面】Dashboard页面访问失败，继续后续流程")

    # 获取试用信息、使用量信息和用户ID
    trial_info = get_trial_info(session_token)
    usage_info = get_usage_info(session_token)
    user_id = extract_user_id(session_token)

    # 构建完整的登录结果
    login_result = {
        "email": email,
        "session_token": session_token,
        "long_term_tokens": long_term_tokens,
        "trial_info": trial_info,
        "usage_info": usage_info,
        "user_id": user_id
    }

    logger.info(f"【登录完成】邮箱: {email}")
    logger.info(f"【登录完成】用户ID: {user_id}")
    if trial_info:
        logger.info(f"【登录完成】试用信息: {trial_info}")
    if usage_info:
        logger.info(f"【登录完成】使用量: {usage_info}")

    return login_result


def exit_with_confirmation(exit_code: int = 1):
    input("Press enter to exit...")
    exit(exit_code)
    

async def main():
    logger.info("Starting...")

    # Check for admin rights at startup
    if not request_admin_elevation():
        exit(0)

    # 读取配置环境变量
    browser_path = os.getenv("BROWSER_PATH", None)
    no_sandbox = os.getenv("NO_SANDBOX", "false").lower() == "true"
    domain = os.getenv("DOMAIN", "example.com")
    temp_email = os.getenv("TEMPMAIL_PLUS_EMAIL", "uhbedk@mailto.plus").strip()
    no_install = os.getenv("NO_INSTALL", "false").lower() == "true"
    visit_settings = os.getenv("VISIT_SETTINGS", "true").lower() == "true"

    try:
        browser = await zd.start(
            lang="en_US",
            headless=False,
            browser_executable_path=browser_path,
            no_sandbox=no_sandbox
        )
    except Exception as error:
        logger.exception(error)
        logger.critical("Failed to start the browser.")
        exit_with_confirmation()

    # 生成用于注册的邮箱地址（使用域名）
    email = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(4, 8))) + "@" + domain
    logger.info(f"Generated registration email: {email}")

    # 获取用于接收验证码的临时邮箱
    logger.info(f"Using TempMail.Plus email for verification: {temp_email}")

    signup_result = await sign_up(browser, email, temp_email)
    if not signup_result:
        logger.error("【注册失败】注册过程失败")
        logger.error("【最可能原因】邮箱域名被 Cursor 加入黑名单")
        exit_with_confirmation()

    session_token, password = signup_result
    logger.info(f"【注册成功】邮箱: {email}")
    logger.info(f"【注册成功】密码: {password}")

    # 使用短期session token获取长期有效令牌
    logger.info("【令牌获取】开始获取长期有效令牌...")
    long_term_tokens = await get_long_term_tokens(browser, session_token)

    # 访问Dashboard页面并获取试用信息
    logger.info("【Dashboard页面】准备访问用户Dashboard页面...")

    # 在访问Dashboard前等待一段时间，确保授权完全完成
    logger.info("【Dashboard页面】等待授权完全完成后再访问Dashboard...")
    await asyncio.sleep(5)  # 额外等待5秒确保授权完成

    logger.info("【Dashboard页面】开始访问用户Dashboard页面...")
    dashboard_success = await visit_dashboard_page(browser, session_token)
    if dashboard_success:
        logger.info("【Dashboard页面】Dashboard页面访问成功，注册流程完成")
    else:
        logger.warning("【Dashboard页面】Dashboard页面访问失败，继续后续流程")

    # 获取试用信息、使用量信息和用户ID
    trial_info = get_trial_info(session_token)
    usage_info = get_usage_info(session_token)
    user_id = extract_user_id(session_token)

    await browser.stop()

    if long_term_tokens:
        access_token, refresh_token = long_term_tokens
        logger.info("【令牌获取】成功获取长期令牌")

        # 使用长期令牌构建新的cookie并验证有效期
        long_term_token = access_token or refresh_token
        logger.info("【JWT验证】开始验证长期令牌有效期...")

        # 验证JWT令牌有效期
        jwt_verification = verify_jwt_expiry(long_term_token)

        if jwt_verification.get("valid") and jwt_verification.get("is_long_term"):
            # JWT验证通过，构建长期cookie
            remaining_days = jwt_verification.get("remaining_days", 0)
            logger.info(f"【JWT验证】✅ 长期令牌验证通过，剩余有效期: {remaining_days}天")

            long_term_cookie = build_long_term_cookie(user_id, long_term_token)

            if long_term_cookie:
                logger.info("【长期Cookie】✅ 成功构建长期有效cookie")

                # 先保存基本账户信息
                save_account_info(email, password, session_token, access_token, refresh_token, trial_info, usage_info, user_id, long_term_cookie)

                # 更新账户文件中的Cookie部分
                update_success = update_account_cookie(email, long_term_cookie)
                if update_success:
                    logger.info("【Cookie更新】✅ 账户文件中的Cookie已更新为长期有效版本")
                else:
                    logger.warning("【Cookie更新】❌ 更新账户文件中的Cookie失败")
            else:
                logger.warning("【长期Cookie】构建失败，将使用原始session token")
                long_term_cookie = session_token
                save_account_info(email, password, session_token, access_token, refresh_token, trial_info, usage_info, user_id, long_term_cookie)
        else:
            # JWT验证失败，使用原始session token
            error_msg = jwt_verification.get("error", "Unknown error")
            remaining_days = jwt_verification.get("remaining_days", 0)
            logger.warning(f"【JWT验证】❌ 长期令牌验证失败: {error_msg}")
            logger.warning(f"【JWT验证】剩余有效期仅: {remaining_days}天，不足30天，pass掉")

            long_term_cookie = session_token
            save_account_info(email, password, session_token, access_token, refresh_token, trial_info, usage_info, user_id, long_term_cookie)

        # 使用长期令牌进行后续操作
        final_token = long_term_token
        logger.info(f"【令牌获取】将使用长期令牌进行数据库更新: {final_token[:15]}...")
    else:
        logger.warning("【令牌获取】未能获取长期令牌，将使用短期session token")

        # 保存基本的账户信息（没有长期cookie）
        save_account_info(email, password, session_token, trial_info=trial_info, usage_info=usage_info, user_id=user_id, long_term_cookie=None)

        # 从 session_token 中提取实际的令牌值
        if session_token.startswith("WorkosCursorSessionToken="):
            final_token = session_token.split("=", 1)[1]
        else:
            final_token = session_token

    if no_install:
        logger.info("NO_INSTALL mode: Skipping database update and machine ID reset")
        logger.info("Generated session token is: " + str(session_token))
        if long_term_tokens:
            logger.info("Long-term access token: " + str(access_token))
            logger.info("Long-term refresh token: " + str(refresh_token))
        logger.info("Final token for database: " + str(final_token))
        exit_with_confirmation(0)

    logger.info("Updating the local Cursor database...")
    success = await update_auth(email, final_token, final_token)
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


async def login_with_email(browser: Browser, email: str) -> Optional[dict]:
    """
    使用邮箱登录到 Cursor 账户（验证码方式）

    Args:
        browser: 浏览器实例
        email: 要登录的邮箱地址

    Returns:
        登录成功时返回完整的账户信息字典，失败时返回 None
    """
    logger.info(f"【邮箱登录】开始登录邮箱: {email}")

    # 调用登录函数
    login_result = await sign_in(browser, email)

    if login_result:
        logger.info("【邮箱登录】登录成功！")

        # 保存登录账户信息（可选）
        session_token = login_result["session_token"]
        long_term_tokens = login_result["long_term_tokens"]
        trial_info = login_result["trial_info"]
        usage_info = login_result["usage_info"]
        user_id = login_result["user_id"]

        # 如果有长期令牌，构建长期cookie
        long_term_cookie = None
        if long_term_tokens:
            access_token, refresh_token = long_term_tokens
            long_term_token = access_token or refresh_token

            # 验证JWT令牌有效期
            jwt_verification = verify_jwt_expiry(long_term_token)
            if jwt_verification.get("valid") and jwt_verification.get("is_long_term"):
                long_term_cookie = build_long_term_cookie(user_id, long_term_token)
                logger.info("【邮箱登录】✅ 成功构建长期有效cookie")

        # 保存账户信息（登录时密码为空）
        save_account_info(
            email=email,
            password="",  # 登录时没有密码
            session_token=session_token,
            access_token=long_term_tokens[0] if long_term_tokens else None,
            refresh_token=long_term_tokens[1] if long_term_tokens else None,
            trial_info=trial_info,
            usage_info=usage_info,
            user_id=user_id,
            long_term_cookie=long_term_cookie
        )

        return login_result
    else:
        logger.error(f"【邮箱登录】登录失败: {email}")
        return None





if __name__ == "__main__":
    asyncio.run(main())