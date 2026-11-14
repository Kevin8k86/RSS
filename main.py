import os
import sys
import time
import socket
import argparse
import logging
import threading
import re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Any, List

import yaml
import feedparser
import schedule

from storage import Storage, hash_id
from llm import ContentEvaluator
from feed_generator import generate_rss_xml
from custom_sources import fetch_github_trending, fetch_makerworld_trending

# Set global socket timeout to prevent hanging feeds
socket.setdefaulttimeout(15)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("RSSCurator")


def load_config(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found at: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "LLM_API_KEY" in os.environ and os.environ["LLM_API_KEY"]:
        config["llm"]["api_key"] = os.environ["LLM_API_KEY"]
    if "LLM_BASE_URL" in os.environ and os.environ["LLM_BASE_URL"]:
        config["llm"]["base_url"] = os.environ["LLM_BASE_URL"]
    if "LLM_MODEL" in os.environ and os.environ["LLM_MODEL"]:
        config["llm"]["model"] = os.environ["LLM_MODEL"]

    return config


def is_mainly_chinese(text: str) -> bool:
    """Check if text contains meaningful Chinese characters (at least 3 characters)."""
    if not text:
        return False
    chinese_chars = re.findall(r"[\u4e00-\u9fa5]", text)
    return len(chinese_chars) >= 3


def extract_entry_content(entry: Any) -> str:
    """Extract richest text content from a feedparser entry."""
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].value
    elif hasattr(entry, "summary") and entry.summary:
        content = entry.summary
    elif hasattr(entry, "description") and entry.description:
        content = entry.description
    return content


def process_single_entry(
    entry: Any,
    feed_url: str,
    storage: Storage,
    evaluator: ContentEvaluator,
    score_threshold: float,
    allow_foreign: bool = False,
):
    link = getattr(entry, "link", "")
    guid = getattr(entry, "id", link)
    item_id = hash_id(link, guid)

    if storage.is_processed(item_id):
        return None

    title = getattr(entry, "title", "无标题").strip()
    author = getattr(entry, "author", "未知作者")
    pub_date = getattr(entry, "published", getattr(entry, "updated", ""))
    content = extract_entry_content(entry)

    # 仅在非极客开源/模型源且不包含中文时跳过
    if not allow_foreign and not is_mainly_chinese(title):
        logger.info(f"   ⏩ [过滤外语文章] {title[:35]}...")
        storage.save_result(
            item_id=item_id,
            feed_url=feed_url,
            title=title,
            link=link,
            author=author,
            pub_date=pub_date,
            original_content=content,
            score=0.0,
            recommendation="外语文章自动跳过",
            status="REJECTED",
        )
        return False

    logger.info(f"   🤖 [AI 评审中] {title[:35]}...")
    eval_res = evaluator.evaluate(title=title, content=content, score_threshold=score_threshold)

    score = eval_res.get("score", 0.0)
    keep = eval_res.get("keep", False)
    reason = eval_res.get("reason", "")
    status = "ACCEPTED" if keep else "REJECTED"

    if keep:
        logger.info(f"      ✅ 【入选 ({score:.1f}分)】: {reason}")
    else:
        logger.info(f"      ❌ 【淘汰 ({score:.1f}分)】: {title[:30]}")

    storage.save_result(
        item_id=item_id,
        feed_url=feed_url,
        title=title,
        link=link,
        author=author,
        pub_date=pub_date,
        original_content=content,
        score=score,
        recommendation=reason,
        status=status,
    )
    return keep


def run_curation_task(config: Dict[str, Any], storage: Storage, evaluator: ContentEvaluator):
    logger.info("🚀 开始执行极客早报抓取、深度质量筛选与今日速报生成任务...")
    score_threshold = float(config.get("curator", {}).get("score_threshold", 7.5))
    max_entries_per_feed = int(config.get("curator", {}).get("max_entries_per_feed", 12))
    max_workers = int(config.get("curator", {}).get("max_workers", 4))

    pending_items = []
    scanned_for_briefing = []

    # 1. 抓取专有特色源：GitHub Trending
    logger.info("📡 正在获取: [GitHub Trending 每日热门仓库]...")
    gh_entries = fetch_github_trending(limit=10)
    for entry in gh_entries:
        scanned_for_briefing.append({"source": "GitHub Trending", "title": entry.title})
        item_id = hash_id(entry.link, entry.id)
        if not storage.is_processed(item_id):
            pending_items.append((entry, "https://github.com/trending", True))

    # 2. 抓取专有特色源：拓竹 MakerWorld 热门 3D 模型
    logger.info("📡 正在获取: [拓竹 MakerWorld 热门 3D 模型]...")
    mw_entries = fetch_makerworld_trending(limit=10)
    for entry in mw_entries:
        scanned_for_briefing.append({"source": "MakerWorld 3D模型", "title": entry.title})
        item_id = hash_id(entry.link, entry.id)
        if not storage.is_processed(item_id):
            pending_items.append((entry, "https://makerworld.com", True))

    # 3. 抓取常规 RSS 订阅源（36氪、知乎精选等）
    feeds = config.get("feeds", [])
    for feed_info in feeds:
        feed_url = feed_info.get("url") if isinstance(feed_info, dict) else feed_info
        feed_name = feed_info.get("name", feed_url) if isinstance(feed_info, dict) else feed_url

        logger.info(f"📡 正在拉取: [{feed_name}] -> {feed_url}")
        try:
            d = feedparser.parse(
                feed_url,
                agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            entries = d.entries or []
            selected_entries = entries[:max_entries_per_feed]
            logger.info(f"   共发现 {len(entries)} 条，选取最新 {len(selected_entries)} 条加入评估队列")

            for entry in selected_entries:
                title = getattr(entry, "title", "").strip()
                if title:
                    scanned_for_briefing.append({"source": feed_name, "title": title})

                link = getattr(entry, "link", "")
                guid = getattr(entry, "id", link)
                item_id = hash_id(link, guid)
                if not storage.is_processed(item_id):
                    pending_items.append((entry, feed_url, False))

        except Exception as e:
            logger.error(f"❌ 读取源 {feed_url} 异常: {str(e)}")

    logger.info(f"⚡ 待处理新增深度项目/文章: {len(pending_items)} 篇，启动 {max_workers} 线程并发评估...")

    total_accepted = 0
    total_rejected = 0

    if pending_items:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    process_single_entry,
                    entry,
                    feed_url,
                    storage,
                    evaluator,
                    score_threshold,
                    allow_foreign,
                )
                for entry, feed_url, allow_foreign in pending_items
            ]
            for f in as_completed(futures):
                res = f.result()
                if res is True:
                    total_accepted += 1
                elif res is False:
                    total_rejected += 1

    # 4. 生成置顶极客晨报速览
    logger.info("📝 正在使用大模型生成【今日极客早餐速报】置顶卡片...")
    briefing_html = evaluator.generate_panoramic_briefing(scanned_for_briefing)

    bj_time = datetime.now(timezone(timedelta(hours=8)))
    briefing_guid = f"geek_briefing_{bj_time.strftime('%Y%m%d_%H%M%S')}_{hash_id(briefing_html)[:8]}"
    briefing_info = {
        "title": f"⚡ 【极客早报】GitHub · 3D打印 · 36氪 · 知乎精选 ({bj_time.strftime('%m-%d')} 版)",
        "guid": briefing_guid,
        "link": config.get("output", {}).get("feed_link", "https://github.com/Kevin8k86/RSS"),
        "content": briefing_html,
    }

    # 5. 清理历史旧数据
    storage.cleanup_old_records(days=45)

    # 6. 获取最近精选入库的文章/项目
    max_items = int(config.get("curator", {}).get("max_output_items", 50))
    accepted_articles = storage.get_recent_accepted(limit=max_items)

    out_cfg = config.get("output", {})
    xml_content = generate_rss_xml(
        feed_title=out_cfg.get("feed_title", "极客早报 · AI 深度精选专栏"),
        feed_description=out_cfg.get("feed_description", "大模型把关：GitHub热榜 · 3D打印模型 · 36氪 · 知乎硬核长文"),
        feed_link=out_cfg.get("feed_link", "https://github.com/Kevin8k86/RSS"),
        articles=accepted_articles,
        briefing=briefing_info,
    )

    out_file_path = Path(out_cfg.get("output_file", "dist/feed.xml"))
    out_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    logger.info(
        f"🎉 任务完成！本次精选新增 {total_accepted} 篇，淘汰 {total_rejected} 篇。"
        f" 成功生成极客晨报并已写入: {out_file_path}"
    )


def start_http_server(directory: str, port: int = 8080):
    """Start a lightweight HTTP server in a separate thread to serve the feed."""
    os.chdir(directory)
    handler = SimpleHTTPRequestHandler
    httpd = HTTPServer(("", port), handler)
    logger.info(f"🌐 本地测试预览服务已启动: http://localhost:{port}/feed.xml")
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="RSS AI 极客早报筛选系统")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--run-once", action="store_true", help="仅执行一次抓取与生成后退出")
    parser.add_argument("--serve", action="store_true", help="启动本地 Web 服务供阅读器测试")
    parser.add_argument("--port", type=int, default=8080, help="本地 Web 服务端口")
    args = parser.parse_args()

    config = load_config(args.config)

    db_path = config.get("storage", {}).get("db_path", "data/curator.db")
    storage = Storage(db_path=db_path)

    llm_cfg = config.get("llm", {})
    evaluator = ContentEvaluator(
        api_key=llm_cfg.get("api_key", ""),
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
        model=llm_cfg.get("model", "deepseek-chat"),
    )

    if args.serve:
        out_dir = Path(config.get("output", {}).get("output_file", "dist/feed.xml")).parent
        t = threading.Thread(target=start_http_server, args=(str(out_dir), args.port), daemon=True)
        t.start()

    if args.run_once:
        run_curation_task(config, storage, evaluator)
        return

    # 定时循环模式
    logger.info("⏰ 启动定时轮询调度器 (每日 07:00 自动执行)...")
    schedule.every().day.at("07:00").do(run_curation_task, config, storage, evaluator)

    # 首次启动先执行一次
    run_curation_task(config, storage, evaluator)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
