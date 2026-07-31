"""逐条评测脚本：运行 5 条用例，逐条检查关键指标，结果写入 evaluation/results.json"""
import json, time
from src.main import run_analysis

TMPL_BAD = ['候选人编号', '支持证据', '反向证据', '尚未验证', '当前证据缺口', '针对缺口', '流程、隐私或证据风险']

cases = json.load(open("tests/test_cases.json", "r", encoding="utf-8"))
results = []

for i, c in enumerate(cases):
    cid = c["candidate_id"]
    t = c["_type"]
    print(f"\n=== [{i+1}/5] {t}: {cid} ===", flush=True)

    try:
        r = run_analysis(cid, c["candidate_text"])
        d = r.model_dump()
        results.append(d)

        # 检查指标
        ok_id = d["candidate_id"] == cid
        ok_null = all(
            isinstance(d.get(k), list) and v is not None
            for k in ["unverified_claims","evidence_gaps","recommended_interview_questions","risk_flags"]
        )
        has_tmpl = any(
            tmpl in str(v)
            for tmpl in TMPL_BAD
            for k, v in d.items() if isinstance(v, list)
        )
        has_none_criterion = any(
            item.get("criterion") == "异常兜底"
            for item in d.get("evidence_by_criterion", [])
        )

        print(json.dumps(d, ensure_ascii=False, indent=2), flush=True)
        print(f"  [ID未篡改] {ok_id}  [无null] {ok_null}  [无模板占位] {not has_tmpl}  [非兜底] {not has_none_criterion}", flush=True)
    except Exception as e:
        print(f"  FAIL: {e}", flush=True)
        results.append({
            "candidate_id": cid,
            "_type": t,
            "_error": str(e)
        })

    if i < len(cases) - 1:
        print("  (冷却 10s...)", flush=True)
        time.sleep(10)

with open("evaluation/results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n=== 完成，共 {len(results)} 条结果 ===", flush=True)
