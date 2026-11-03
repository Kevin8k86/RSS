import json
import re
from typing import Dict, Any, Optional
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


class ContentEvaluator:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=25.0)
        self.model = model

    def evaluate(self, title: str, content: str, score_threshold: float = 7.5) -> Dict[str, Any]:
        """
        Evaluate an article using LLM.
        Returns: {"score": float, "keep": bool, "reason": str}
        """
        clean_content = clean_text_from_html(content, max_chars=600)

        # Quick reject for ultra-short junk
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
