import os
import sys
import time
import argparse
import logging
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Any

import yaml
import feedparser
import schedule

from storage import Storage, hash_id
from llm import ContentEvaluator
from feed_generator import generate_rss_xml

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

    # Support environment variable override for sensitive keys
    if "LLM_API_KEY" in os.environ:
        config["llm"]["api_key"] = os.environ["LLM_API_KEY"]
    if "LLM_BASE_URL" in os.environ:
        config["llm"]["base_url"] = os.environ["LLM_BASE_URL"]
    if "LLM_MODEL" in os.environ:
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


def run_curation_task(config: Dict[str, Any], storage: Storage, evaluator: ContentEvaluator):
    logger.info("🚀 开始执行 RSS 抓取与深度质量筛选任务...")
    score_threshold = float(config.get("curator", {}).get("score_threshold", 7.5))
    feeds = config.get("feeds", [])

    total_scanned = 0
    total_accepted = 0
    total_rejected = 0

    for feed_info in feeds:
        feed_url = feed_info.get("url") if isinstance(feed_info, dict) else feed_info
        feed_name = feed_info.get("name", feed_url) if isinstance(feed_info, dict) else feed_url

        logger.info(f"📡 正在拉取源: [{feed_name}] -> {feed_url}")
        try:
            # Set realistic User-Agent to avoid anti-scraping blocks
            d = feedparser.parse(
                feed_url,
                agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            entries = d.entries or []
            logger.info(f"   共获取到 {len(entries)} 条最新文章")

            for entry in entries:
                total_scanned += 1
                link = getattr(entry, "link", "")
                guid = getattr(entry, "id", link)
                item_id = hash_id(link, guid)

                if storage.is_processed(item_id):
                    continue

                title = getattr(entry, "title", "无标题").strip()
                author = getattr(entry, "author", "未知作者")
                pub_date = getattr(entry, "published", getattr(entry, "updated", ""))
                content = extract_entry_content(entry)

                logger.info(f"   🤖 [AI 评审中] {title[:40]}...")
                eval_res = evaluator.evaluate(title=title, content=content, score_threshold=score_threshold)

                score = eval_res.get("score", 0.0)
                keep = eval_res.get("keep", False)
                reason = eval_res.get("reason", "")
                status = "ACCEPTED" if keep else "REJECTED"

                if keep:
                    total_accepted += 1
                    logger.info(f"      ✅ 【入选 ({score:.1f}分)】: {reason}")
                else:
                    total_rejected += 1
                    logger.info(f"      ❌ 【淘汰 ({score:.1f}分)】")

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

                # Tiny throttle to respect rate limits
                time.sleep(0.3)

        except Exception as e:
            logger.error(f"❌ 读取源 {feed_url} 发生错误: {str(e)}")

    # Clean up old records in DB
    storage.cleanup_old_records(days=45)

    # Generate output RSS XML
    max_items = int(config.get("curator", {}).get("max_output_items", 50))
    accepted_articles = storage.get_recent_accepted(limit=max_items)

    out_cfg = config.get("output", {})
    xml_content = generate_rss_xml(
        feed_title=out_cfg.get("feed_title", "AI 精选深度资讯"),
        feed_description=out_cfg.get("feed_description", "由大模型把关筛选的优质长文与行业洞察"),
        feed_link=out_cfg.get("feed_link", "https://github.com"),
        articles=accepted_articles,
    )

    out_file_path = Path(out_cfg.get("output_file", "dist/feed.xml"))
    out_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    logger.info(
        f"🎉 任务完成！本次扫描新增文章，保留精选 {total_accepted} 篇，淘汰 {total_rejected} 篇。"
        f" 当前精选源总共包含 {len(accepted_articles)} 篇精品。已写入: {out_file_path}"
    )


def start_http_server(directory: str, port: int = 8080):
    """Start a lightweight HTTP server in a separate thread to serve the feed."""
    os.chdir(directory)

    class CustomHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress normal access logs to keep terminal tidy

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

        # Start background HTTP server
        server_thread = threading.Thread(
            target=start_http_server,
            args=(str(out_dir.resolve()), args.port),
            daemon=True,
        )
        server_thread.start()

        # Run immediately once
        run_curation_task(config, storage, evaluator)

        # Schedule recurring runs
        logger.info(f"⏰ 已设置定时轮询任务：每隔 {interval_min} 分钟自动执行一次。")
        schedule.every(interval_min).minutes.do(run_curation_task, config, storage, evaluator)

        while True:
            schedule.run_pending()
            time.sleep(10)
    else:
        # Default fallback to run-once
        run_curation_task(config, storage, evaluator)


if __name__ == "__main__":
    main()
