# 中国知网论文爬虫

一个用于爬取中国知网（CNKI）论文信息的Python爬虫工具，支持批量下载论文PDF/CAJ文件并保存到MySQL数据库。

## 功能特性

- ✅ **智能爬取**：自动搜索并提取论文标题、作者、发表时间等信息
- ✅ **批量下载**：支持批量下载论文PDF/CAJ文件
- ✅ **数据存储**：自动保存论文元数据到MySQL数据库
- ✅ **日志记录**：完整的日志系统，详细记录运行过程
- ✅ **错误处理**：完善的异常处理和重试机制
- ✅ **进度显示**：实时显示爬取和下载进度

## 环境要求

- Python 3.7+
- Chrome浏览器
- ChromeDriver（已包含在项目中）版本为142.0.7444.175
- MySQL数据库（可选，如不使用数据库功能可忽略）

## 安装步骤

### 1. 克隆或下载项目

```bash
# 如果使用git
git clone <repository-url>
cd 新建文件夹

# 或直接下载解压项目文件
```

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

### 3. 配置ChromeDriver

项目已包含 `chromedriver.exe`，确保它与 `中国知网.py` 在同一目录下。

如果ChromeDriver版本与Chrome浏览器不匹配，请：
- 查看Chrome版本：打开Chrome -> 设置 -> 关于Chrome
- 下载对应版本的ChromeDriver：https://chromedriver.chromium.org/
- 替换项目中的 `chromedriver.exe`

### 4. 配置MySQL数据库（可选）

如果不需要数据库功能，可以跳过此步骤。程序会在数据库连接失败时继续运行，只是不保存数据。

#### 方式一：使用默认配置
程序默认使用以下配置：
- 主机：localhost
- 端口：3306
- 用户：root
- 密码：123456
- 数据库：cnki（自动创建）

#### 方式二：使用环境变量配置
在运行前设置环境变量：

**Windows (PowerShell):**
```powershell
$env:DB_HOST="localhost"
$env:DB_PORT="3306"
$env:DB_USER="root"
$env:DB_PASSWORD="your_password"
```

**Windows (CMD):**
```cmd
set DB_HOST=localhost
set DB_PORT=3306
set DB_USER=root
set DB_PASSWORD=your_password
```

**Linux/Mac:**
```bash
export DB_HOST=localhost
export DB_PORT=3306
export DB_USER=root
export DB_PASSWORD=your_password
```

## 使用方法

### 基本使用

```bash
python 中国知网.py
```

运行后会提示输入：
1. **检索词**：要搜索的关键词（例如：Python、机器学习）
2. **论文数量**：需要爬取的论文数量（例如：100）

### 示例

```
请输入检索词（例如：Python）：python
请输入需要爬取的论文数量（例如：100）：20
```

程序将自动：
1. 打开知网首页
2. 搜索指定关键词
3. 爬取论文信息
4. 保存到MySQL数据库
5. 下载PDF/CAJ文件到 `mypdf/` 目录

## 项目结构

```
新建文件夹/
├── 中国知网.py          # 主程序文件
├── chromedriver.exe     # Chrome浏览器驱动
├── requirements.txt     # Python依赖包列表
├── README.md           # 项目说明文档
├── logs/               # 日志文件目录（自动创建）
│   └── cnki_spider_YYYYMMDD_HHMMSS.log
└── mypdf/              # 下载的PDF/CAJ文件目录（自动创建）
    └── 论文标题.caj
```

## 配置说明

### 无头模式运行

在代码中修改 `main()` 函数：

```python
spider = CNKISpider(headless=True)  # 设置为True可无头运行
```

### 自定义ChromeDriver路径

```python
spider = CNKISpider(driver_path="path/to/chromedriver.exe")
```

### 禁用PDF下载

在 `search_and_crawl()` 方法调用时设置：

```python
papers = spider.search_and_crawl(theme, papers_need, max_pages, download_pdf=False)
```

## 数据库结构

程序会自动创建以下数据库表：

**数据库名：** `cnki`

**表名：** `mycnki`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INT | 主键，自增 |
| title | VARCHAR(500) | 论文标题 |
| authors | VARCHAR(500) | 作者（多个作者用"；"分隔） |
| pub_date | VARCHAR(50) | 发表日期 |
| page | INT | 所在页码 |
| file_name | VARCHAR(500) | 下载的文件名 |
| created_at | DATETIME | 创建时间（自动） |

## 日志系统

程序会生成详细的日志文件，保存在 `logs/` 目录下：

- **日志文件命名格式**：`cnki_spider_YYYYMMDD_HHMMSS.log`
- **日志级别**：
  - DEBUG：详细调试信息（仅文件）
  - INFO：一般信息（仅文件）
  - WARNING：警告信息（文件+控制台）
  - ERROR：错误信息（文件+控制台）

**控制台输出**：仅显示关键进度和错误信息，保持界面简洁。

## 常见问题

### 1. ChromeDriver版本不匹配

**错误信息**：`SessionNotCreatedException` 或 `This version of ChromeDriver only supports Chrome version XX`

**解决方法**：
- 更新Chrome浏览器到最新版本
- 下载对应版本的ChromeDriver
- 或使用 `webdriver-manager` 自动管理驱动

### 2. 找不到搜索结果区域

**可能原因**：
- 网络连接问题
- 知网页面结构更新
- 页面加载时间过长

**解决方法**：
- 检查网络连接
- 查看日志文件获取详细错误信息
- 增加等待时间（修改代码中的 `time.sleep()` 值）

### 3. MySQL连接失败

**错误信息**：`初始化 MySQL 数据库失败`

**解决方法**：
- 确保MySQL服务正在运行
- 检查数据库用户名和密码
- 确认MySQL允许本地连接
- 或使用环境变量配置数据库信息

### 4. 下载文件失败

**可能原因**：
- 网络不稳定
- 文件链接失效
- 需要登录权限

**解决方法**：
- 检查网络连接
- 查看日志文件了解具体错误
- 部分论文可能需要登录才能下载

## 注意事项

1. **合法使用**：请遵守知网的使用条款，仅用于学习和研究目的
2. **访问频率**：建议适当控制爬取频率，避免对服务器造成过大压力
3. **数据使用**：下载的论文仅供个人学习研究使用，请勿用于商业用途
4. **版权尊重**：尊重论文作者的版权，合理使用下载的内容

## 技术栈

- **Python 3.7+**
- **Selenium** - Web自动化框架
- **PyMySQL** - MySQL数据库连接
- **Requests** - HTTP请求库
- **Logging** - 日志记录

## 许可证

本项目仅供学习和研究使用。


