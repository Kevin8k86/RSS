# 📡 RSS AI Curator (智能主编级深度资讯筛选器)

专为解决 **“RSS 订阅源每天推送太杂、水文太多，但又想每天精读几十篇高质量长文”** 打造。

---

## 💡 核心机制

```
原始高频 RSS 源 (每天推送 200+ 条快讯与文章)
             ↓
【Step 1: 内存/数据库去重】判断是否已评估，避免重复消耗 Token
             ↓
【Step 2: AI 主编严格评审】
  • 淘汰项：公关软文、普通行情涨跌、简讯通告、情绪口水文 (< 6.0分)
  • 加分项：独家产业调查、底层技术拆解、数据复盘、深度长文 (≥ 7.5分)
             ↓
【Step 3: 阈值过滤】仅放行得分 ≥ 7.5 的精华文章
             ↓
【Step 4: 注入精选要义】文首附带【AI 评级】与【推荐理由】
             ↓
输出专属 RSS (每天精选 20~50 篇) 供 ReadYou 阅读
```

---

## ❓ 常见问题：需要用家里的 NAS 部署 Docker 吗？

**结论：不一定需要，你可以根据场景二选一：**

| 对比维度 | 方案 A：云端 GitHub Actions（最推荐） | 方案 B：家里 NAS Docker 部署 |
| :--- | :--- | :--- |
| **服务器要求** | **完全不需要服务器/NAS**，免费托管 | 需要一台 24 小时开机的 NAS 设备 |
| **手机外出访问** | **完美支持**。在外用 5G 网络也能随时刷新 ReadYou | 手机在外刷新需要配置**公网 IP / DDNS / 内网穿透** |
| **维护成本** | **零维护**，微软免费算力定时跑 | 需维护 NAS 容器与本地存储 |
| **运行频率** | 建议每 2~3 小时跑一次 | 随心所欲，每 15 分钟或 1 小时均可 |

> **建议**：
> - 如果你的手机经常在外通勤阅读，推荐 **方案 A (GitHub Actions)**，省心、免维护、不折腾内网穿透；
> - 如果你的 NAS 已经配置好了 Cloudflare Tunnel、Tailscale 或 DDNS，或者你习惯本地掌控，推荐 **方案 B (NAS Docker)**。

---

## 🚀 部署方式一：部署在家里的 NAS (Docker 模式)

### 1. 修改配置
复制并修改 `config.yaml`：
```yaml
llm:
  api_key: "sk-xxxxxxxx" # 填入你的 API Key (推荐 DeepSeek 或 Gemini)
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"

curator:
  score_threshold: 7.5   # 及格线：低于 7.5 分的全部丢弃
  max_output_items: 50  # 最终保留在源里的精选文章数量
  interval_minutes: 60  # 每 60 分钟自动抓取并筛选一次

feeds:
  - name: "36氪"
    url: "https://36kr.com/feed"
  - name: "虎嗅"
    url: "https://rss.huxiu.com/"
  # 在此处添加你想筛选的源...
```

### 2. 启动容器
在 `rss_curator` 目录下执行：
```bash
docker compose up -d
```

### 3. 在 ReadYou 中订阅
容器自带轻量 Web 服务，启动后在局域网内直接访问：
```
http://<你的NAS局域网IP>:8080/feed.xml
```
（注：若需手机外出时刷新，可通过 NAS 上的反代工具如 Nginx Proxy Manager / Cloudflare Tunnel 将 8080 端口暴露到你的域名。）

---

## ☁️ 部署方式二：GitHub Actions + Pages（免服务器、零成本）

1. **新建 GitHub 仓库**：在 GitHub 上创建一个私有或公开仓库（如 `my-rss-curator`）。
2. **推送代码**：将本项目推送到该仓库。
3. **添加 API 密钥**：
   - 进入仓库设置：`Settings -> Secrets and variables -> Actions`
   - 点击 `New repository secret`，名称填写 `LLM_API_KEY`，值为你的大模型 Key。
4. **开启 GitHub Pages**：
   - 首次运行工作流后，仓库会自动生成 `gh-pages` 分支。
   - 在 `Settings -> Pages` 中，将 `Build and deployment` 的 Source 设置为 `Deploy from a branch`，分支选择 `gh-pages` / `/ (root)`。
5. **在 ReadYou 中订阅**：
   ```
   https://<你的GitHub用户名>.github.io/<仓库名>/feed.xml
   ```
   之后每隔 3 小时，GitHub 会自动拉取源、打分过滤，并更新此链接，手机无论在任何网络环境下均可稳定秒开。

---

## 🎛️ 如何精准控制每天推送的条数？

* **如果推出来的还是有点多（> 50 条）**：
  * 将 `score_threshold` 从 `7.5` 上调至 `8.0` 或 `8.5`。门槛越高，留下的越是重磅硬核长文。
* **如果推出来的偏少（< 15 条）**：
  * 将 `score_threshold` 下调至 `7.0`，放宽准入标准。
