import ollama
import json
from pydantic import ValidationError
from schema import EvidenceOutput, EvidenceItem, ConfidenceLevel
from rules import pre_filter
from prompt_template import build_prompt
from logger import logger

# 模型配置（本地 Ollama，无付费 API）
OLLAMA_MODEL = "qwen:7b"  # 可替换为 qwen:1.8b / llama3.2 等本地模型


def _extract_json(raw: str) -> str:
    """从 LLM 原始回复中提取纯净 JSON 字符串，过滤 markdown 包裹和前置说明文字。"""
    import re
    # 优先匹配 markdown 代码块内的 JSON: ```json ... ```
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if md_match:
        return md_match.group(1).strip()
    # 回退：查找最外层 { ... } 并校验括号匹配
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
    return raw[start:end].strip()


def _build_fallback(candidate_id: str, risk_flags: list[str]) -> EvidenceOutput:
    """构建标准兜底结构，human_decision_required 固定为 True，evidence_source 保留溯源占位。"""
    #【修改：兜底溯源】异常场景必须填充 evidence_source，确保所有输出满足考题"证据可溯源"硬性要求
    fallback_item = EvidenceItem(
        criterion="异常兜底",
        supporting_evidence=[],
        counter_evidence=[],
        evidence_source="输入解析失败，原始材料无法读取",  #【修改：兜底溯源】固定占位文本
        confidence=ConfidenceLevel.LOW,
    )
    risk_flags.append("模型输出格式异常，无原始证据溯源")  #【修改：兜底溯源】追加溯源缺失说明
    return EvidenceOutput(
        candidate_id=candidate_id,
        evidence_by_criterion=[fallback_item],  #【修改：兜底溯源】空数组 → 含占位 EvidenceItem
        unverified_claims=[],
        evidence_gaps=["大模型输出校验未通过，请人工复核全部材料"],
        recommended_interview_questions=[],
        risk_flags=risk_flags,
        human_decision_required=True,
    )


def run_analysis(candidate_id: str, candidate_text: str) -> EvidenceOutput:
    """
    核心分析函数：
    1. 前置规则过滤（敏感词 / 提示注入 / 越权指令）
    2. 调用本地 Ollama 进行证据提取
    3. model_validate_json 强校验，ValidationError 不抛异常，自动追加风险
    """
    # ---- 第一层：前置规则过滤 ----
    filter_result = pre_filter(candidate_text)
    if not filter_result["pass"]:
        logger.warning(f"{candidate_id} 前置拦截触发：{filter_result['risk_flags']}")
        return _build_fallback(
            candidate_id,
            filter_result["risk_flags"] + ["前置安全拦截，未进入 LLM 分析"],
        )

    # ---- 第二层：本地 Ollama 调用 ----
    prompt = build_prompt(candidate_text)
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        raw_content = response["message"]["content"]  #【修改：旧字段替换】仅读取 LLM 返回消息体
    except Exception as e:
        logger.error(f"{candidate_id} Ollama 调用异常: {e}")
        return _build_fallback(
            candidate_id,
            ["LLM 服务调用失败，离线故障降级"],
        )

    # ---- 第三层：JSON 提取 + Pydantic 强校验 ----
    json_str = _extract_json(raw_content)
    try:
        result = EvidenceOutput.model_validate_json(json_str)
        logger.info(f"{candidate_id} 分析完成，校验通过")
        return result
    except ValidationError as e:
        # 提取缺失字段和格式错误，追加到 risk_flags，程序不崩溃
        error_details: list[str] = []
        for err in e.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            msg = err.get("msg", "")
            error_details.append(f"字段 [{loc}]: {msg}")
        logger.error(f"{candidate_id} JSON 校验失败: {error_details}")
        return _build_fallback(
            candidate_id,
            [
                "LLM 输出结构校验失败",
                f"校验错误数: {len(e.errors())}",
                *error_details,
            ],
        )
    except json.JSONDecodeError as e:
        logger.error(f"{candidate_id} JSON 解析失败: {e}")
        return _build_fallback(
            candidate_id,
            ["LLM 输出非合法 JSON，无法解析"],
        )


def batch_run(test_case_path: str, output_path: str):
    """批量运行测试用例，结果写入 evaluation/results.json。"""
    with open(test_case_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    output_list = []
    for case in cases:
        cid = case["candidate_id"]
        text = case["candidate_text"]  #【修改：旧字段替换】旧字段 "content" → "candidate_text"
        res = run_analysis(cid, text)
        output_list.append(res.model_dump())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_list, f, ensure_ascii=False, indent=2)
    logger.info(f"批量评测完成，共 {len(cases)} 条，结果写入 {output_path}")


if __name__ == "__main__":
    batch_run(
        test_case_path="../tests/test_cases.json",
        output_path="../evaluation/results.json",
    )
