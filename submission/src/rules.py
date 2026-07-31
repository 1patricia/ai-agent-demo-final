# 【规则引擎：敏感词、提示注入拦截 —— 检测 + 脱敏，不终止流程】
import re
from logger import logger

# 敏感属性黑名单（检测但不阻断 LLM 分析）
SENSITIVE_KEYWORDS = ["年龄", "性别", "婚育", "婚姻", "籍贯", "怀孕"]

# 敏感词 → 脱敏占位，保留语义但不暴露具体值
SENSITIVE_PATTERNS = [
    (r"\d{1,3}\s*岁", "[已脱敏-年龄]"),
    (r"男[性|士|候选人]?", "[已脱敏-性别]"),
    (r"女[性|士|候选人]?", "[已脱敏-性别]"),
    (r"已婚|未婚|离异", "[已脱敏-婚育]"),
    (r"籍贯[\s：:]*\S+", "[已脱敏-籍贯]"),
    (r"怀孕|备孕|产假", "[已脱敏-婚育]"),
]

# 简单提示词注入检测
def check_prompt_injection(text: str) -> tuple[bool, str]:
    injection_words = ["直接录用", "直接通过", "忽略前面要求", "无视规则"]
    for word in injection_words:
        if word in text:
            logger.warning(f"检测提示注入：{word}")
            return True, f"风险：检测恶意指令【{word}】"
    return False, ""

# 敏感信息检测
def check_sensitive_content(text: str) -> tuple[bool, str]:
    for word in SENSITIVE_KEYWORDS:
        if word in text:
            logger.warning(f"检测敏感字段：{word}")
            return True, f"风险：包含敏感属性【{word}】"
    return False, ""

def pre_filter(input_text: str) -> dict:
    """
    前置过滤：检测 + 脱敏，不阻断流程。
    返回 {'pass': True, 'risk_flags': [...], 'desensitized_text': str}
    """
    risk_flags = []
    desensitized = input_text

    # 1. 提示词注入检测
    inj_flag, inj_msg = check_prompt_injection(input_text)
    if inj_flag:
        risk_flags.append(inj_msg)

    # 2. 敏感属性检测 + 脱敏
    sen_flag, sen_msg = check_sensitive_content(input_text)
    if sen_flag:
        risk_flags.append(sen_msg)
        # 脱敏：具体值替换为占位，保留上下文结构供 LLM 分析
        for pattern, replacement in SENSITIVE_PATTERNS:
            desensitized = re.sub(pattern, replacement, desensitized)

    return {
        "pass": True,  # 始终放行，不中断 LLM 分析
        "risk_flags": risk_flags,
        "desensitized_text": desensitized,
    }
