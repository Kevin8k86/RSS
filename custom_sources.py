import re
import json
import logging
import urllib.request
from typing import List, Dict, Any

logger = logging.getLogger("RSSCurator.CustomSources")

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class PseudoEntry:
    """Simulates a feedparser entry object for custom scraped items."""
    def __init__(self, title: str, link: str, summary: str, source: str, author: str = ""):
        self.title = title
        self.link = link
        self.id = link
        self.summary = summary
        self.description = summary
        self.author = author or source
        self.published = ""
        self.updated = ""
        self.source = source


def fetch_github_trending(limit: int = 10) -> List[PseudoEntry]:
    """Fetch GitHub daily trending repositories directly without external dependencies."""
    url = "https://github.com/trending"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    entries = []
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            html = res.read().decode("utf-8")
        
        articles = re.findall(r'<article class="Box-row"[\s\S]*?</article>', html)
        for art in articles[:limit]:
            repo_m = re.search(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', art)
            if not repo_m:
                continue
            repo = repo_m.group(1)
            desc_m = re.search(r'<p class="col-9 color-fg-muted my-1[^\"]*">\s*([\s\S]*?)\s*</p>', art)
            desc = re.sub(r"\s+", " ", desc_m.group(1)).strip() if desc_m else "暂无项目描述"
            lang_m = re.search(r'<span itemprop="programmingLanguage">([^<]+)</span>', art)
            lang = lang_m.group(1).strip() if lang_m else "Markdown/Other"
            stars_today_m = re.search(r'([0-9,]+)\s+stars today', art)
            stars_today = stars_today_m.group(1) if stars_today_m else "0"

            title = f"{repo} ({lang}, 今日 +{stars_today} Stars)"
            link = f"https://github.com/{repo}"
            content = f"""<p><b>【GitHub 今日热门仓库】</b>: <a href="{link}">{repo}</a></p>
<p><b>核心语言</b>: {lang} | <b>今日新增</b>: +{stars_today} Stars</p>
<p><b>项目简介</b>: {desc}</p>
<p><b>项目主页</b>: <a href="{link}">{link}</a></p>"""

            entries.append(PseudoEntry(
                title=title,
                link=link,
                summary=content,
                source="GitHub Trending",
                author="GitHub Trending"
            ))
        logger.info(f"✅ 成功抓取 GitHub Trending 热门仓库 {len(entries)} 个")
    except Exception as e:
        logger.error(f"❌ 抓取 GitHub Trending 失败: {str(e)}")
    return entries


def fetch_makerworld_trending(limit: int = 10) -> List[PseudoEntry]:
    """Fetch trending 3D models from Bambu Lab MakerWorld API."""
    url = f"https://api.bambulab.com/v1/search-service/select/design2?limit={limit}&offset=0&order=trending"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Origin": "https://makerworld.com",
            "Referer": "https://makerworld.com/",
            "Accept": "application/json"
        }
    )
    entries = []
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            data = json.loads(res.read().decode("utf-8"))
        hits = data.get("hits", [])
        for h in hits[:limit]:
            title = h.get("title", "未命名模型").strip()
            m_id = h.get("id")
            link = f"https://makerworld.com/zh/models/{m_id}"
            downloads = h.get("downloadCount", 0)
            likes = h.get("likeCount", 0)
            prints = h.get("printCount", 0)
            creator = h.get("designCreator", {}).get("name", "MakerWorld创客")
            tags_list = h.get("tags", [])[:5]
            tags = ", ".join(tags_list) if tags_list else "3D打印"
            cover = h.get("cover", "")

            title_str = f"{title} (下载 {downloads} / 打印 {prints})"
            content = f"""<p><b>【拓竹热门 3D 模型】</b>: <a href="{link}">{title}</a></p>
<p><b>创作者</b>: {creator} | <b>下载量</b>: {downloads} | <b>打印量</b>: {prints} | <b>点赞</b>: {likes}</p>
<p><b>分类标签</b>: {tags}</p>"""
            if cover:
                content = f'<p><img src="{cover}" style="max-width: 100%; border-radius: 8px;" /></p>' + content
            content += f'<p><b>模型详情与切片下载</b>: <a href="{link}">{link}</a></p>'

            entries.append(PseudoEntry(
                title=title_str,
                link=link,
                summary=content,
                source="MakerWorld 3D模型",
                author=creator
            ))
        logger.info(f"✅ 成功抓取 MakerWorld 热门 3D 模型 {len(entries)} 个")
    except Exception as e:
        logger.error(f"❌ 抓取 MakerWorld 模型失败: {str(e)}")
    return entries
