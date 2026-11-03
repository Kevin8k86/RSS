import html
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from dateutil import parser as date_parser


def format_rfc822(date_str: str) -> str:
    """Format date to RFC 822 standard for RSS feeds."""
    try:
        dt = date_parser.parse(date_str)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def generate_rss_xml(
    feed_title: str,
    feed_description: str,
    feed_link: str,
    articles: List[Dict[str, Any]],
    briefing: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate RSS 2.0 XML with optional lead panoramic briefing article."""
    build_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    items_xml = []

    # 1. Lead Panoramic Briefing (置顶全景速报：一篇文章扫完全天各大类)
    if briefing and briefing.get("content"):
        b_title = html.escape(briefing.get("title", "📰 【AI 今日全景速报】一眼看全天下事"))
        b_link = html.escape(briefing.get("link", feed_link))
        b_guid = html.escape(briefing.get("guid", "briefing_today"))
        b_date = build_date
        b_content = briefing.get("content", "")

        styled_briefing_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1e293b;">
            <div style="background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: white; padding: 14px 18px; border-radius: 8px; margin-bottom: 18px;">
                <h2 style="margin: 0; font-size: 18px; color: #ffffff;">⚡ 今日资讯全景速览</h2>
                <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.9;">涵盖科技、数码、财经、文娱与时政，两分钟一眼扫完全天热点</p>
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
        <author>AI 全能主编</author>
        <description><![CDATA[{styled_briefing_html}]]></description>
    </item>"""
        items_xml.append(briefing_item)

    # 2. Individual In-depth Curated Articles (深度硬核长文单篇精读)
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
        <div style="background-color: #f1f5f9; border-left: 4px solid #2563eb; padding: 12px 16px; margin-bottom: 16px; border-radius: 6px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
            <div style="font-weight: 700; color: #1e40af; font-size: 15px; margin-bottom: 6px;">
                🎯 AI 深度评级：{score:.1f} / 10.0
            </div>
            <div style="color: #334155; font-size: 14px; line-height: 1.6;">
                <b>【精选推荐】</b>：{recommendation}
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
    {''.join(items_xml)}
</channel>
</rss>
"""
    return xml_content.strip()
