import time
import os
import re
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import traceback
import pymysql
import requests
from functools import wraps
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import sys
from io import StringIO

class CNKISpider:
    def __init__(self, driver_path="chromedriver.exe", headless=False, log_level=logging.INFO):
        """初始化爬虫"""
        self.driver_path = driver_path
        self.headless = headless
        self.driver = None
        self.conn = None  # MySQL 连接
        self.current_theme = ""  # 当前检索词（可选存入数据库）
        self.setup_logging(log_level)
        self.setup_driver()
        self.setup_db()
    
    def setup_logging(self, log_level=logging.INFO):
        """配置日志系统"""
        # 创建logs目录
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        # 日志文件名包含时间戳
        log_filename = os.path.join(log_dir, f"cnki_spider_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        # 配置日志格式
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        date_format = '%Y-%m-%d %H:%M:%S'
        
        # 配置日志：文件记录所有级别，控制台只显示关键信息
        logging.basicConfig(
            level=logging.DEBUG,
            format=log_format,
            datefmt=date_format,
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler()  # 控制台输出
            ]
        )
        
        # 设置控制台日志级别为WARNING，只显示警告和错误
        console_handler = logging.getLogger().handlers[1]
        console_handler.setLevel(logging.WARNING)
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"日志系统初始化完成，日志文件: {log_filename}")
    
    def log_info(self, message):
        """记录信息日志（仅写入文件）"""
        self.logger.info(message)
    
    def log_warning(self, message):
        """记录警告日志（文件+控制台）"""
        self.logger.warning(message)
    
    def log_error(self, message, exc_info=False):
        """记录错误日志（文件+控制台）"""
        self.logger.error(message, exc_info=exc_info)
    
    def log_debug(self, message):
        """记录调试日志（仅写入文件）"""
        self.logger.debug(message)
    
    @staticmethod
    def retry_on_exception(max_retries=3, delay=2, exceptions=(Exception,)):
        """装饰器：在异常时重试"""
        def decorator(func):
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                for attempt in range(max_retries):
                    try:
                        return func(self, *args, **kwargs)
                    except exceptions as e:
                        if attempt < max_retries - 1:
                            self.log_warning(f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}，{delay}秒后重试...")
                            time.sleep(delay)
                        else:
                            self.log_error(f"{func.__name__} 失败，已重试 {max_retries} 次: {str(e)}", exc_info=True)
                            raise
                return None
            return wrapper
        return decorator
        
    def setup_driver(self):
        """设置并返回WebDriver实例"""
        try:
            if not os.path.exists(self.driver_path):
                raise FileNotFoundError(f"ChromeDriver未找到: {self.driver_path}")
            
            service = Service(self.driver_path)
            options = webdriver.ChromeOptions()
            options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
            
            if self.headless:
                options.add_argument('--headless')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            
            # 添加更多稳定性选项
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # 增加页面加载稳定性
            options.add_argument('--disable-web-security')
            options.add_argument('--allow-running-insecure-content')
            options.add_argument('--disable-extensions')
            options.add_argument('--no-first-run')
            options.add_argument('--disable-default-apps')
            
            # 设置页面加载策略
            options.page_load_strategy = 'normal'  # 等待所有资源加载完成
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.maximize_window()  # 最大化窗口以确保元素可见
            
            # 设置隐式等待
            self.driver.implicitly_wait(5)
            
            # 设置页面加载超时
            self.driver.set_page_load_timeout(30)
            
            self.log_info("WebDriver初始化成功")
            
        except Exception as e:
            self.log_error(f"WebDriver初始化失败: {str(e)}", exc_info=True)
            raise
    
    def wait_for_page_load(self, timeout=10):
        """等待页面完全加载"""
        try:
            # 等待document.readyState为complete
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            # 额外等待jQuery加载完成（如果页面使用jQuery）
            try:
                WebDriverWait(self.driver, 2).until(
                    lambda d: d.execute_script("return typeof jQuery !== 'undefined' ? jQuery.active === 0 : true")
                )
            except TimeoutException:
                pass  # 如果没有jQuery，忽略
            time.sleep(0.5)  # 额外等待确保动态内容加载
            return True
        except TimeoutException:
            self.log_warning("页面加载超时")
            return False
    
    def wait_for_element(self, by, value, timeout=10, element_name="", retry_count=3):
        """等待元素出现，并处理超时情况，支持重试"""
        for attempt in range(retry_count):
            try:
                # 先确保页面加载完成
                if attempt > 0:
                    self.wait_for_page_load(timeout=5)
                    time.sleep(1)  # 增加重试间隔
                
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                self.log_debug(f"成功找到元素: {element_name if element_name else value}")
                return element
            except TimeoutException:
                if attempt < retry_count - 1:
                    self.log_debug(f"等待元素超时，重试中 ({attempt + 1}/{retry_count})...")
                    time.sleep(2)  # 增加重试间隔
                    continue
                error_msg = f"等待元素超时 ({element_name if element_name else value})"
                self.log_warning(error_msg)
                try:
                    self.log_debug(f"当前URL: {self.driver.current_url}")
                    self.log_debug(f"页面标题: {self.driver.title}")
                except Exception:
                    pass
                return None
            except Exception as e:
                self.log_warning(f"等待元素时发生异常: {str(e)}")
                if attempt < retry_count - 1:
                    time.sleep(2)
                    continue
                return None
    
    def wait_for_elements(self, by, value, timeout=10, element_name="", min_count=1):
        """等待多个元素出现"""
        try:
            # 先等待页面加载
            self.wait_for_page_load(timeout=5)
            
            elements = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_all_elements_located((by, value))
            )
            
            if len(elements) >= min_count:
                self.log_debug(f"成功找到 {len(elements)} 个元素: {element_name if element_name else value}")
                return elements
            else:
                self.log_warning(f"找到的元素数量不足: {len(elements)} < {min_count}")
                return elements if elements else []
        except TimeoutException:
            # 超时后尝试直接查找，可能元素已经存在但等待条件未满足
            try:
                elements = self.driver.find_elements(by, value)
                if elements:
                    self.log_info(f"超时后直接查找找到 {len(elements)} 个元素")
                    return elements
            except Exception:
                pass
            self.log_warning(f"等待元素超时 ({element_name if element_name else value})")
            return []
    
    def wait_for_element_clickable(self, by, value, timeout=8, element_name=""):
        """等待元素可点击"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            self.log_debug(f"元素可点击: {element_name if element_name else value}")
            return element
        except TimeoutException:
            self.log_warning(f"等待元素可点击超时 ({element_name if element_name else value})")
            return None
    
    def setup_db(self):
        """初始化 MySQL 连接并创建数据库/数据表"""
        try:
            # 数据库配置（可以从环境变量或配置文件读取）
            db_config = {
                "host": os.getenv("DB_HOST", "localhost"),
                "port": int(os.getenv("DB_PORT", "3306")),
                "user": os.getenv("DB_USER", "root"),
                "password": os.getenv("DB_PASSWORD", "123456"),
                "charset": "utf8mb4"
            }
            
            # 第一步：不指定数据库连接，仅用于创建数据库
            tmp_conn = pymysql.connect(**db_config, autocommit=True)

            with tmp_conn.cursor() as cursor:
                # 创建数据库（如果不存在）
                cursor.execute(
                    "CREATE DATABASE IF NOT EXISTS cnki "
                    "DEFAULT CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci"
                )
            
            tmp_conn.close()

            # 第二步：重新连接，并直接使用 cnki 数据库
            self.conn = pymysql.connect(**db_config, db="cnki", autocommit=True)

            with self.conn.cursor() as cursor:
                # 重新创建数据表，以适配当前字段（如已存在则先删除）
                cursor.execute("DROP TABLE IF EXISTS mycnki;")
                cursor.execute(
                    """
                    CREATE TABLE mycnki (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        title VARCHAR(500) NOT NULL,
                        authors VARCHAR(500),
                        pub_date VARCHAR(50),
                        page INT,
                        -- 存储下载得到的 CAJ/PDF 等文件在本地的相对路径或文件名
                        file_name VARCHAR(500),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                    """
                )

            self.log_info("MySQL 数据库和数据表已准备就绪（cnki.mycnki）")

        except Exception as e:
            self.log_warning(f"初始化 MySQL 数据库失败: {str(e)}，将继续运行但不保存到数据库")
            self.log_debug(traceback.format_exc())
            # 不抛出，让爬虫仍可运行，只是不写入数据库
            self.conn = None

    def save_to_mysql(self, papers):
        """将元数据批量写入 MySQL（cnki.mycnki）

        这里只保存题目/作者/时间/页码，不再保存 download_url；
        实际文件数据在下载成功后通过 UPDATE 写入 file_data 字段。
        """
        if not papers:
            self.log_debug("没有数据需要写入 MySQL")
            return

        if not self.conn:
            self.log_debug("未连接 MySQL，跳过写入")
            return

        try:
            with self.conn.cursor() as cursor:
                sql = (
                    "INSERT INTO mycnki (title, authors, pub_date, page) "
                    "VALUES (%s, %s, %s, %s)"
                )
                data = []
                for p in papers:
                    data.append((
                        p.get("title", ""),
                        p.get("authors", ""),
                        p.get("date", ""),
                        p.get("page", None),
                    ))

                cursor.executemany(sql, data)

            # 再次确保提交（即使 autocommit=True，安全起见）
            try:
                self.conn.commit()
            except Exception:
                pass

            self.log_info(f"已写入 MySQL 表 mycnki 共 {len(papers)} 条记录")
            print(f"✓ 已保存 {len(papers)} 条记录到数据库")

        except Exception as e:
            self.log_error(f"写入 MySQL 失败: {str(e)}", exc_info=True)

    # ================= PDF 下载相关 =================

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名中 Windows 不允许的字符"""
        if not name:
            return "unnamed"
        # 去除非法字符 \ / : * ? " < > | 以及控制字符
        name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name)
        name = name.strip(" .")  # 去掉首尾空格和点
        if not name:
            return "unnamed"
        # 限制长度，避免路径过长
        return name[:100]

    def _get_requests_session_from_driver(self) -> requests.Session:
        """使用当前 Selenium 会话的 Cookie 构造 requests.Session，用于直接下载"""
        session = requests.Session()

        # 同步 Cookie
        try:
            for c in self.driver.get_cookies():
                session.cookies.set(c["name"], c["value"])
        except Exception as e:
            self.log_warning(f"同步 Selenium Cookie 失败: {e}")

        # 使用浏览器的 User-Agent
        try:
            ua = self.driver.execute_script("return navigator.userAgent;")
            session.headers.update({"User-Agent": ua})
        except Exception:
            pass

        return session

    def download_papers(self, papers, folder: str = "mypdf"):
        """
        根据 papers 中的 download_url 批量下载文献（PDF 或 CAJ 等），
        使用 Selenium 会话 Cookie + Referer，保存为 论文题目.扩展名 到指定文件夹。
        """
        if not papers:
            self.log_debug("没有可下载的论文记录，跳过 PDF 下载")
            return

        os.makedirs(folder, exist_ok=True)
        session = self._get_requests_session_from_driver()

        # 尝试使用当前页面作为 Referer（一般是检索结果页）
        try:
            referer = self.driver.current_url
        except Exception:
            referer = "https://www.cnki.net"

        total = len(papers)
        print(f"开始下载文件，共 {total} 篇...")
        self.log_info(f"开始批量下载 PDF，共 {total} 篇（保存路径: {os.path.abspath(folder)}）")

        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, p in enumerate(papers, start=1):
            url = p.get("download_url") or ""
            title = p.get("title") or ""

            if not url:
                self.log_debug(f"[{idx}/{total}] 《{title}》 无下载链接，跳过")
                skip_count += 1
                continue

            safe_name = self._sanitize_filename(title)
            self.log_debug(f"[{idx}/{total}] 正在下载：《{title}》")

            try:
                headers = {
                    "Referer": referer,  # 关键：带上来源页面
                }
                # 使用 stream 避免一次性加载大文件
                resp = session.get(url, headers=headers, stream=True, timeout=60)

                if resp.status_code != 200:
                    self.log_warning(f"[{idx}/{total}] 下载失败，HTTP {resp.status_code}: {title}")
                    error_count += 1
                    continue

                # 先读出第一个块，用于判断是否真的是 PDF
                first_chunk = None
                try:
                    for first_chunk in resp.iter_content(chunk_size=8 * 1024):
                        if first_chunk:
                            break
                except Exception as e:
                    self.log_warning(f"[{idx}/{total}] 读取数据出错: {e}")
                    error_count += 1
                    continue

                if not first_chunk:
                    self.log_warning(f"[{idx}/{total}] 文件内容为空: {title}")
                    error_count += 1
                    continue

                # 判断文件类型：PDF 通常以 %PDF 开头；否则按 CAJ 等二进制保存
                if first_chunk.startswith(b"%PDF"):
                    ext = ".pdf"
                else:
                    # 尝试按文本解码一小部分，若明显是 HTML 错误页则跳过
                    try:
                        snippet = first_chunk[:200].decode("utf-8", errors="ignore")
                    except Exception:
                        snippet = ""
                    if "来源应用不正确" in snippet or "<html" in snippet.lower():
                        self.log_warning(f"[{idx}/{total}] 检测到错误页面，已跳过: {title}")
                        error_count += 1
                        continue
                    # 否则按 CAJ（或其他二进制格式）保存
                    ext = ".caj"

                file_name = f"{safe_name}{ext}"
                file_path = os.path.join(folder, file_name)

                if os.path.exists(file_path):
                    self.log_debug(f"[{idx}/{total}] 文件已存在，跳过下载: {file_path}")
                    skip_count += 1
                else:
                    # 将第一个块和后续数据写入文件（使用临时文件，确保原子性）
                    temp_file_path = file_path + ".tmp"
                    try:
                        with open(temp_file_path, "wb") as f:
                            f.write(first_chunk)
                            for chunk in resp.iter_content(chunk_size=64 * 1024):
                                if chunk:
                                    f.write(chunk)
                        # 下载完成后重命名为正式文件
                        if os.path.exists(temp_file_path):
                            if os.path.exists(file_path):
                                os.remove(file_path)
                            os.rename(temp_file_path, file_path)
                    except Exception as e:
                        # 清理临时文件
                        if os.path.exists(temp_file_path):
                            try:
                                os.remove(temp_file_path)
                            except Exception:
                                pass
                        raise e

                    self.log_info(f"[{idx}/{total}] 下载完成: {file_path}")
                    success_count += 1
                    
                    # 显示进度
                    if idx % 10 == 0 or idx == total:
                        print(f"  进度: {idx}/{total} (成功: {success_count}, 跳过: {skip_count}, 失败: {error_count})")

                # 在 MySQL 中记录文件名（按 title + pub_date 匹配一条记录）
                if self.conn:
                    try:
                        with self.conn.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE mycnki
                                SET file_name = %s
                                WHERE title = %s AND pub_date = %s AND (file_name IS NULL)
                                LIMIT 1
                                """,
                                (file_name, title, p.get("date", ""))
                            )
                        try:
                            self.conn.commit()
                        except Exception:
                            pass
                        self.log_debug(f"已在 MySQL 中记录文件名: {file_name}")
                    except Exception as e:
                        self.log_warning(f"写入 MySQL 文件名失败: {e}")

            except Exception as e:
                self.log_error(f"[{idx}/{total}] 下载出错: {e}", exc_info=True)
                error_count += 1
                continue
        
        print(f"✓ 下载完成: 成功 {success_count}, 跳过 {skip_count}, 失败 {error_count}")
        self.log_info(f"下载统计: 成功 {success_count}, 跳过 {skip_count}, 失败 {error_count}")

    def verify_search_result_page(self):
        """验证是否在搜索结果页面"""
        try:
            current_url = self.driver.current_url
            # 检查URL是否包含搜索结果相关关键词
            if "defaultresult" in current_url.lower() or "search" in current_url.lower() or "result" in current_url.lower():
                # 检查页面是否包含论文列表的常见元素
                possible_indicators = [
                    (By.CLASS_NAME, "fz14"),
                    (By.CSS_SELECTOR, "table.result"),
                    (By.ID, "GridTableContent"),
                    (By.CLASS_NAME, "result-list"),
                    (By.CSS_SELECTOR, ".brief"),
                ]
                
                for by, value in possible_indicators:
                    try:
                        elements = self.driver.find_elements(by, value)
                        if elements:
                            self.log_debug(f"验证成功：找到搜索结果页面指示元素 {value}")
                            return True
                    except Exception:
                        continue
                
                self.log_warning("URL看起来是搜索结果页，但未找到论文列表元素")
                return False
            else:
                self.log_warning(f"当前URL不像是搜索结果页: {current_url}")
                return False
        except Exception as e:
            self.log_warning(f"验证搜索结果页面时出错: {str(e)}")
            return False
    
    def extract_papers_from_current_page(self, current_page):
        """从当前页面提取论文标题 + 作者（a.KnowledgeNetLink）+ 时间（td.date）"""
        papers = []
        
        # 先验证是否在搜索结果页面
        if not self.verify_search_result_page():
            self.log_warning("页面验证失败，可能不在搜索结果页面")
            # 继续尝试提取，可能页面结构不同
        
        # 等待页面加载完成
        self.wait_for_page_load(timeout=5)
        time.sleep(1)  # 额外等待确保动态内容加载
        
        # 获取论文标题元素，使用更长的超时时间
        title_elements = self.wait_for_elements(By.CLASS_NAME, "fz14", timeout=15, element_name="论文标题", min_count=1)
        
        if not title_elements:
            self.log_warning("未找到任何论文标题元素，尝试查找其他可能的选择器...")
            
            # 尝试其他常见的选择器，按优先级排序
            alternative_selectors = [
                (By.CSS_SELECTOR, "a.fz14"),
                (By.CSS_SELECTOR, ".fz14 a"),
                (By.CSS_SELECTOR, "table.result a.fz14"),
                (By.CSS_SELECTOR, "#GridTableContent a.fz14"),
                (By.CSS_SELECTOR, ".article-title"),
                (By.CSS_SELECTOR, ".title"),
                (By.CSS_SELECTOR, ".title a"),
                (By.CSS_SELECTOR, "h3 a"),
                (By.CSS_SELECTOR, ".result-list .title"),
                (By.CSS_SELECTOR, "tr[onclick] a"),
                (By.CSS_SELECTOR, ".brief a"),
            ]
            
            for by, selector in alternative_selectors:
                try:
                    alt_elements = self.driver.find_elements(by, selector)
                    if alt_elements and len(alt_elements) > 0:
                        self.log_info(f"使用选择器 '{selector}' 找到了 {len(alt_elements)} 个元素")
                        title_elements = alt_elements
                        break
                except Exception as e:
                    self.log_debug(f"尝试选择器 {selector} 时出错: {str(e)}")
                    continue
        
        if not title_elements:
            self.log_error("所有选择器都未找到论文标题元素")
            return papers
        
        self.log_info(f"第{current_page}页找到 {len(title_elements)} 个论文标题元素")
        
        # 提取论文标题 + 作者 + 时间 + 下载链接（列表页 td.operat 中的 a.downloadlink）
        for i, title_element in enumerate(title_elements):
            try:
                # 1. 标题：仍然使用原来的逻辑
                title_text = title_element.text.strip()
                if not title_text:
                    href = title_element.get_attribute('textContent') or title_element.get_attribute('href')
                    title_text = (href or '').strip()

                # 默认作者、时间、下载链接为空，防止异常导致程序中断
                authors_text = ''
                date_text = ''
                download_url = ''

                # 2. 找到这一条记录所在的行（tr），再在这一行中找作者和时间
                #    作者在 <a class="KnowledgeNetLink"> 中
                #    时间在 <td class="date"> 中
                try:
                    # 1）在列表页所在行中获取作者与时间
                    row = title_element.find_element(By.XPATH, "./ancestor::tr[1]")
                    author_links = row.find_elements(By.CSS_SELECTOR, "a.KnowledgeNetLink")
                    if author_links:
                        authors_text = "；".join(a.text.strip() for a in author_links if a.text.strip())

                    try:
                        date_td = row.find_element(By.CSS_SELECTOR, "td.date")
                        date_text = date_td.text.strip()
                    except Exception:
                        date_text = ''
                except Exception:
                    # 某些结构可能不是表格行，忽略作者和时间
                    pass

                # 2）在当前列表页的同一行中，查找下载按钮（td.operat > a.downloadlink.icon-download）
                try:
                    operat_td = row.find_element(By.CSS_SELECTOR, "td.operat")
                    # 优先找 class 同时包含 downloadlink 和 icon-download 的 a
                    try:
                        download_a = operat_td.find_element(
                            By.CSS_SELECTOR, "a.downloadlink.icon-download"
                        )
                    except Exception:
                        # 退而求其次，只要含有 downloadlink 类的 a
                        download_a = operat_td.find_element(
                            By.CSS_SELECTOR, "a.downloadlink"
                        )
                    download_url = download_a.get_attribute("href") or ""
                except Exception:
                    download_url = ''

                if title_text:  # 确保标题不为空
                    papers.append({
                        'title': title_text,
                        'authors': authors_text,
                        'date': date_text,
                        'page': current_page,
                        'download_url': download_url
                    })
                    self.log_debug(f"第{current_page}页-{i+1}. 标题: {title_text} | 作者: {authors_text} | 时间: {date_text}")
            except Exception as e:
                self.log_warning(f"提取第{current_page}页第{i+1}个标题时出错: {str(e)}")
            continue
        
        return papers
    
    def go_to_next_page(self, current_page):
        """尝试翻到下一页"""
        try:
            # 查找下一页按钮
            next_button = self.wait_for_element_clickable(
                By.ID, "PageNext", 
                timeout=10, 
                element_name=f"第{current_page}页的下一页按钮"
            )
            
            if not next_button:
                self.log_info(f"未找到第{current_page}页的下一页按钮，已到最后一页")
                return False
            
            # 检查按钮是否可点击（没有禁用属性）
            if next_button.get_attribute("disabled"):
                self.log_info(f"第{current_page}页的下一页按钮被禁用，已到最后一页")
                return False
            
            # 点击下一页按钮（使用重试机制）
            self.log_debug(f"正在点击第{current_page}页的下一页按钮...")
            for click_attempt in range(3):
                try:
                    self.driver.execute_script("arguments[0].click();", next_button)
                    break
                except StaleElementReferenceException:
                    if click_attempt < 2:
                        self.log_debug(f"元素已过期，重新查找并重试...")
                        next_button = self.wait_for_element_clickable(
                            By.ID, "PageNext", timeout=5, element_name="下一页按钮（重试）"
                        )
                        if not next_button:
                            return False
                    else:
                        raise
            
            # 等待页面加载
            time.sleep(2)
            
            # 等待新页面内容加载
            self.wait_for_page_load(timeout=15)
            time.sleep(1)
            
            # 验证新页面是否加载成功
            if not self.verify_search_result_page():
                self.log_warning("翻页后页面验证失败，可能页面加载失败")
                # 尝试重新加载页面
                try:
                    self.driver.refresh()
                    self.wait_for_page_load(timeout=10)
                    time.sleep(2)
                    if self.verify_search_result_page():
                        self.log_info("刷新后页面验证成功")
                        return True
                except Exception as e:
                    self.log_warning(f"刷新页面失败: {str(e)}")
                return False
            
            self.log_info(f"成功翻到第{current_page + 1}页")
            return True
            
        except Exception as e:
            self.log_error(f"翻到第{current_page + 1}页时出错: {str(e)}", exc_info=True)
            return False
    
    def search_and_crawl(self, theme, papers_need=100, max_pages=None, download_pdf=True):
        """执行搜索和爬取操作，支持翻页

        :param theme: 检索词
        :param papers_need: 需要爬取的论文数量
        :param max_pages: 最大翻页数；为 None 时按需一直翻页直到爬够或无下一页
        """
        all_papers = []
        current_page = 1
        self.current_theme = theme
        
        try:
            # 1. 打开知网首页
            print("正在打开知网首页...")
            self.log_info("步骤1: 正在打开知网首页...")
            try:
                self.driver.get("https://www.cnki.net")
            except Exception as e:
                self.log_error(f"打开知网首页失败: {str(e)}")
                # 尝试重新加载
                try:
                    self.driver.refresh()
                except:
                    pass
            
            # 等待首页加载完成
            self.wait_for_page_load(timeout=15)
            time.sleep(2)  # 额外等待确保页面稳定
            
            # 2. 查找搜索框并输入关键词（增加重试）
            self.log_info("步骤2: 正在查找搜索框...")
            search_input = None
            
            # 尝试多个可能的搜索框选择器
            search_selectors = [
                (By.ID, "txt_SearchText"),
                (By.CSS_SELECTOR, "input#txt_SearchText"),
                (By.CSS_SELECTOR, "input[placeholder*='检索']"),
                (By.CSS_SELECTOR, "input[type='text'][name*='search']"),
                (By.CLASS_NAME, "search-input"),
            ]
            
            for by, value in search_selectors:
                search_input = self.wait_for_element(by, value, timeout=10, element_name="搜索输入框", retry_count=2)
                if search_input:
                    self.log_info(f"找到搜索框，使用选择器: {by}={value}")
                    break
            
            if not search_input:
                self.log_error("无法找到搜索输入框，可能页面加载失败")
                return all_papers
                
            # 输入关键词，使用重试机制
            for attempt in range(3):
                try:
                    search_input.clear()
                    time.sleep(0.3)
                    search_input.send_keys(theme)
                    time.sleep(0.5)  # 等待输入完成
                    self.log_info(f"已输入搜索关键词: {theme}")
                    break
                except StaleElementReferenceException:
                    if attempt < 2:
                        self.log_debug("搜索框元素过期，重新查找...")
                        search_input = self.wait_for_element(By.ID, "txt_SearchText", element_name="搜索输入框", retry_count=2)
                        if not search_input:
                            self.log_error("重新查找搜索框失败")
                            return all_papers
                    else:
                        self.log_error("输入关键词失败，元素不稳定")
                        return all_papers
                except Exception as e:
                    if attempt < 2:
                        self.log_warning(f"输入关键词时出错，重试: {str(e)}")
                        time.sleep(1)
                    else:
                        self.log_error(f"输入关键词失败: {str(e)}")
                        return all_papers
            
            # 3. 查找并点击搜索按钮（增加重试）
            self.log_info("步骤3: 正在查找搜索按钮...")
            search_button = None
            
            # 尝试多个可能的搜索按钮选择器
            button_selectors = [
                (By.CLASS_NAME, "search-btn"),
                (By.CSS_SELECTOR, "button.search-btn"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, ".search-button"),
                (By.XPATH, "//button[contains(text(), '检索')]"),
                (By.XPATH, "//input[@value='检索']"),
            ]
            
            for by, value in button_selectors:
                search_button = self.wait_for_element(by, value, timeout=10, element_name="搜索按钮", retry_count=2)
                if search_button:
                    self.log_info(f"找到搜索按钮，使用选择器: {by}={value}")
                    break
            
            if not search_button:
                # 如果找不到按钮，尝试按回车键
                self.log_info("未找到搜索按钮，尝试按回车键搜索...")
                try:
                    search_input.send_keys(Keys.RETURN)
                    self.log_info("已按回车键触发搜索")
                except Exception as e:
                    self.log_error(f"按回车键失败: {str(e)}")
                    return all_papers
            else:
                # 点击搜索按钮
                for attempt in range(3):
                    try:
                        # 先尝试普通点击
                        search_button.click()
                        self.log_info("已点击搜索按钮")
                        break
                    except Exception as e:
                        if attempt < 2:
                            self.log_debug(f"普通点击失败，尝试JavaScript点击: {str(e)}")
                            try:
                                self.driver.execute_script("arguments[0].click();", search_button)
                                self.log_info("已使用JavaScript点击搜索按钮")
                                break
                            except Exception:
                                # 重新查找按钮
                                search_button = self.wait_for_element(By.CLASS_NAME, "search-btn", timeout=5, element_name="搜索按钮")
                                if not search_button:
                                    # 尝试按回车键
                                    try:
                                        search_input.send_keys(Keys.RETURN)
                                        self.log_info("已按回车键触发搜索")
                                        break
                                    except:
                                        pass
                        else:
                            self.log_error("点击搜索按钮失败")
                            return all_papers
            
            # 等待页面跳转和加载
            print("等待搜索结果页面加载...")
            try:
                # 等待URL变化，表示页面已跳转
                WebDriverWait(self.driver, 20).until(
                    lambda d: "defaultresult" in d.current_url.lower() or 
                             "search" in d.current_url.lower() or 
                             "result" in d.current_url.lower() or
                             d.current_url != "https://www.cnki.net/"
                )
                self.log_info(f"页面已跳转到: {self.driver.current_url}")
            except TimeoutException:
                self.log_warning("页面跳转超时，但继续尝试...")
            
            # 等待页面完全加载
            self.wait_for_page_load(timeout=15)
            time.sleep(3)  # 额外等待确保搜索结果加载完成
            
            # 4. 循环爬取多页
            print(f"开始爬取，目标: {papers_need} 篇...")
            consecutive_failures = 0  # 连续失败计数
            max_consecutive_failures = 3  # 最大连续失败次数
            
            while len(all_papers) < papers_need and (max_pages is None or current_page <= max_pages):
                self.log_info(f"=== 开始爬取第{current_page}页 ===")
                
                # 等待页面加载
                self.wait_for_page_load(timeout=10)
                time.sleep(1)
                
                # 验证是否在搜索结果页面
                if not self.verify_search_result_page():
                    consecutive_failures += 1
                    self.log_warning(f"页面验证失败 (连续失败 {consecutive_failures}/{max_consecutive_failures})")
                    if consecutive_failures >= max_consecutive_failures:
                        self.log_error("连续多次页面验证失败，停止爬取")
                        break
                    time.sleep(3)  # 等待后重试
                    continue
                else:
                    consecutive_failures = 0  # 重置失败计数
                
                # 尝试多个可能的选择器来查找搜索结果区域（可选，主要用于日志）
                result_element = None
                possible_selectors = [
                    (By.CLASS_NAME, "result"),
                    (By.ID, "GridTableContent"),
                    (By.CLASS_NAME, "result-list"),
                    (By.CLASS_NAME, "search-result"),
                    (By.CSS_SELECTOR, ".result-list"),
                    (By.CSS_SELECTOR, "#GridTableContent"),
                    (By.CSS_SELECTOR, "table.result"),
                ]
                
                for by, value in possible_selectors:
                    try:
                        result_element = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((by, value))
                        )
                        self.log_info(f"找到搜索结果区域，使用选择器: {by}={value}")
                        break
                    except TimeoutException:
                        continue
                
                if not result_element:
                    # 诊断：输出当前页面信息
                    try:
                        current_url = self.driver.current_url
                        page_title = self.driver.title
                        page_source_length = len(self.driver.page_source)
                        self.log_warning(f"第{current_page}页未找到搜索结果区域")
                        self.log_warning(f"当前URL: {current_url}")
                        self.log_warning(f"页面标题: {page_title}")
                        self.log_warning(f"页面源码长度: {page_source_length}")
                        
                        # 尝试查找任何包含论文标题的元素
                        try:
                            test_elements = self.driver.find_elements(By.CLASS_NAME, "fz14")
                            if test_elements:
                                self.log_info(f"找到 {len(test_elements)} 个可能的标题元素，继续尝试提取...")
                                # 即使没有找到result区域，也尝试提取
                            else:
                                # 尝试其他可能的选择器
                                alt_selectors = [
                                    (By.CSS_SELECTOR, "a[title]"),
                                    (By.CSS_SELECTOR, ".brief"),
                                    (By.CSS_SELECTOR, "tr[onclick]"),
                                ]
                                found_any = False
                                for by, selector in alt_selectors:
                                    try:
                                        elements = self.driver.find_elements(by, selector)
                                        if elements:
                                            self.log_info(f"使用选择器 {selector} 找到 {len(elements)} 个元素")
                                            found_any = True
                                            break
                                    except Exception:
                                        continue
                                
                                if not found_any:
                                    self.log_error("页面可能未正确加载，建议检查网络连接或稍后重试")
                                    print("✗ 页面加载异常，请检查网络连接或稍后重试")
                                    break
                        except Exception as e:
                            self.log_error(f"查找标题元素时出错: {str(e)}")
                    except Exception as e:
                        self.log_error(f"诊断信息获取失败: {str(e)}")
                    
                    # 如果找不到结果区域，但找到了标题元素，继续尝试
                    title_elements = self.driver.find_elements(By.CLASS_NAME, "fz14")
                    if not title_elements:
                        # 最后尝试：等待更长时间后再次查找
                        self.log_info("等待页面完全加载后再次尝试...")
                        time.sleep(5)
                        title_elements = self.driver.find_elements(By.CLASS_NAME, "fz14")
                        if not title_elements:
                            self.log_warning(f"第{current_page}页未找到搜索结果区域和标题元素，可能页面加载失败")
                            print("✗ 无法找到搜索结果，请检查页面是否正常加载")
                            break
                
                # 提取当前页的论文（即使没有找到result区域也尝试提取）
                page_papers = self.extract_papers_from_current_page(current_page)
                if page_papers and len(page_papers) > 0:
                    all_papers.extend(page_papers)
                    consecutive_failures = 0  # 重置失败计数
                else:
                    consecutive_failures += 1
                    self.log_warning(f"第{current_page}页未提取到任何论文 (连续失败 {consecutive_failures}/{max_consecutive_failures})")
                    
                    # 尝试等待更长时间后重试
                    if consecutive_failures < max_consecutive_failures:
                        self.log_info("等待页面完全加载后重试...")
                        time.sleep(5)
                        self.wait_for_page_load(timeout=10)
                        page_papers = self.extract_papers_from_current_page(current_page)
                        if page_papers and len(page_papers) > 0:
                            all_papers.extend(page_papers)
                            consecutive_failures = 0
                            self.log_info(f"重试成功，提取到 {len(page_papers)} 篇论文")
                        else:
                            if consecutive_failures >= max_consecutive_failures:
                                self.log_error("连续多次提取失败，停止爬取")
                                break
                    else:
                        self.log_error("连续多次提取失败，停止爬取")
                        break
                
                print(f"  第{current_page}页: 获取 {len(page_papers)} 篇，累计 {len(all_papers)} 篇")
                self.log_info(f"第{current_page}页爬取完成，累计获取 {len(all_papers)} 篇论文")
                
                # 检查是否已达到所需数量
                if len(all_papers) >= papers_need:
                    self.log_info(f"已达到所需论文数量 {papers_need}，停止爬取")
                    break
                
                # 尝试翻到下一页
                if len(all_papers) < papers_need:
                    if not self.go_to_next_page(current_page):
                        self.log_info("无法翻到下一页，停止爬取")
                        break
                    current_page += 1
                    time.sleep(2)  # 翻页后等待
                else:
                    break
            
            # 如果获取的论文超过所需数量，进行截断
            if len(all_papers) > papers_need:
                all_papers = all_papers[:papers_need]
                self.log_info(f"已截断到所需数量 {papers_need}")
            
            # 5. 保存结果到 MySQL
            if all_papers:
                self.save_to_mysql(all_papers)

            # 6. 根据 download_url 批量下载文献（PDF/CAJ）
            if download_pdf and all_papers:
                self.download_papers(all_papers, folder="mypdf")
            
            return all_papers
            
        except Exception as e:
            self.log_error(f"搜索和爬取过程中发生错误: {str(e)}", exc_info=True)
            return all_papers
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            self.log_info("正在关闭浏览器...")
            try:
                self.driver.quit()
                self.log_info("浏览器已关闭")
            except Exception as e:
                self.log_error(f"关闭浏览器时出错: {str(e)}", exc_info=True)

        # 关闭 MySQL 连接
        if self.conn:
            self.log_info("正在关闭 MySQL 连接...")
            try:
                self.conn.close()
                self.log_info("MySQL 连接已关闭")
            except Exception as e:
                self.log_error(f"关闭 MySQL 连接时出错: {str(e)}", exc_info=True)

class TextRedirector:
    """重定向stdout到GUI的文本控件"""
    def __init__(self, text_widget, log_callback):
        self.text_widget = text_widget
        self.log_callback = log_callback
        self.buffer = StringIO()
    
    def write(self, message):
        if message.strip():
            self.log_callback(message.strip())
        self.buffer.write(message)
    
    def flush(self):
        pass

class CNKISpiderGUI:
    """爬虫图形界面"""
    def __init__(self, root):
        self.root = root
        self.root.title("中国知网论文爬虫")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # 爬虫实例
        self.spider = None
        self.is_running = False
        self.crawl_thread = None
        self.original_stdout = sys.stdout
        
        # 创建界面
        self.create_widgets()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="中国知网论文爬虫", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # 检索词输入
        ttk.Label(main_frame, text="检索词：", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.theme_entry = ttk.Entry(main_frame, width=40, font=("Arial", 10))
        self.theme_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.theme_entry.insert(0, "Python")
        
        # 论文数量输入
        ttk.Label(main_frame, text="论文数量：", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.papers_entry = ttk.Entry(main_frame, width=40, font=("Arial", 10))
        self.papers_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=5)
        self.papers_entry.insert(0, "100")
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=2, sticky=tk.W, padx=5)
        
        self.start_button = ttk.Button(button_frame, text="开始爬取", command=self.start_crawl, width=15)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_crawl, width=15, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # 进度条
        self.progress_var = tk.StringVar(value="等待开始...")
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_var, font=("Arial", 9))
        self.progress_label.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_bar.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # 日志输出区域
        ttk.Label(main_frame, text="运行日志：", font=("Arial", 10)).grid(row=5, column=0, sticky=tk.W, pady=(10, 5))
        
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, width=80, height=20, font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.log_text.config(state=tk.DISABLED)
        
        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
    
    def log_message(self, message, level="INFO"):
        """在日志区域显示消息"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 根据级别设置颜色
        if level == "ERROR":
            tag = "error"
            self.log_text.tag_config("error", foreground="red")
        elif level == "WARNING":
            tag = "warning"
            self.log_text.tag_config("warning", foreground="orange")
        elif level == "SUCCESS":
            tag = "success"
            self.log_text.tag_config("success", foreground="green")
        else:
            tag = "info"
        
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        # 更新状态栏
        self.status_var.set(message[:50] if len(message) > 50 else message)
    
    def start_crawl(self):
        """开始爬取"""
        if self.is_running:
            messagebox.showwarning("警告", "爬取任务正在运行中，请先停止当前任务")
            return
        
        # 获取输入
        theme = self.theme_entry.get().strip()
        if not theme:
            messagebox.showerror("错误", "请输入检索词")
            return
        
        try:
            papers_need = int(self.papers_entry.get().strip())
            if papers_need <= 0:
                raise ValueError("数量必须大于0")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的论文数量（正整数）")
            return
        
        # 禁用输入和开始按钮
        self.theme_entry.config(state=tk.DISABLED)
        self.papers_entry.config(state=tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        # 清空日志
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        # 启动进度条
        self.progress_bar.start(10)
        self.progress_var.set(f"正在爬取：{theme}，目标数量：{papers_need} 篇")
        self.is_running = True
        
        # 在新线程中运行爬虫
        self.crawl_thread = threading.Thread(target=self.run_crawl, args=(theme, papers_need), daemon=True)
        self.crawl_thread.start()
    
    def run_crawl(self, theme, papers_need):
        """执行爬取任务（在后台线程中运行）"""
        spider = None
        try:
            # 重定向stdout到GUI
            sys.stdout = TextRedirector(self.log_text, lambda msg: self.root.after(0, lambda: self.log_message(msg, "INFO")))
            
            self.log_message(f"开始初始化爬虫...", "INFO")
            spider = CNKISpider(headless=False)
            self.spider = spider
            
            # 重定向print输出到GUI
            self.log_message(f"检索词：{theme}", "INFO")
            self.log_message(f"目标数量：{papers_need} 篇", "INFO")
            self.log_message("=" * 50, "INFO")
            
            # 执行爬取
            papers = spider.search_and_crawl(theme, papers_need, max_pages=None, download_pdf=True)
            
            if papers:
                pages_count = len(set(p.get('page', 1) for p in papers))
                success_msg = f"✓ 爬取完成! 成功获取 {len(papers)} 篇论文，涉及 {pages_count} 页"
                self.log_message(success_msg, "SUCCESS")
                self.root.after(0, lambda: messagebox.showinfo("完成", success_msg))
            else:
                error_msg = "✗ 爬取失败，未获取到任何论文标题"
                self.log_message(error_msg, "WARNING")
                self.root.after(0, lambda: messagebox.showwarning("警告", error_msg))
            
        except KeyboardInterrupt:
            self.log_message("用户中断程序", "WARNING")
        except Exception as e:
            error_msg = f"程序执行过程中发生错误: {str(e)}"
            self.log_message(error_msg, "ERROR")
            self.log_message(traceback.format_exc(), "ERROR")
            self.root.after(0, lambda: messagebox.showerror("错误", error_msg))
        finally:
            # 恢复stdout
            sys.stdout = self.original_stdout
            
            # 确保关闭浏览器
            if spider:
                try:
                    spider.close()
                except:
                    pass
            self.spider = None
            
            # 恢复界面状态
            self.root.after(0, self.crawl_finished)
    
    def crawl_finished(self):
        """爬取完成后的界面恢复"""
        self.is_running = False
        self.progress_bar.stop()
        self.progress_var.set("爬取完成")
        self.theme_entry.config(state=tk.NORMAL)
        self.papers_entry.config(state=tk.NORMAL)
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("就绪")
    
    def stop_crawl(self):
        """停止爬取"""
        if not self.is_running:
            return
        
        if messagebox.askyesno("确认", "确定要停止当前爬取任务吗？"):
            self.is_running = False
            self.log_message("正在停止爬取任务...", "WARNING")
            
            # 关闭浏览器
            if self.spider and self.spider.driver:
                try:
                    self.spider.driver.quit()
                except:
                    pass
            
            self.crawl_finished()
            messagebox.showinfo("提示", "爬取任务已停止")
    
    def on_closing(self):
        """窗口关闭事件"""
        if self.is_running:
            if messagebox.askyesno("确认", "爬取任务正在运行，确定要退出吗？"):
                # 停止爬取
                if self.spider and self.spider.driver:
                    try:
                        self.spider.driver.quit()
                    except:
                        pass
                # 恢复stdout
                sys.stdout = self.original_stdout
                self.root.destroy()
        else:
            # 恢复stdout
            sys.stdout = self.original_stdout
            self.root.destroy()

def main():
    """主函数 - 启动GUI"""
    root = tk.Tk()
    app = CNKISpiderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()