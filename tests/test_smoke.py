"""
冒烟测试：验证主流程各模块能正常导入和基本逻辑正确
不依赖外部 API，纯本地验证
"""
import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保项目根目录在 path 中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_imports():
    """测试所有模块能正常导入"""
    print("=== 测试模块导入 ===")
    from src.config.paths import (
        DATA_DIR, RSS_MAX_EPISODES, MIN_EPISODE_DURATION,
        MAX_EPISODE_DURATION, TRANSCRIPTION_BATCH_SIZE,
        TRANSCRIPTION_POLL_INTERVAL, TRANSCRIPTION_MAX_WAIT,
        AUDIO_PARSE_TIMEOUT, TONGYI_PAGE_SIZE,
    )
    from src.core.storage import Storage
    from src.core.rss import RSSProcessor
    from src.core.exceptions import TranscriptionError, RSSError, PodcastError
    # transcription 和 podcast 依赖环境变量，单独测
    print("  所有模块导入成功")


def test_storage():
    """测试 Storage 基本功能"""
    print("=== 测试 Storage ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        # 测试目录创建
        assert storage.episodes_dir.exists()
        assert storage.transcripts_dir.exists()
        assert storage.rss_dir.exists()
        assert storage.podcasts_dir.exists()

        # 测试 is_transcribed
        assert not storage.is_transcribed("test_pid", "test_eid")

        # 测试 save_transcript + is_transcribed
        storage.save_transcript("test_pid", "test_eid", {"transcription": [{"text": "hello"}]})
        assert storage.is_transcribed("test_pid", "test_eid")

        # 测试 load_transcript
        data = storage.load_transcript("test_pid", "test_eid")
        assert data["transcription"][0]["text"] == "hello"

        # 测试 save_rss
        storage.save_rss("test_pid", "<rss>test</rss>")
        rss_file = storage.rss_dir / "test_pid.xml"
        assert rss_file.exists()
        assert rss_file.read_text() == "<rss>test</rss>"

        print("  Storage 测试通过")


def test_episode_collector():
    """测试 EpisodeCollector 收集逻辑"""
    print("=== 测试 EpisodeCollector ===")
    from src.core.transcription import EpisodeCollector
    from src.config.paths import MIN_EPISODE_DURATION, MAX_EPISODE_DURATION

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        # 准备测试数据
        episodes = {
            "ep1": {
                "title": "正常剧集",
                "duration": 3600,
                "enclosure": {"url": "https://example.com/ep1.mp3"},
                "pubDate": 1700000000,
                "payType": "FREE",
            },
            "ep2": {
                "title": "太短的剧集",
                "duration": 60,
                "enclosure": {"url": "https://example.com/ep2.mp3"},
                "pubDate": 1700000001,
                "payType": "FREE",
            },
            "ep3": {
                "title": "付费剧集",
                "duration": 3600,
                "enclosure": {"url": "https://example.com/ep3.mp3"},
                "pubDate": 1700000002,
                "payType": "PAY_EPISODE",
            },
            "ep4": {
                "title": "太长的剧集",
                "duration": 20000,
                "enclosure": {"url": "https://example.com/ep4.mp3"},
                "pubDate": 1700000003,
                "payType": "FREE",
            },
        }
        episodes_file = storage.episodes_dir / "test_pid.json"
        episodes_file.write_text(json.dumps(episodes))

        collector = EpisodeCollector(storage)
        result = collector.collect_untranscribed("test_pid")

        # 只有 ep1 应该被收集（ep2 太短，ep3 付费，ep4 太长）
        assert len(result) == 1
        assert result[0]["eid"] == "ep1"
        print("  EpisodeCollector 测试通过")


def test_rss_processor():
    """测试 RSS 生成逻辑"""
    print("=== 测试 RSSProcessor ===")
    from src.core.rss import RSSProcessor

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        # 准备播客信息
        podcast_info = {
            "title": "测试播客",
            "brief": "测试描述",
            "description": "详细描述",
            "latestEpisodePubDate": "2025-01-01T00:00:00Z",
        }
        podcast_file = storage.podcasts_dir / "test_pid.json"
        podcast_file.write_text(json.dumps(podcast_info))

        # 准备剧集
        episodes = {
            "ep1": {
                "title": "测试剧集",
                "description": "剧集描述",
                "pubDate": 1700000000,
                "shownotes": "",
            }
        }
        episodes_file = storage.episodes_dir / "test_pid.json"
        episodes_file.write_text(json.dumps(episodes))

        # 准备转写文件
        storage.save_transcript("test_pid", "ep1", {
            "transcription": [
                {"time": "00:00:01", "speaker": "主播", "text": "大家好"}
            ]
        })

        # 用 mock storage 路径来测试
        with patch.object(RSSProcessor, '__init__', lambda self: None):
            processor = RSSProcessor()
            processor.storage = storage
            processor.logger = MagicMock()

            processor.generate_rss("test_pid")

        rss_file = storage.rss_dir / "test_pid.xml"
        assert rss_file.exists()
        content = rss_file.read_text()
        assert "测试播客" in content
        assert "测试剧集" in content
        assert "大家好" in content
        print("  RSSProcessor 测试通过")


def test_podcast_update_all_logic():
    """测试 update_all 中的订阅列表逻辑（mock API）"""
    print("=== 测试 update_all 逻辑 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        # 模拟已有的播客信息（旧的 latestEpisodePubDate）
        old_info = {
            "title": "播客A",
            "latestEpisodePubDate": "2025-01-01T00:00:00Z",
        }
        (storage.podcasts_dir / "pid_a.json").write_text(json.dumps(old_info))

        # 模拟订阅列表返回（pid_a 有更新，pid_b 是新的）
        mock_subscription = [
            {"pid": "pid_a", "title": "播客A", "brief": "", "episodeCount": 10,
             "description": "", "latestEpisodePubDate": "2025-02-01T00:00:00Z"},
            {"pid": "pid_b", "title": "播客B", "brief": "", "episodeCount": 5,
             "description": "", "latestEpisodePubDate": "2025-01-15T00:00:00Z"},
            {"pid": "pid_other", "title": "不在配置中", "brief": "", "episodeCount": 1,
             "description": "", "latestEpisodePubDate": "2025-01-01T00:00:00Z"},
        ]

        # 构造 mock PodcastClient
        with patch('src.core.podcast.PodcastClient.__init__', return_value=None):
            from src.core.podcast import PodcastClient
            client = PodcastClient.__new__(PodcastClient)
            client.storage = storage
            client.headers = {}
            client.session = MagicMock()

            # mock get_subscription 和 get_episodes
            client.get_subscription = MagicMock(return_value=mock_subscription)
            client.ensure_token = MagicMock()
            client.get_episodes = MagicMock(return_value=[])
            client.refresh_token = MagicMock()

            pids = ["pid_a", "pid_b", "pid_c"]  # pid_c 不在订阅列表中
            changed = client.update_all(pids)

            # pid_a 有更新，pid_b 是新的（本地无文件），pid_c 不在订阅列表
            assert "pid_a" in changed, f"pid_a should be changed, got {changed}"
            assert "pid_b" in changed, f"pid_b should be changed, got {changed}"
            assert "pid_c" not in changed, f"pid_c should not be changed, got {changed}"

            # 验证调用了 get_subscription 而不是 fetch_all_podcast_info
            client.get_subscription.assert_called_once()

        print("  update_all 逻辑测试通过")


def test_parallel_prepare():
    """测试并行 prepare_audio_file 逻辑"""
    print("=== 测试并行音频准备 ===")
    from src.core.transcription import TranscriptionProcessor
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        # mock TongyiClient
        mock_client = MagicMock()
        mock_client.ensure_dir_exist.return_value = "dir_123"

        # prepare_audio_file 模拟耗时 0.5 秒
        def slow_prepare(eid, url):
            time.sleep(0.5)
            return [{"fileId": f"file_{eid}", "fileSize": 1000, "tag": {}}]

        mock_client.prepare_audio_file.side_effect = slow_prepare
        mock_client.start_transcription.return_value = True

        processor = TranscriptionProcessor(
            tongyi_client=mock_client, pid="test_pid", storage=storage
        )

        episodes = [
            {"eid": f"ep{i}", "title": f"剧集{i}", "audio_url": f"https://example.com/ep{i}.mp3",
             "pid": "test_pid", "duration": 3600}
            for i in range(6)
        ]

        start = time.time()
        tasks = processor._prepare_and_submit_tasks(episodes, "dir_123")
        elapsed = time.time() - start

        assert len(tasks) == 6, f"Expected 6 tasks, got {len(tasks)}"
        # 6 个任务，每个 0.5 秒，3 并发 → 应该约 1 秒完成，串行要 3 秒
        assert elapsed < 2.0, f"并行应该在 2 秒内完成，实际耗时 {elapsed:.1f}秒"
        print(f"  6 个任务并行准备耗时 {elapsed:.1f}秒（串行预期 3 秒），测试通过")


def test_refresh_token_syncs_to_session():
    """测试 refresh_token 后 access token 同步到 session.headers"""
    print("=== 测试 refresh_token 同步 session ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = _create_storage(tmpdir)

        with patch('src.core.podcast.PodcastClient.__init__', return_value=None):
            from src.core.podcast import PodcastClient
            client = PodcastClient.__new__(PodcastClient)
            client.storage = storage
            client.headers = {
                "host": "api.xiaoyuzhoufm.com",
                "applicationid": "app.podcast.cosmos",
                "x-jike-refresh-token": "fake-refresh-token",
            }
            client.session = MagicMock()
            client.session.headers = dict(client.headers)

            # mock refresh API 返回
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"x-jike-access-token": "new-access-token"}
            client.session.post.return_value = mock_resp

            client.refresh_token()

            assert client.headers.get("x-jike-access-token") == "new-access-token"
            assert client.session.headers.get("x-jike-access-token") == "new-access-token", \
                "access token 未同步到 session.headers"

        print("  refresh_token 同步测试通过")


def _create_storage(tmpdir):
    """创建测试用 Storage"""
    from src.core.storage import Storage
    return Storage(base_dir=tmpdir)


if __name__ == "__main__":
    tests = [
        test_imports,
        test_storage,
        test_episode_collector,
        test_rss_processor,
        test_podcast_update_all_logic,
        test_parallel_prepare,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")

    print(f"\n{'='*40}")
    print(f"结果: {passed} 通过, {failed} 失败")
    sys.exit(1 if failed else 0)
