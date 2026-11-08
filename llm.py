import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from openai import OpenAI
from bs4 import BeautifulSoup


def clean_text_from_html(html_content: str, max_chars: int = 500) -> str:
    """Extract plain text from HTML and truncate to reduce token consumption and latency."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for s in soup(["script", "style", "nav", "footer", "aside"]):
        s.extract()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


SYSTEM_PROMPT = """你是一位挑剔且极富洞察力的资深科技与深度商业资讯主编。
你的职责是：从海量资讯中精挑细选出最具【深度、事实密度、长期参考价值】的优质单篇文章，果断淘汰低质灌水内容。

【评审打分标准 (1.0 - 10.0 分)】：
1. 【严重扣分/淘汰 (1.0 - 5.9 分)】：
   - 简单的行情波动/数字播报、无实质细节的碎片化快讯。
   - 厂商公关软文、商务合作通稿、产品促销优惠信息。
   - 情绪煽动型标题党、毫无论据的主观臆测、单纯二手搬运无任何增量分析的文章。

2. 【普通资讯 (6.0 - 7.4 分)】：
   - 常规行业新闻、重要财报基础发布，但缺乏深度挖掘或独家洞见。

3. 【重点保留/精选 (7.5 - 10.0 分)】：
   - 具有深度的行业或技术内幕调查、扎实的数据复盘。
   - 突破性技术原理拆解、系统架构演进分析。
   - 影响深远的产业战略分析、具备长期参考价值的高信息密度长文。

【输出要求】：
请务必返回严格的 JSON 格式（不要包含额外的无用开场白），字段如下：
{
  "score": 8.5,
  "keep": true,
  "reason": "简述2-3句为什么值得读，提炼其最核心的增量事实或洞察（80字以内）"
}
注意：
- 当且仅当 score >= 阈值 (通常为 7.5 分) 时，keep 为 true。
- reason 必须精炼有物，直接说明该文章的核心价值，禁止使用空话套话。
"""

BRIEFING_SYSTEM_PROMPT = """你是一位洞察敏锐的高级全景资讯总编。
你的任务是：根据今天抓取到的最新多领域权威中文资讯列表，撰写一份【今日各领域全景速览·一站看全天下事】（纯中文精编）。

【必须完整覆盖以下 6 大板块，绝不能遗漏任何一个】：
1. 🌐 【国际要闻与全球焦点】（海外重大事件、国际热点、地缘局势与全球观察）
2. 📱 【数码与前沿科技】（消费电子新品、AI大模型突破、前沿软硬件）
3. 💰 【商业与财经金融】（巨头商业战略、宏观资本市场、重磅收购或经济趋势）
4. 🎭 【文娱生活与社会热点】（热门影视文化、社会焦点民生话题、舆论热点）
5. 🌍 【时政要闻与大国动向】（权威政策通报、重大社会与制度动态）
6. ⚽ 【体育竞技综合速递】（重要赛况赛果、体坛焦点人物动态）

【每条条目的撰写规则（严格遵守）】：
- 全部内容严格以中文呈现，严禁输出任何未翻译的外语长句；
- 每个板块精选 2 条最具代表性的重大事件；
- 每条字数约 **80 ~ 110 字**，讲清：【加粗事件核心主体】 + 背景前因与讨论焦点 + 结论影响；
- 【格式纯净限制】：严禁输出 <!DOCTYPE>、<html>、<head>、<style> 标签！直接输出轻量紧凑的 HTML 代码（使用 <div>、<h3>、<p>、<b> 标签），保证 6 大板块全部完整输出，绝不截断。
"""


class ContentEvaluator:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=3)
        self.model = model

    def _call_with_retry(self, messages: List[Dict[str, str]], max_tokens: int, temperature: float = 0.2, retries: int = 3):
        last_err = None
        for attempt in range(retries):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                last_err = e
                wait_sec = (attempt + 1) * 3
                time.sleep(wait_sec)
        raise last_err

    def evaluate(self, title: str, content: str, score_threshold: float = 7.5) -> Dict[str, Any]:
        clean_content = clean_text_from_html(content, max_chars=500)

        if len(clean_content) < 30 and len(title) < 15:
            return {
                "score": 3.0,
                "keep": False,
                "reason": "内容过短，缺乏实质信息。",
            }

        user_prompt = f"""【待审文章标题】：{title}
【内容摘要/正文前序】：
{clean_content}

请给出评分 (1.0 - 10.0) 以及是否保留 (及格线为 {score_threshold} 分)，并附上精炼的推荐理由。严格以 JSON 格式输出。"""

        try:
            response = self._call_with_retry(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=200,
                retries=3,
            )
            raw_text = response.choices[0].message.content.strip()

            raw_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
            raw_text = re.sub(r"^```\s*", "", raw_text, flags=re.MULTILINE)
            raw_text = raw_text.strip()

            result = json.loads(raw_text)
            score = float(result.get("score", 5.0))
            keep = score >= score_threshold
            reason = result.get("reason", "未提供理由").strip()

            return {
                "score": score,
                "keep": keep,
                "reason": reason,
            }
        except Exception as e:
            return {
                "score": 0.0,
                "keep": False,
                "reason": f"评估异常: {str(e)}",
                "error": True,
            }

    def generate_panoramic_briefing(self, raw_items: List[Dict[str, str]]) -> str:
        if not raw_items:
            return "<p>今日暂无足够资讯生成速览。</p>"

        lines = []
        for i, item in enumerate(raw_items[:40], 1):
            src = item.get("source", "资讯")
            t = item.get("title", "").strip()
            lines.append(f"{i}. [{src}] {t}")

        input_text = "\n".join(lines)
        bj_time = datetime.now(timezone(timedelta(hours=8)))
        date_str = bj_time.strftime("%Y年%m月%d日")

        user_prompt = f"""【当前时间】：{date_str} 全景日报
【今日已收录的最新中文资讯总表】：
{input_text}

请直接输出排版优雅的 HTML 代码，撰写一份条理分明的【今日各领域全景速览】（纯中文版）。
严格要求：
1. 【必须写全全部 6 大板块】：国际要闻与全球焦点、数码与前沿科技、商业与财经金融、文娱生活与社会热点、时政要闻与大国动向、体育竞技综合速递；
2. 每个板块精选 2 条最重要事件，每条 80~110 字，讲透事实细节；
3. 全文必须为通顺流畅的中文，禁止夹杂未翻译的外语句子；
4. 严禁生成大段 CSS 样式或 <!DOCTYPE> 标签！直接生成纯净的 <div>、<h3>、<p>、<b> 结构，确保 6 大板块全部完整输出！"""

        try:
            response = self._call_with_retry(
                messages=[
                    {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=3500,
                retries=3,
            )
            html_content = response.choices[0].message.content.strip()
            html_content = re.sub(r"^```html\s*", "", html_content, flags=re.MULTILINE)
            html_content = re.sub(r"^```\s*", "", html_content, flags=re.MULTILINE)

            match = re.search(r"(<(div|h[1-6]|p|section)[\s>].*)", html_content, re.DOTALL | re.IGNORECASE)
            if match:
                html_content = match.group(1).strip()

            return html_content.strip()
        except Exception as e:
            fallback_items = "".join([f"<li style='margin-bottom:8px;'><b>[{item.get('source')}]</b> {item.get('title')}</li>" for item in raw_items[:15]])
            return f"""
            <div style="background:#fff3cd;padding:12px;border-radius:6px;border:1px solid #ffeeba;margin-bottom:12px;color:#856404;font-size:13px;">
                ⚠️ 大模型服务端在高峰期出现短暂排队（503 拥堵）。已为你保留今日重点即时资讯列表，下次定时运行将自动恢复深度长评：
            </div>
            <ul>{fallback_items}</ul>
            """
