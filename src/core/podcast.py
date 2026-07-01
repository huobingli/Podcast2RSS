import json
import pendulum
import requests
import logging
import re
import time
from html import unescape

from src.config.paths import RSS_MAX_EPISODES

# 配置日志
logger = logging.getLogger(__name__)


class PodcastClient:
    """小宇宙播客客户端"""

    BASE_URL = "https://www.xiaoyuzhoufm.com"
    
    def __init__(self, storage):
        """初始化客户端
        
        Args:
            storage: Storage实例，用于管理数据存储
        """
        self.storage = storage
        self._podcast_cache = {}
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        logger.info("使用小宇宙公开网页数据源，无需 refresh token")

    def _request(self, url):
        for attempt in range(3):
            resp = self.session.get(url, timeout=30)
            if resp.status_code not in (429, 500, 502, 503, 504):
                resp.raise_for_status()
                return resp

            if attempt == 2:
                resp.raise_for_status()

            wait_seconds = 2 * (attempt + 1)
            logger.warning(f"请求小宇宙页面失败 {resp.status_code}，{wait_seconds}s 后重试: {url}")
            time.sleep(wait_seconds)

        raise RuntimeError(f"请求失败: {url}")

    @staticmethod
    def _parse_next_data(html):
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            raise ValueError("未找到小宇宙页面中的 __NEXT_DATA__")

        raw_data = match.group(1)
        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            return json.loads(unescape(raw_data))

    def _get_podcast_payload(self, pid):
        """从公开播客页读取 Next.js 数据。"""
        pid = pid.strip()
        if pid in self._podcast_cache:
            return self._podcast_cache[pid]

        url = f"{self.BASE_URL}/podcast/{pid}"
        next_data = self._parse_next_data(self._request(url).text)
        podcast = next_data.get("props", {}).get("pageProps", {}).get("podcast")
        if not podcast:
            raise ValueError(f"未获取到播客信息: {pid}")

        payload = {
            "build_id": next_data.get("buildId"),
            "podcast": podcast,
        }
        self._podcast_cache[pid] = payload
        return payload

    def _get_episode_detail(self, build_id, eid):
        """读取单集详情，用于补全 shownotes。失败时由调用方回退到列表数据。"""
        if not build_id or not eid:
            return None

        url = f"{self.BASE_URL}/_next/data/{build_id}/episode/{eid}.json"
        resp = self._request(url)
        return resp.json().get("pageProps", {}).get("episode")

    def get_episodes(self, pid):
        """获取播客剧集列表"""
        payload = self._get_podcast_payload(pid)
        build_id = payload.get("build_id")
        raw_episodes = payload["podcast"].get("episodes") or []
        episodes = raw_episodes[:RSS_MAX_EPISODES]

        for index, episode in enumerate(episodes):
            eid = episode.get("eid")
            try:
                detail = self._get_episode_detail(build_id, eid)
                if detail:
                    episodes[index] = {**episode, **detail}
            except Exception as e:
                logger.warning(f"获取单集详情失败，将使用列表数据: {eid}, 错误: {e}")

        return episodes

    def get_podcast_info(self, pid):
        """获取单个播客的信息"""
        podcast = self._get_podcast_payload(pid)["podcast"]
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
        """顺序获取所有播客信息，避免公开网页触发频率限制

        Args:
            pids: 播客ID列表
        Returns:
            dict: {pid: podcast_info} 映射
        """
        results = {}
        for pid in pids:
            try:
                results[pid] = self.get_podcast_info(pid)
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

            # 逐个获取播客信息（不依赖订阅关系，任何有效 token 都能查询）
            all_podcast_info = self.fetch_all_podcast_info(pids)

            missing_pids = set(pids) - set(all_podcast_info.keys())
            if missing_pids:
                logger.warning(f"以下播客信息获取失败，将跳过: {missing_pids}")

            logger.info(f"获取到 {len(all_podcast_info)}/{len(pids)} 个播客信息")
            if pids and not all_podcast_info:
                raise Exception("未获取到任何播客信息，终止本次更新")

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

            # 并行获取有新内容的播客的剧集信息
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _fetch_and_save_episodes(pid):
                episodes = self.get_episodes(pid)
                if episodes:
                    self.save_episodes(episodes, pid)
                return pid, len(episodes) if episodes else 0

            if changed_pids:
                logger.info(f"开始并行获取 {len(changed_pids)} 个播客的剧集信息...")
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(_fetch_and_save_episodes, pid): pid for pid in changed_pids}
                    for future in as_completed(futures):
                        pid = futures[future]
                        try:
                            _, count = future.result()
                            if count > 0:
                                logger.info(f"获取到 {count} 个剧集: {pid}")
                            else:
                                logger.warning(f"播客 {pid} 没有任何剧集")
                        except Exception as e:
                            logger.error(f"获取剧集失败: {pid}, 错误: {str(e)}")

            return changed_pids

        except Exception as e:
            logger.error(f"执行失败: {str(e)}")
            raise
