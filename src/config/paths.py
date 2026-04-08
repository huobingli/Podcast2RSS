import os
from pathlib import Path

# 获取项目根目录
PROJECT_ROOT = Path(os.getenv('PROJECT_ROOT', Path(__file__).parent.parent.parent))

# 配置目录
CONFIG_DIR = Path(os.getenv('CONFIG_DIR', PROJECT_ROOT / 'config'))
PODCASTS_CONFIG = CONFIG_DIR / 'podcasts.yml'

# 数据目录
DATA_DIR = Path(os.getenv('DATA_DIR', PROJECT_ROOT / 'data'))

# 日志目录
LOGS_DIR = PROJECT_ROOT / 'logs'

# --- 业务常量 ---

# 剧集时长过滤（秒）
MIN_EPISODE_DURATION = 180       # 3分钟以下跳过
MAX_EPISODE_DURATION = 18000     # 5小时以上跳过

# 转写处理
TRANSCRIPTION_BATCH_SIZE = 10           # 每批提交的转写任务数
TRANSCRIPTION_POLL_INTERVAL = 45        # 转写状态轮询间隔（秒）
TRANSCRIPTION_MAX_WAIT = 1800           # 转写最大等待时间（秒）
AUDIO_PARSE_TIMEOUT = 300               # 音频解析轮询超时（秒）

# 分页
TONGYI_PAGE_SIZE = 48                   # 通义听悟目录列表分页大小

# RSS
RSS_MAX_EPISODES = 30                   # RSS Feed 最多包含的单集数

# 确保基础目录存在
def ensure_base_directories():
    """确保基础目录存在"""
    directories = [
        CONFIG_DIR,
        DATA_DIR,
        LOGS_DIR
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

# 在导入时确保基础目录存在
ensure_base_directories()
