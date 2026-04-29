import logging
import os
import time
import yaml
from pathlib import Path
from src.core.podcast import PodcastClient
from src.core.transcription import transcribe_podcast
from src.core.rss import RSSProcessor
from src.core.storage import Storage
from src.core.tongyi_client import TongyiClient
from src.core.exceptions import TranscriptionError, RSSError

def setup_logging():
    """配置日志处理器"""
    # 创建logs目录
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # 生成日志文件名，包含时间戳
    log_file = log_dir / f"podcast_rss_{time.strftime('%Y%m%d_%H%M%S')}.log"
    
    # 创建格式化器
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 创建并配置文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # 创建并配置控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # 移除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    # 添加新的处理器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return log_file

def main():
    """主程序入口"""
    # 设置日志
    log_file = setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"日志将保存到: {log_file}")
    
    start_time = time.time()
    # 初始化存储
    storage = Storage()
    
    try:
        # 1. 读取配置
        config_path = Path(__file__).parent.parent / "config" / "podcasts.yml"
        with open(config_path) as f:
            podcasts = yaml.safe_load(f)['podcasts']
            
        if not podcasts:
            logger.error("配置文件为空")
            return
            
        total_podcasts = len(podcasts)
        logger.info(f"共有 {total_podcasts} 个指定播客需要处理")
        
        # 2. 初始化处理器
        client = PodcastClient(storage)
        rss_processor = RSSProcessor()
        tongyi_client = TongyiClient()
        cookie_valid = tongyi_client.check_cookie_valid()
        if not cookie_valid:
            logger.warning("TONGYI_COOKIE 无效，将跳过转写步骤，仅更新播客数据和重新生成RSS")

        # 初始化 LLM 摘要（可选）
        summarizer = None
        if os.getenv("DEEPSEEK_API_KEY"):
            try:
                from src.core.summarizer import Summarizer
                summarizer = Summarizer()
            except Exception as e:
                logger.warning(f"Summarizer 初始化失败，将跳过摘要生成: {e}")
        else:
            logger.info("未设置 DEEPSEEK_API_KEY，跳过 LLM 摘要生成")

        logger.info("开始更新播客与剧集数据...")
        pids = [p['pid'] for p in podcasts if 'pid' in p]
        changed_pids = client.update_all(pids)
        logger.info("完成更新播客与剧集数据...")

        # 3. 并行处理有新内容的播客（转写 + RSS生成）
        changed_podcasts = [p for p in podcasts if p.get('pid') in changed_pids]
        if not changed_podcasts:
            logger.info("所有播客均无新内容，无需处理")

        def _process_single_podcast(podcast):
            """处理单个播客的转写和RSS生成"""
            pid = podcast.get('pid')
            name = podcast.get('name')
            if not pid or not name:
                logger.error(f"播客配置错误: {podcast}")
                return

            podcast_start_time = time.time()
            logger.info(f"开始处理播客：{name}")

            try:
                # 3.1 处理音频转写
                if cookie_valid:
                    logger.info(f"正在处理音频转写: {name}")
                    try:
                        transcribe_podcast(pid, storage=storage, tongyi_client=tongyi_client, summarizer=summarizer)
                    except TranscriptionError as e:
                        logger.error(f"音频转写失败: {name}, {str(e)}")

                # 3.2 生成RSS
                logger.info(f"正在生成RSS: {name}")
                try:
                    rss_processor.generate_rss(pid)
                except RSSError as e:
                    logger.error(f"RSS生成失败: {name}, {str(e)}")

                podcast_time = time.time() - podcast_start_time
                logger.info(f"播客 {name} 处理完成，耗时：{podcast_time:.2f}秒")

            except Exception as e:
                logger.error(f"处理播客 {name} 时发生错误：{str(e)}")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        if changed_podcasts:
            logger.info(f"开始并行处理 {len(changed_podcasts)} 个播客（最多3个同时进行）...")
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_process_single_podcast, p): p for p in changed_podcasts}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        podcast = futures[future]
                        logger.error(f"播客处理异常: {podcast.get('name')}, {str(e)}")
        
        total_time = time.time() - start_time
        logger.info(f"所有播客处理完成，总耗时：{total_time:.2f}秒")
        
    except Exception as e:
        logger.error(f"程序执行出错：{str(e)}")
        raise

if __name__ == "__main__":
    main()