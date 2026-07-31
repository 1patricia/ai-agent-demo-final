# 【规则引擎：敏感词、提示注入拦截】
from logger import logger

# 敏感属性黑名单（禁止AI分析的维度）
SENSITIVE_KEYWORDS = ["年龄", "性别", "婚育", "婚姻", "籍贯", "怀孕"]

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
    risk_flags = []
    inj_flag, inj_msg = check_prompt_injection(input_text)
    sen_flag, sen_msg = check_sensitive_content(input_text)
    if inj_flag:
        risk_flags.append(inj_msg)
    if sen_flag:
        risk_flags.append(sen_msg)
    return {
        "pass": len(risk_flags) == 0,
        "risk_flags": risk_flags
    }