# Podcast2RSS

将[小宇宙](https://www.xiaoyuzhoufm.com/)播客自动转写为文字稿，生成 RSS Feed，用你喜欢的 RSS 阅读器订阅。

**听不完的播客，读得完。**

## 它能做什么

- 定时从小宇宙获取你关注的播客的最新单集
- 通过[通义听悟](https://tongyi.aliyun.com/efficiency)自动转写音频为带时间戳、说话人标注的文字稿
- 生成标准 RSS 2.0 Feed，部署到 GitHub Pages
- 用任意 RSS 阅读器（[Follow](https://follow.is)、Reeder、Inoreader 等）订阅阅读

## 快速开始

### 1. Fork 本仓库

点击右上角 **Fork**，复制到你自己的 GitHub 账号下。

### 2. 获取 Token

你需要两个凭证：

#### 小宇宙 Refresh Token

用于访问小宇宙 API 获取播客和单集数据。

1. 在浏览器或抓包工具中登录小宇宙
2. 找到请求头中的 `x-jike-refresh-token` 值
3. 支持配置最多 5 个 Token 轮换使用（推荐，降低单个 Token 被限流的风险）

#### 通义听悟 Cookie

用于调用通义听悟的音频转写服务。

1. 打开 [通义听悟](https://tongyi.aliyun.com/efficiency) 并登录
2. 打开浏览器开发者工具（F12）→ Network
3. 随便触发一个请求，从请求头中复制完整的 `Cookie` 值

### 3. 配置 GitHub Secrets

进入你 Fork 的仓库 → **Settings** → **Secrets and variables** → **Actions**，添加以下 Secrets：

| Secret 名称 | 说明 |
|---|---|
| `REFRESH_TOKEN_1` | 小宇宙 Refresh Token（必填，至少配一个） |
| `REFRESH_TOKEN_2` ~ `REFRESH_TOKEN_5` | 额外的 Refresh Token（可选） |
| `TONGYI_COOKIE` | 通义听悟 Cookie（必填） |

### 4. 配置你的播客列表

编辑 `config/podcasts.yml`，替换为你想要订阅的播客：

```yaml
podcasts:
- pid: 6388760f22567e8ea6ad070f
  name: 面基
- pid: 611719d3cb0b82e1df0ad29e
  name: 无人知晓
```

`pid` 是播客在小宇宙的唯一标识，可以从播客页面 URL 中获取：
```
https://www.xiaoyuzhoufm.com/podcast/65257ff6e8ce9deaf70a65e9
                                      ^^^^^^^^^^^^^^^^^^^^^^^^ 这就是 pid
```

### 5. 启用 GitHub Actions 和 Pages

1. 进入仓库 → **Actions** → 点击 **I understand my workflows, go ahead and enable them**
2. 进入 **Settings** → **Pages** → Source 选择 **Deploy from a branch** → Branch 选择 `gh-pages` / `root`
3. 手动触发一次：**Actions** → **Podcast RSS Update** → **Run workflow**

### 6. 订阅 RSS

运行成功后，你的 RSS 地址格式为：

```
https://<你的用户名>.github.io/<仓库名>/<pid>.xml
```

在 RSS 阅读器中添加即可。

## 工作原理

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│  小宇宙 API  │ ──→ │  本地数据存储  │ ──→ │  通义听悟转写  │ ──→ │  RSS 生成  │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────┘
```

GitHub Actions 每两天自动运行一次（也可手动触发），执行以下流程：

1. **增量检测** — 对比每个播客的 `latestEpisodePubDate`，只处理有新内容的播客
2. **获取单集** — 并行获取有更新的播客的最新单集信息（最多保留 30 集）
3. **音频转写** — 将未转写的单集提交到通义听悟，自动轮询等待结果
4. **生成 RSS** — 将转写文稿生成标准 RSS 2.0 格式
5. **部署** — 提交数据到 `master`，同步 RSS 文件到 `gh-pages` 供 GitHub Pages 托管

### 项目结构

```
Podcast2RSS/
├── src/
│   ├── core/
│   │   ├── podcast.py          # 小宇宙 API 客户端
│   │   ├── tongyi_client.py    # 通义听悟 API 客户端
│   │   ├── transcription.py    # 转写任务编排
│   │   ├── rss.py              # RSS Feed 生成
│   │   └── storage.py          # 数据存储管理
│   ├── config/paths.py         # 路径和业务常量
│   └── main.py                 # 主程序入口
├── config/podcasts.yml         # 播客订阅列表
├── data/
│   ├── podcasts/{pid}.json     # 播客元数据
│   ├── episodes/{pid}.json     # 单集信息
│   ├── transcripts/{pid}/      # 转写文稿
│   └── rss/{pid}.xml           # 生成的 RSS Feed
└── .github/workflows/          # GitHub Actions 定时任务
```

## 配置参考

`src/config/paths.py` 中可调整的参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `RSS_MAX_EPISODES` | 30 | RSS Feed 最多包含的单集数 |
| `MIN_EPISODE_DURATION` | 180 | 最短单集时长（秒），低于此值跳过转写 |
| `MAX_EPISODE_DURATION` | 18000 | 最长单集时长（秒），超过此值跳过转写 |
| `TRANSCRIPTION_BATCH_SIZE` | 10 | 每批提交的转写任务数 |

## 注意事项

- **Token 有效期**：小宇宙 Refresh Token 和通义听悟 Cookie 都会过期，需要定期更新 GitHub Secrets
- **付费单集**：付费单集会自动跳过转写
- **运行频率**：默认每两天运行一次，可在 `.github/workflows/daily-update.yml` 中修改 cron 表达式
- **费用**：GitHub Actions 对公开仓库免费，通义听悟目前免费使用

## License

MIT
