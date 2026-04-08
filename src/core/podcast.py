import json
import os
import random
import pendulum
from retrying import retry
import requests
from pathlib import Path
import time
import logging
import yaml
from datetime import datetime

from src.core.storage import Storage
from src.config.paths import RSS_MAX_EPISODES

# 配置日志
logger = logging.getLogger(__name__)

class PodcastClient:
    """小宇宙播客客户端"""
    
    def __init__(self, storage):
        """初始化客户端
        
        Args:
            storage: Storage实例，用于管理数据存储
        """
        self.storage = storage
        
        # 加载所有可用的 refresh token，随机选择一个使用
        tokens = self._load_refresh_tokens()
        chosen = random.choice(tokens)
        chosen_index = tokens.index(chosen) + 1
        logger.info(f"已加载 {len(tokens)} 个 refresh token，本次随机使用 #{chosen_index}")
        
        self.headers = {
            "host": "api.xiaoyuzhoufm.com",
            "applicationid": "app.podcast.cosmos",
            "x-jike-refresh-token": chosen,
            "x-jike-device-id": "5070e349-ba04-4c7b-a32e-13eb0fed01e7",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    @staticmethod
    def _load_refresh_tokens():
        """从环境变量加载所有可用的 refresh token
        
        支持两种配置方式：
        1. REFRESH_TOKEN_1 ~ REFRESH_TOKEN_5（推荐，多token随机轮换）
        2. REFRESH_TOKEN（兼容旧配置，单token）
        """
        tokens = []
        for i in range(1, 6):
            token = os.getenv(f"REFRESH_TOKEN_{i}")
            if token:
                tokens.append(token)
        
        # 兼容旧的单 token 配置
        if not tokens:
            single_token = os.getenv("REFRESH_TOKEN")
            if single_token:
                tokens.append(single_token)
        
        if not tokens:
            raise Exception("缺少必要的环境变量: 请设置 REFRESH_TOKEN_1~5 或 REFRESH_TOKEN")
        
        return tokens

    def ensure_token(self):
        """确保token有效"""
        if "x-jike-access-token" not in self.headers:
            self.refresh_token()

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def refresh_token(self):
        """刷新访问令牌"""
        url = "https://api.xiaoyuzhoufm.com/app_auth_tokens.refresh"
        resp = self.session.post(url)
        if not resp.ok:
            raise Exception(f"刷新令牌失败: {resp.text}")
        token = resp.json().get("x-jike-access-token")
        if not token:
            raise Exception("未获取到有效的访问令牌")
        self.headers["x-jike-access-token"] = token
        # 等待token生效
        time.sleep(1)

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_subscription(self):
        """获取订阅的播客列表"""
        self.ensure_token()
        results = []
        url = "https://api.xiaoyuzhoufm.com/v1/subscription/list"
        data = {
            "limit": 25,
            "sortBy": "subscribedAt",
            "sortOrder": "desc",
        }
        loadMoreKey = ""
        while loadMoreKey is not None:
            if loadMoreKey:
                data["loadMoreKey"] = loadMoreKey
            resp = self.session.post(url, json=data)
            if resp.ok:
                loadMoreKey = resp.json().get("loadMoreKey")
                results.extend(resp.json().get("data"))
            else:
                self.refresh_token()
                raise Exception(f"Error {data} {resp.text}")
        return results

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_episodes(self, pid):
        """获取播客剧集列表"""
        self.ensure_token()
        url = "https://api.xiaoyuzhoufm.com/v1/episode/list"
        episodes = []
        load_more_key = None
        
        while True:
            data = {
                "limit": 25,
                "pid": pid,
            }
            if load_more_key:
                data["loadMoreKey"] = load_more_key
                
            resp = self.session.post(url, json=data)
            if not resp.ok:
                if resp.status_code == 401:
                    self.refresh_token()
                    continue
                raise Exception(f"获取剧集列表失败: {resp.text}")
                
            resp_data = resp.json()
            new_episodes = resp_data.get("data", [])
            if not new_episodes:
                break
                
            episodes.extend(new_episodes)
            if len(episodes) >= RSS_MAX_EPISODES:
                break
            load_more_key = resp_data.get("loadMoreKey")
            if not load_more_key:
                break

        return episodes

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_podcast_info(self, pid):
        """获取单个播客的信息"""
        self.ensure_token()
        url = f"https://api.xiaoyuzhoufm.com/v1/podcast/get?pid={pid}"
        
        # 获取ISO格式的当前时间
        now = datetime.now()
        iso_time = now.strftime("%Y-%m-%dT%H:%M:%S%z")
        
        # 添加必要的请求头
        headers = {
            **self.headers,
            'User-Agent': 'Xiaoyuzhou/2.57.1 (build:1576; iOS 17.4.1)',
            'Market': 'AppStore',
            'App-BuildNo': '1576',
            'OS': 'ios',
            'Manufacturer': 'Apple',
            'BundleID': 'app.podcast.cosmos',
            'Model': 'iPhone14,2',
            'App-Version': '2.57.1',
            'OS-Version': '17.4.1',
            'Local-Time': iso_time,
            'Timezone': 'Asia/Shanghai',
            'Accept': '*/*',
            'Accept-Language': 'zh-Hant-HK;q=1.0, zh-Hans-CN;q=0.9'
        }

        resp = self.session.get(url, headers=headers)

        if not resp.ok:
            if resp.status_code == 401:
                self.refresh_token()
            raise Exception(f"获取播客信息失败: {resp.text}")
            
        podcast = resp.json().get("data", {})
        if not podcast:
            raise Exception(f"未获取到播客信息: {pid}")
            
        # 只保留需要的字段
        filtered_podcast = {
            'latestEpisodePubDate': podcast.get('latestEpisodePubDate'),
            'pid': podcast.get('pid'),
            'title': podcast.get('title'),
            'brief': podcast.get('brief'),
            'episodeCount': podcast.get('episodeCount', 0),
            'description': podcast.get('description')
        }
        return filtered_podcast

    def fetch_all_podcast_info(self, pids):
        """并行获取所有播客信息

        Args:
            pids: 播客ID列表
        Returns:
            dict: {pid: podcast_info} 映射
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_pid = {executor.submit(self.get_podcast_info, pid): pid for pid in pids}
            for future in as_completed(future_to_pid):
                pid = future_to_pid[future]
                try:
                    results[pid] = future.result()
                except Exception as e:
                    logger.error(f"获取播客信息失败: {pid}, 错误: {str(e)}")

        return results

    def save_episodes(self, episodes, pid):
        """保存播客剧集到文件"""
        filepath = self.storage.get_episodes_file(pid)
        existing_episodes = {}
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                existing_episodes = json.load(f)
        
        # 更新数据
        for episode in episodes:
            episode_id = episode.get("eid")
            if not episode_id:
                logger.warning(f"剧集缺少eid: {episode.get('title')}")
                continue
            
            # 只保留RSS Feed需要的字段
            episode_data = {
                "eid": episode_id,
                "pid": episode.get("pid"),
                "title": episode.get("title"),
                "description": episode.get("description"),
                "duration": episode.get("duration"),
                "enclosure": {
                    "url": episode.get("enclosure", {}).get("url"),
                    "type": "audio/mpeg",
                    "length": episode.get("media", {}).get("size", 0)
                },
                "pubDate": pendulum.parse(episode.get("pubDate")).in_tz("UTC").int_timestamp if episode.get("pubDate") else None,
                "author": episode.get("podcast", {}).get("author"),
                "explicit": episode.get("explicit", False),
                "payType": episode.get("payType", "FREE"),
                "shownotes": episode.get("shownotes", "")  # 添加 shownotes 字段
            }
            
            existing_episodes[episode_id] = episode_data

        # 只保留最新的 RSS_MAX_EPISODES * 2 个剧集，避免文件无限增长
        if len(existing_episodes) > RSS_MAX_EPISODES * 2:
            sorted_eids = sorted(
                existing_episodes.keys(),
                key=lambda eid: existing_episodes[eid].get('pubDate', 0),
                reverse=True
            )
            existing_episodes = {eid: existing_episodes[eid] for eid in sorted_eids[:RSS_MAX_EPISODES * 2]}

        # 保存到文件
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing_episodes, f, ensure_ascii=False, indent=2)
        
        logger.info(f"保存了 {len(episodes)} 个剧集到: {filepath}")

    def update_all(self, pids=None):
        """更新所有播客数据，返回有新内容的播客ID列表"""
        try:
            changed_pids = []

            # 通过订阅列表一次性获取所有播客信息，替代逐个 API 调用
            subscription_list = self.get_subscription()
            all_podcast_info = {}
            for item in subscription_list:
                pid = item.get('pid')
                if pid and pid in pids:
                    all_podcast_info[pid] = {
                        'latestEpisodePubDate': item.get('latestEpisodePubDate'),
                        'pid': pid,
                        'title': item.get('title'),
                        'brief': item.get('brief'),
                        'episodeCount': item.get('episodeCount', 0),
                        'description': item.get('description'),
                    }

            # 检查 config 中有但订阅列表中没有的播客
            missing_pids = set(pids) - set(all_podcast_info.keys())
            if missing_pids:
                logger.warning(f"以下播客不在订阅列表中，将跳过: {missing_pids}")

            logger.info(f"从订阅列表获取到 {len(all_podcast_info)}/{len(pids)} 个播客信息")

            for pid in pids:
                podcast = all_podcast_info.get(pid)
                if not podcast:
                    continue

                # 对比已存储的信息，检查是否有新内容
                podcast_file = self.storage.get_podcast_file(pid)
                has_new_content = True
                if podcast_file.exists():
                    try:
                        with open(podcast_file, "r", encoding="utf-8") as f:
                            old_podcast = json.load(f)
                        if old_podcast.get('latestEpisodePubDate') == podcast.get('latestEpisodePubDate'):
                            has_new_content = False
                            logger.info(f"播客无新内容，跳过: {podcast.get('title', pid)}")
                    except Exception:
                        pass  # 读取失败则视为有新内容

                # 保存最新播客信息
                with open(podcast_file, "w", encoding="utf-8") as f:
                    json.dump(podcast, f, ensure_ascii=False, indent=4)

                if has_new_content:
                    changed_pids.append(pid)

            logger.info(f"播客信息更新完成，{len(changed_pids)}/{len(pids)} 个播客有新内容")

            # 只获取有新内容的播客的剧集信息
            for index, pid in enumerate(changed_pids, 1):
                try:
                    start_time = time.time()
                    logger.info(f"[{index}/{len(changed_pids)}] 正在获取播客 {pid} 的剧集信息...")
                    episodes = self.get_episodes(pid)
                    if episodes:
                        self.save_episodes(episodes, pid)
                        logger.info(f"[{index}/{len(changed_pids)}] 获取到 {len(episodes)} 个剧集")
                    else:
                        logger.warning(f"[{index}/{len(changed_pids)}] 播客 {pid} 没有任何剧集")
                    process_time = time.time() - start_time
                    logger.info(f"[{index}/{len(changed_pids)}] 处理完成: {pid}, 耗时: {process_time:.2f}秒")
                except Exception as e:
                    logger.error(f"[{index}/{len(changed_pids)}] 处理失败: {pid}, 错误: {str(e)}")

            return changed_pids

        except Exception as e:
            logger.error(f"执行失败: {str(e)}")
            raise
