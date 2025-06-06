import os
import sqlite3
import sys
import time
import psutil
from loguru import logger


def get_db_path():
    """根据操作系统获取 Cursor 数据库路径"""

    if sys.platform == "win32":  # Windows 系统
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise EnvironmentError("APPDATA environment variable is not set")
        return os.path.join(appdata, "Cursor", "User", "globalStorage", "state.vscdb")

    elif sys.platform == "darwin":  # macOS 系统
        return os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")

    elif sys.platform == "linux":  # Linux 系统
        return os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")

    else:
        raise NotImplementedError(f"Unsupported operating system: {sys.platform}")


def gracefully_exit_cursor(timeout: int = 5) -> bool:
    """
    优雅地终止 Cursor 进程（带超时机制）

    Args:
        timeout (int): 等待进程自然终止的时间（秒）
    Returns:
        bool: 如果所有进程都成功终止则返回 True
    """
    try:
        logger.info("开始终止 Cursor 进程...")
        cursor_processes = []

        # 收集所有 Cursor 进程
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'].lower() in ['cursor.exe', 'cursor']:
                    cursor_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not cursor_processes:
            logger.info("未发现运行中的 Cursor 进程")
            return True

        # 优雅地请求进程终止
        for proc in cursor_processes:
            try:
                if proc.is_running():
                    proc.terminate()  # 发送终止信号
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 等待进程自然终止
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
                logger.info("所有 Cursor 进程已成功终止")
                return True

            time.sleep(0.5)  # 检查间隔的小延迟

        # 如果超时后进程仍在运行
        if still_running := [str(p.pid) for p in still_running]:
            logger.warning(f"以下进程在超时时间内未能终止: {', '.join(still_running)}")
            return False

        return True

    except Exception as e:
        logger.error(f"终止 Cursor 进程时发生错误: {e}")
        return False


async def update_auth(email: str, access_token: str, refresh_token: str) -> bool:
    """
    更新 Cursor 数据库中的认证信息

    :param email: 新的邮箱地址
    :param access_token: 新的访问令牌
    :param refresh_token: 新的刷新令牌
    :return: bool - 更新成功返回 True，否则返回 False
    """
    # 首先，优雅地终止所有运行中的 Cursor 实例
    if not gracefully_exit_cursor():
        logger.warning("无法优雅地终止所有 Cursor 进程")
        # 继续执行，因为我们仍可能能够更新数据库

    db_path = get_db_path()

    updates = {
        "cursorAuth/cachedSignUpType": "Auth_0",  # 始终更新注册类型
        "cursorAuth/stripeMembershipType": "free_trial"  # 设置会员类型为免费试用
    }

    # 将提供的值添加到更新字典中
    if email is not None:
        updates["cursorAuth/cachedEmail"] = email
    if access_token is not None:
        updates["cursorAuth/accessToken"] = access_token
    if refresh_token is not None:
        updates["cursorAuth/refreshToken"] = refresh_token

    if not updates:
        logger.warning("未提供任何更新值")
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            for key, value in updates.items():
                # 检查键是否存在
                cursor.execute("SELECT COUNT(*) FROM itemTable WHERE key = ?", (key,))
                exists = cursor.fetchone()[0] > 0

                if exists:
                    # 更新现有记录
                    cursor.execute("UPDATE itemTable SET value = ? WHERE key = ?", (value, key))
                    logger.debug(f"已更新: {key.split('/')[-1]}")
                else:
                    # 插入新记录
                    cursor.execute("INSERT INTO itemTable (key, value) VALUES (?, ?)", (key, value))
                    logger.debug(f"已插入: {key.split('/')[-1]}")

            conn.commit()  # 提交所有更改
            return True

    except sqlite3.Error as e:
        logger.error(f"数据库错误: {e}")
    except Exception as e:
        logger.error(f"意外错误: {e}")

    return False