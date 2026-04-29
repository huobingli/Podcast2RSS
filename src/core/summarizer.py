import logging
import os
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """你是一位播客内容分析师。请根据以下播客对话文稿，生成一份结构化的内容摘要。

要求：
1. **主题概述**（1段）：这期节目讨论了什么，核心议题是什么
2. **关键信息要点**（3-7条）：提炼最有价值的观点、数据、结论
3. **总结与启发**（1段）：整体结论或对听众的启发

风格：客观、精炼、信息密度高。使用中文。输出使用 Markdown 格式。"""


class Summarizer:
    """通过 DeepSeek API 调用 LLM 生成播客摘要"""

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("环境变量中未设置 DEEPSEEK_API_KEY")

        from openai import OpenAI

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
        self.model = DEFAULT_MODEL
        logger.info(f"Summarizer 初始化完成，模型: {self.model}")

    def summarize(self, title: str, transcription: List[Dict]) -> Optional[str]:
        """对转写文稿生成结构化摘要

        Args:
            title: 单集标题
            transcription: 转写结果列表，每个元素包含 time/speaker/text

        Returns:
            Markdown 格式的摘要文本，失败返回 None
        """
        if not transcription:
            logger.warning(f"转写内容为空，跳过摘要: {title}")
            return None

        # 拼接纯文本（保留说话人，去掉时间戳）
        lines = []
        for item in transcription:
            speaker = item.get("speaker", "")
            text = item.get("text", "")
            if text:
                lines.append(f"{speaker}: {text}")
        transcript_text = "\n".join(lines)

        if not transcript_text.strip():
            logger.warning(f"转写文本为空，跳过摘要: {title}")
            return None

        user_prompt = f"播客标题：{title}\n\n对话文稿：\n{transcript_text}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            summary = response.choices[0].message.content
            logger.info(f"摘要生成成功: {title}")
            return summary
        except Exception as e:
            logger.error(f"摘要生成失败: {title}, 错误: {e}")
            return None
