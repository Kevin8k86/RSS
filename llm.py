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


SYSTEM_PROMPT = """你是一位挑剔且极富极客精神的资深科技主编与开源/创客观察家。
你的职责是：从海量技术资讯、GitHub开源项目、3D打印模型、商业报道与知乎精选中，挑选出最具【实操价值、技术美感、事实密度与深度认知】的优质条目。

【评审打分标准 (1.0 - 10.0 分)】：
1. 【重点保留/精选 (7.5 - 10.0 分)】：
   - GitHub 优质开源项目：解决真实生产力痛点、架构优雅、CLI/AI/跨平台生产力工具（请用中文阐明其核心定位与使用场景）。
   - 热门 3D 打印模型：结构精巧（如防脱收纳、卡扣设计、AMS多色优化、机械结构件、生活实用改装），具有直接打印价值。
   - 36氪商业科技深度：AI大模型前沿落地、硬科技突破、行业趋势深度复盘。
   - 知乎精选长文：有硬核原理解释、底层逻辑拆解、无废话的高赞干货。

2. 【普通或低质内容淘汰 (1.0 - 7.4 分)】：
   - 厂商单纯的通稿公关、价格促销、无实际代码的资料堆砌列表。
   - 缺乏创意的普通玩具模型、换汤不换药的无意义重构。
   - 情绪煽动型标题党、毫无增量事实的二手搬运。

【输出要求】：
请务必返回严格的 JSON 格式（不要包含额外的无用开场白），字段如下：
{
  "score": 8.6,
  "keep": true,
  "reason": "中文精炼概括：它是什么/核心亮点是什么，为什么值得看或用（80字以内）"
}
注意：
- 当且仅当 score >= 阈值 (通常为 7.5 分) 时，keep 为 true。
- reason 必须为地道流畅的中文，禁止套话。
"""

BRIEFING_SYSTEM_PROMPT = """你是一位懂代码、爱硬件、关注前沿商业的顶级极客早报主编。
你的任务是：根据今天抓取到的候选资讯列表，撰写一份条理分明、干货满满的【今日极客早餐速报】（纯中文精编）。

【必须完整覆盖以下 4 大核心板块，分类清晰】：
1. 🌟 【GitHub 开源黑科技与提效神器】（精选 3~4 个最亮眼的项目，讲明：项目名称与技术栈 + 解决什么具体痛点 + 适用场景）
2. 🖨️ 【热门 3D 打印模型与创客设计】（精选 2~3 个最受欢迎的模型，讲明：模型名称 + 机械/收纳结构亮点 + 拓竹/FDM打印建议）
3. 💼 【商业科技与前沿创新 (36氪)】（精选 2~3 条重磅行业观察，讲明：事件核心主体 + 商业技术影响与风向）
4. 💡 【知乎精选与深度思考】（精选 1~2 篇硬核高赞讨论，讲明：探讨的核心命题 + 底层原理解析或思维增量）

【撰写规则（严格遵守）】：
- 全文严格以通顺流畅的中文呈现（外语项目名保留原名，但功能与描述必须全中文）；
- 每条条目约 **80 ~ 110 字**，讲透事实细节与价值点，信息密度拉满；
- 【格式纯净限制】：严禁输出 <!DOCTYPE>、<html>、<head>、<style> 标签！直接输出轻量紧凑的 HTML 代码（使用 <div>、<h3>、<p>、<b>、<a> 结构），适合在 RSS 阅读器中直接优雅排版渲染。
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
        clean_content = clean_text_from_html(content, max_chars=600)

        if len(clean_content) < 20 and len(title) < 10:
            return {
                "score": 3.0,
                "keep": False,
                "reason": "内容过短，缺乏实质信息。",
            }

        user_prompt = f"""【待审项目/文章标题】：{title}
【内容摘要/详情】：
{clean_content}

请给出评分 (1.0 - 10.0) 以及是否保留 (及格线为 {score_threshold} 分)，并附上中文精炼推荐理由。严格以 JSON 格式输出。"""

        try:
            response = self._call_with_retry(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=250,
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
        for i, item in enumerate(raw_items[:45], 1):
            src = item.get("source", "资讯")
            t = item.get("title", "").strip()
            lines.append(f"{i}. [{src}] {t}")

        input_text = "\n".join(lines)
        bj_time = datetime.now(timezone(timedelta(hours=8)))
        date_str = bj_time.strftime("%Y年%m月%d日")

        user_prompt = f"""【当前时间】：{date_str} 极客早报
【今日抓取的候选项目与资讯列表】：
{input_text}

请直接输出排版优雅的 HTML 代码，撰写一份条理分明的【今日极客早餐速报】（纯中文精编）。
严格要求：
1. 【必须完整覆盖 4 大核心板块】：
   - 🌟 【GitHub 开源黑科技与提效神器】
   - 🖨️ 【热门 3D 打印模型与创客设计】
   - 💼 【商业科技与前沿创新 (36氪)】
   - 💡 【知乎精选与深度思考】
2. 每个板块精选 2~3 条最具代表性的项目/资讯，每条 80~110 字，讲透技术亮点或事实细节；
3. 全文必须为通顺流畅的中文，严禁未翻译的英文长句；
4. 严禁生成大段全局 CSS 或 <!DOCTYPE> 标签！直接生成纯净的 <div>、<h3>、<p>、<b> 结构。"""

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
                ⚠️ 大模型服务端在高峰期出现短暂排队。已为你保留今日重点资讯列表：
            </div>
            <ul>{fallback_items}</ul>
            """
