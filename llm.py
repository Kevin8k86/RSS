import json
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from openai import OpenAI
from bs4 import BeautifulSoup


def clean_text_from_html(html_content: str, max_chars: int = 600) -> str:
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

BRIEFING_SYSTEM_PROMPT = """你是一位洞察敏锐的资深全景资讯主编。
你的任务是：根据今天抓取到的各领域最新资讯列表，提炼编写一份【今日各领域资讯全景速览·一眼扫完】。

读者希望在 2 分钟内轻松扫视全天下的核心动态，请按以下 5 大类别进行分类归纳：
1. 📱 【数码与前沿科技】（消费电子新品、AI大模型进展、技术热点）
2. 💰 【商业与财经金融】（重磅商业战略、资本市场与经济动态）
3. 🎭 【文娱生活与社会热点】（影视娱乐、社会话题、民生趋势、生活趣味）
4. 🌍 【国内外时政要点】（重要政策发布、国际突发与大国动向）
5. ⚽ 【体育竞技速递】（重要赛况、体育焦点人物动态）

编写要求：
- 每个板块精选 2~4 条最重要的事件；
- 每条只能写 1~2 句话，必须【加粗关键主体与结论】，做到极度干练、一眼可扫；
- 直接输出结构清晰、色彩现代的 HTML 内容（适合手机 Material You 风格排版，使用优雅的圆角卡片与列表）。
"""


class ContentEvaluator:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
        self.model = model

    def evaluate(self, title: str, content: str, score_threshold: float = 7.5) -> Dict[str, Any]:
        """
        Evaluate an individual article using LLM.
        """
        clean_content = clean_text_from_html(content, max_chars=600)

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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=200,
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
        """
        Generate a consolidated daily panoramic briefing covering Tech, Digital, Finance, Entertainment, Politics, etc.
        """
        if not raw_items:
            return "<p>今日暂无足够资讯生成速览。</p>"

        # Compile titles and snippets (up to 40 diverse items)
        lines = []
        for i, item in enumerate(raw_items[:45], 1):
            src = item.get("source", "资讯")
            t = item.get("title", "").strip()
            lines.append(f"{i}. [{src}] {t}")

        input_text = "\n".join(lines)
        bj_time = datetime.now(timezone(timedelta(hours=8)))
        period = "早报" if bj_time.hour < 12 else ("午报" if bj_time.hour < 15 else "晚报")
        date_str = bj_time.strftime("%Y年%m月%d日")

        user_prompt = f"""【当前时间】：{date_str} {period}
【今日已收录的最新资讯总表】：
{input_text}

请为读者撰写一份结构清晰、条目精炼、两分钟内一眼能够扫完的【今日全景资讯速览】。
涵盖数码科技、商业财经、文娱与社会热点、国内外时政、体育竞技。请直接输出适合在 RSS 阅读器渲染的 HTML 片段。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=1200,
            )
            html_content = response.choices[0].message.content.strip()
            # Clean markdown code wrapper if model used it
            html_content = re.sub(r"^```html\s*", "", html_content, flags=re.MULTILINE)
            html_content = re.sub(r"^```\s*", "", html_content, flags=re.MULTILINE)
            return html_content.strip()
        except Exception as e:
            return f"<p>生成全景速览时遇到异常: {str(e)}</p>"
