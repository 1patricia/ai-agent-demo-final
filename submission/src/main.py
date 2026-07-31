import json
import time
from pydantic import ValidationError
from schema import EvidenceOutput, EvidenceItem, ConfidenceLevel
from rules import pre_filter
from prompt_template import build_prompt
from logger import logger
from config import (
    LLM_MODE, OLLAMA_MODEL,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL,
    MAX_TOKENS, TEMPERATURE,
)

# 模板占位文本黑名单（精确匹配删除）
TEMPLATE_PLACEHOLDERS = [
    "候选人编号", "支持证据", "反向证据",
    "材料名称及原文片段", "尚未验证的候选人自述",
    "当前证据缺口", "针对缺口的行为面试题",
    "流程、隐私或证据风险",
]


def _extract_json(raw: str) -> str:
    """从 LLM 原始回复中提取纯净 JSON 字符串，含残缺自动补全和无引号键名修复。"""
    import re

    def _repair(json_str: str) -> str:
        """修复常见 JSON 错误：非法转义 → 双反斜杠，null→[]，无引号键名 → 加引号，截断 → 补全 } ] " """
        # 0. 清洗 Q3 量化模型的非法 JSON 转义
        json_str = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_str)
        # 0.5. null → []
        array_fields = [
            "supporting_evidence", "counter_evidence",
            "unverified_claims", "evidence_gaps",
            "recommended_interview_questions", "risk_flags",
            "evidence_by_criterion",
        ]
        for field in array_fields:
            json_str = re.sub(
                rf'"{field}"\s*:\s*null',
                f'"{field}": []',
                json_str,
            )
        # 1. 修复无引号键名（MULTILINE）
        json_str = re.sub(
            r'^(\s*)([a-zA-Z_]\w*)\s*:',
            r'\1"\2":',
            json_str,
            flags=re.MULTILINE,
        )
        # 2. 修复 { 或 , 紧邻的键
        json_str = re.sub(
            r'([\{,])\s*([a-zA-Z_]\w*)\s*:',
            r'\1 "\2":',
            json_str,
        )
        # 3. 计数未闭合的 {} 和 []
        open_braces = json_str.count("{") - json_str.count("}")
        open_brackets = json_str.count("[") - json_str.count("]")
        # 4. 截断的字符串值
        in_string = False
        for ch in json_str:
            if ch == '"':
                in_string = not in_string
        if in_string:
            json_str += '"'
        # 5. 补全
        json_str += "]" * open_brackets
        json_str += "}" * open_braces
        return json_str

    # 优先匹配 markdown 代码块
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = md_match.group(1).strip() if md_match else None

    if candidate is None:
        start = raw.find("{")
        if start == -1:
            return raw.strip()
        depth = 0
        end = start
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        candidate = raw[start:end].strip()

    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return _repair(candidate)


def _build_fallback(candidate_id: str, risk_flags: list[str]) -> EvidenceOutput:
    """构建标准兜底结构。"""
    fallback_item = EvidenceItem(
        criterion="异常兜底",
        supporting_evidence=[],
        counter_evidence=[],
        evidence_source="输入解析失败，原始材料无法读取",
        confidence=ConfidenceLevel.LOW,
    )
    risk_flags.append("模型输出格式异常，无原始证据溯源")
    return EvidenceOutput(
        candidate_id=candidate_id,
        evidence_by_criterion=[fallback_item],
        unverified_claims=[],
        evidence_gaps=["大模型输出校验未通过，请人工复核全部材料"],
        recommended_interview_questions=[],
        risk_flags=risk_flags,
        human_decision_required=True,
    )


def _post_process(result: EvidenceOutput, original_candidate_id: str) -> EvidenceOutput:
    """后置规则校验：修复 ID 幻觉、清除模板占位、null→[] 兜底。"""
    # 1. 强制还原 candidate_id，消除模型篡改幻觉
    result.candidate_id = original_candidate_id

    # 2. 清除模板占位文本
    for tmpl in TEMPLATE_PLACEHOLDERS:
        result.unverified_claims = [c for c in result.unverified_claims if tmpl not in c]
        result.evidence_gaps = [c for c in result.evidence_gaps if tmpl not in c]
        result.recommended_interview_questions = [c for c in result.recommended_interview_questions if tmpl not in c]
        result.risk_flags = [c for c in result.risk_flags if tmpl not in c]

    # 3. null→[] 兜底（_repair 已做，此处二次保障）
    for attr in ["unverified_claims", "evidence_gaps", "recommended_interview_questions", "risk_flags"]:
        if getattr(result, attr, None) is None:
            setattr(result, attr, [])

    return result


def _call_llm(prompt: str) -> str:
    """
    统一 LLM 调用入口，双模式兼容。
    返回模型原始输出字符串（raw_content）。
    """
    if LLM_MODE == "deepseek":
        # ---- DeepSeek 云端 API（OpenAI 兼容接口） ----
        from openai import OpenAI
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,       # 推理模型需额外空间，覆盖 reasoning_tokens 开销
            temperature=TEMPERATURE,
        )
        return response.choices[0].message.content or ""

    else:
        # ---- 本地 Ollama 推理（默认） ----
        import ollama
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "temperature": TEMPERATURE,
                "num_ctx": 4096,
                "num_predict": MAX_TOKENS,
            },
        )
        return response["message"]["content"] or ""


def run_analysis(candidate_id: str, candidate_text: str) -> EvidenceOutput:
    """
    核心分析函数：
    1. 前置过滤（脱敏不终止）
    2. 调用 LLM（Ollama 本地 / DeepSeek 云端，由 .env 中 LLM_MODE 控制）
    3. model_validate_json + _post_process 后置修复
    """
    # ---- 第一层：前置过滤（脱敏不终止） ----
    filter_result = pre_filter(candidate_text)
    pre_risk_flags = list(filter_result["risk_flags"])  # 复制，用于最终输出
    desensitized_text = filter_result["desensitized_text"]

    # ---- 第二层：LLM 调用（Ollama 本地 / DeepSeek 云端，单次推理） ----
    prompt = build_prompt(desensitized_text)
    # [注释] 重试机制已验证生效但加剧 OOM，注释保留代码留待硬件升级后恢复
    # max_retries = 1
    # for attempt in range(max_retries + 1):
    try:
        raw_content = _call_llm(prompt)
        # [注释] 以下为原重试逻辑，注释保留
        # try:
        #     json_str = _extract_json(raw_content)
        #     json.loads(json_str)
        #     break
        # except json.JSONDecodeError:
        #     if attempt < max_retries:
        #         logger.warning(f"{candidate_id} JSON 解析失败，重试...")
        #         time.sleep(3)
        #     else:
        #         logger.error(...)
        #         return _build_fallback(...)
    except Exception as e:
        logger.error(f"{candidate_id} LLM 调用异常: {e}")
        return _build_fallback(
            candidate_id,
            pre_risk_flags + ["LLM 服务调用失败，离线故障降级"],
        )

    # ---- 第三层：JSON 提取 + Pydantic 强校验 + 后置修复 ----
    json_str = _extract_json(raw_content)
    try:
        result = EvidenceOutput.model_validate_json(json_str)
        logger.info(f"{candidate_id} 分析完成，校验通过")
        # 后置规则修复
        result = _post_process(result, candidate_id)
        # 合并前置风险标记
        if pre_risk_flags:
            for flag in pre_risk_flags:
                if flag not in result.risk_flags:
                    result.risk_flags.append(flag)
        return result
    except ValidationError as e:
        error_details: list[str] = []
        for err in e.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            msg = err.get("msg", "")
            error_details.append(f"字段 [{loc}]: {msg}")
        logger.error(f"{candidate_id} JSON 校验失败: {error_details}")
        return _build_fallback(
            candidate_id,
            pre_risk_flags + [
                "LLM 输出结构校验失败",
                f"校验错误数: {len(e.errors())}",
                *error_details,
            ],
        )
    except json.JSONDecodeError as e:
        logger.error(f"{candidate_id} JSON 解析失败: {e}")
        return _build_fallback(
            candidate_id,
            pre_risk_flags + ["LLM 输出非合法 JSON，无法解析"],
        )


def batch_run(test_case_path: str, output_path: str):
    """批量运行测试用例（仅逐条手动使用，不建议全量循环）。"""
    with open(test_case_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    output_list = []
    for i, case in enumerate(cases):
        if i > 0:
            time.sleep(5)  # 推理间隔，CPU 散热
        cid = case["candidate_id"]
        text = case["candidate_text"]
        res = run_analysis(cid, text)
        output_list.append(res.model_dump())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_list, f, ensure_ascii=False, indent=2)
    logger.info(f"批量评测完成，共 {len(cases)} 条，结果写入 {output_path}")


if __name__ == "__main__":
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    batch_run(
        test_case_path=str(_root / "tests" / "test_cases.json"),
        output_path=str(_root / "evaluation" / "results.json"),
    )
