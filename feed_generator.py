import html
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
try:
    from dateutil import parser as date_parser
except ImportError:
    date_parser = None


def format_rfc822(date_str: str) -> str:
    """Format date to RFC 822 standard for RSS feeds."""
    if date_parser and date_str:
        try:
            dt = date_parser.parse(date_str)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def generate_rss_xml(
    feed_title: str,
    feed_description: str,
    feed_link: str,
    articles: List[Dict[str, Any]],
    briefing: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate RSS 2.0 XML with optional lead geek briefing article."""
    build_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    items_xml = []

    # 1. Lead Panoramic Briefing (置顶极客晨报速览：扫完 GitHub、3D打印、36氪、知乎)
    if briefing and briefing.get("content"):
        b_title = html.escape(briefing.get("title", "⚡ 【极客早报】GitHub热榜 · 3D打印 · 36氪 · 知乎"))
        b_link = html.escape(briefing.get("link", feed_link))
        b_guid = html.escape(briefing.get("guid", "briefing_today"))
        b_date = build_date
        b_content = briefing.get("content", "")

        styled_briefing_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1e293b;">
            <div style="background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #0284c7 100%); color: white; padding: 16px 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 10px rgba(15, 23, 42, 0.2);">
                <h2 style="margin: 0; font-size: 20px; font-weight: 700; color: #ffffff;">⚡ 今日极客早餐速报</h2>
                <p style="margin: 6px 0 0; font-size: 13px; color: #93c5fd; opacity: 0.95;">GitHub 热门开源 · 拓竹 3D 打印模型 · 36氪商业科技 · 知乎硬核精选</p>
            </div>
            <div>
                {b_content}
            </div>
        </div>
        """

        briefing_item = f"""
    <item>
        <title>{b_title}</title>
        <link>{b_link}</link>
        <guid isPermaLink="false">{b_guid}</guid>
        <pubDate>{b_date}</pubDate>
        <author>AI 极客主编</author>
        <description><![CDATA[{styled_briefing_html}]]></description>
    </item>"""
        items_xml.append(briefing_item)

    # 2. Individual In-depth Curated Articles (深度硬核长文与项目单篇精读)
    for art in articles:
        title = html.escape(art.get("title", "无标题"))
        link = html.escape(art.get("link", ""))
        guid = html.escape(art.get("id", link))
        author = html.escape(art.get("author", "AI Curator"))
        pub_date = format_rfc822(art.get("pub_date", art.get("created_at", "")))
        score = art.get("score", 0.0)
        recommendation = html.escape(art.get("recommendation", ""))
        original_content = art.get("original_content", "")

        # Highlight card for ReadYou webview
        curated_html = f"""
        <div style="background-color: #f8fafc; border-left: 4px solid #0284c7; padding: 12px 16px; margin-bottom: 16px; border-radius: 6px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <div style="font-weight: 700; color: #0369a1; font-size: 15px; margin-bottom: 6px;">
                🎯 AI 极客评级：{score:.1f} / 10.0
            </div>
            <div style="color: #334155; font-size: 14px; line-height: 1.6;">
                <b>【推荐看点】</b>：{recommendation}
            </div>
        </div>
        <hr style="border: none; border-top: 1px dashed #cbd5e1; margin: 18px 0;" />
        <div>
            {original_content}
        </div>
        """

        item_str = f"""
    <item>
        <title>[{score:.1f}分] {title}</title>
        <link>{link}</link>
        <guid isPermaLink="false">{guid}</guid>
        <pubDate>{pub_date}</pubDate>
        <author>{author}</author>
        <description><![CDATA[{curated_html}]]></description>
    </item>"""
        items_xml.append(item_str)

    xml_content = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
    <title>{html.escape(feed_title)}</title>
    <link>{html.escape(feed_link)}</link>
    <description>{html.escape(feed_description)}</description>
    <lastBuildDate>{build_date}</lastBuildDate>
    <generator>RSS AI Curator</generator>
    {"".join(items_xml)}
</channel>
</rss>
"""
    return xml_content
