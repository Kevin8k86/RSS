import os
import sys
import time
import socket
import argparse
import logging
import threading
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


def process_single_entry(entry: Any, feed_url: str, storage: Storage, evaluator: ContentEvaluator, score_threshold: float):
    link = getattr(entry, "link", "")
    guid = getattr(entry, "id", link)
    item_id = hash_id(link, guid)

    if storage.is_processed(item_id):
        return None

    title = getattr(entry, "title", "无标题").strip()
    author = getattr(entry, "author", "未知作者")
    pub_date = getattr(entry, "published", getattr(entry, "updated", ""))
    content = extract_entry_content(entry)

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
    logger.info("🚀 开始执行 RSS 抓取、深度质量筛选与今日全景速报生成任务...")
    score_threshold = float(config.get("curator", {}).get("score_threshold", 7.5))
    max_entries_per_feed = int(config.get("curator", {}).get("max_entries_per_feed", 8))
    max_workers = int(config.get("curator", {}).get("max_workers", 4))

    feeds = config.get("feeds", [])
    pending_items = []
    scanned_for_briefing = []

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
                    pending_items.append((entry, feed_url))

        except Exception as e:
            logger.error(f"❌ 读取源 {feed_url} 异常: {str(e)}")

    logger.info(f"⚡ 待处理新增深度文章: {len(pending_items)} 篇，启动 {max_workers} 线程并发评估...")

    total_accepted = 0
    total_rejected = 0

    if pending_items:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(process_single_entry, entry, feed_url, storage, evaluator, score_threshold)
                for entry, feed_url in pending_items
            ]
            for f in as_completed(futures):
                res = f.result()
                if res is True:
                    total_accepted += 1
                elif res is False:
                    total_rejected += 1

    # 1. Generate lead panoramic briefing article (置顶全景速览：一眼扫完全天热点)
    logger.info("📝 正在使用大模型生成【今日各领域全景速览·一眼扫完】置顶文章...")
    briefing_html = evaluator.generate_panoramic_briefing(scanned_for_briefing)

    bj_time = datetime.now(timezone(timedelta(hours=8)))
    period_label = "早报" if bj_time.hour < 12 else ("午报" if bj_time.hour < 15 else "晚报")
    # Use exact timestamp & hash in guid so ReadYou always refreshes fresh content instead of holding old cache
    briefing_guid = f"briefing_{bj_time.strftime('%Y%m%d_%H%M%S')}_{hash_id(briefing_html)[:8]}"
    briefing_info = {
        "title": f"📰 【今日全景速报】一分钟看全天下事 ({bj_time.strftime('%m-%d')} {period_label})",
        "guid": briefing_guid,
        "link": config.get("output", {}).get("feed_link", "https://github.com/Kevin8k86/RSS"),
        "content": briefing_html,
    }

    # 2. Clean up old records in DB
    storage.cleanup_old_records(days=45)

    # 3. Retrieve accepted in-depth articles
    max_items = int(config.get("curator", {}).get("max_output_items", 50))
    accepted_articles = storage.get_recent_accepted(limit=max_items)

    out_cfg = config.get("output", {})
    xml_content = generate_rss_xml(
        feed_title=out_cfg.get("feed_title", "AI 深度精选专栏 (Daily Digest)"),
        feed_description=out_cfg.get("feed_description", "由大模型把关筛选的优质长文与行业洞察"),
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
        f" 成功生成置顶全景速览并已写入: {out_file_path}"
    )


def start_http_server(directory: str, port: int = 8080):
    """Start a lightweight HTTP server in a separate thread to serve the feed."""
    os.chdir(directory)

    class CustomHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), CustomHandler)
    logger.info(f"🌐 本地静态 Web 服务已在后台启动: http://0.0.0.0:{port}/feed.xml")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="RSS AI Curator - 智能深度资讯筛选器")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--run-once", action="store_true", help="Run once and exit (for GitHub Actions / Cron)")
    parser.add_argument("--daemon", action="store_true", help="Run as a daemon with built-in scheduler and web server")
    parser.add_argument("--port", type=int, default=8080, help="Port for the built-in HTTP server in daemon mode")
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config.get("storage", {}).get("db_path", "curator.db")
    storage = Storage(db_path=db_path)

    llm_cfg = config.get("llm", {})
    evaluator = ContentEvaluator(
        api_key=llm_cfg.get("api_key", ""),
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
        model=llm_cfg.get("model", "deepseek-chat"),
    )

    if args.run_once:
        run_curation_task(config, storage, evaluator)
        return

    if args.daemon:
        interval_min = int(config.get("curator", {}).get("interval_minutes", 60))
        out_dir = Path(config.get("output", {}).get("output_file", "dist/feed.xml")).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        server_thread = threading.Thread(
            target=start_http_server,
            args=(str(out_dir.resolve()), args.port),
            daemon=True,
        )
        server_thread.start()

        run_curation_task(config, storage, evaluator)

        logger.info(f"⏰ 已设置定时轮询任务：每隔 {interval_min} 分钟自动执行一次。")
        schedule.every(interval_min).minutes.do(run_curation_task, config, storage, evaluator)

        while True:
            schedule.run_pending()
            time.sleep(10)
    else:
        run_curation_task(config, storage, evaluator)


if __name__ == "__main__":
    main()
