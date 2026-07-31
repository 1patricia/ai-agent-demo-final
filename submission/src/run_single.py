"""单条用例运行脚本：支持按 candidate_id 指定运行"""
import json, sys, os, time

sys.path.insert(0, os.path.dirname(__file__))
from main import run_analysis, TEMPLATE_PLACEHOLDERS

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cases_path = os.path.join(_root, "tests", "test_cases.json")
out_path = os.path.join(_root, "evaluation", "results.json")

cases = json.load(open(cases_path, "r", encoding="utf-8"))

# 支持命令行指定 candidate_id，否则运行全部
target_id = sys.argv[1] if len(sys.argv) > 1 else None
target_index = int(sys.argv[2]) if len(sys.argv) > 2 else None

results = []
for i, c in enumerate(cases):
    cid = c["candidate_id"]
    if target_id and cid != target_id:
        continue
    if target_index is not None and i != target_index:
        continue

    t = c["_type"]
    print(f"\n=== [{cid}] {t} ===", flush=True)

    try:
        r = run_analysis(cid, c["candidate_text"])
        d = r.model_dump()
        results.append(d)

        ok_id = d["candidate_id"] == cid
        list_fields = ["unverified_claims","evidence_gaps","recommended_interview_questions","risk_flags"]
        ok_null = all(isinstance(d.get(k), list) for k in list_fields)
        has_tmpl = any(tmpl in str(v) for tmpl in TEMPLATE_PLACEHOLDERS
                       for k, v in d.items() if isinstance(v, list))
        is_fallback = any(item.get("criterion") == "异常兜底"
                         for item in d.get("evidence_by_criterion", []))

        print(json.dumps(d, ensure_ascii=False, indent=2), flush=True)
        print(f"  [ID:{ok_id}] [null:{ok_null}] [模板:{not has_tmpl}] [兜底:{is_fallback}]", flush=True)
    except Exception as e:
        print(f"  FAIL: {e}", flush=True)
        results.append({"candidate_id": cid, "_type": t, "_error": str(e)})

print(f"\n=== 完成，共运行 {len(results)} 条 ===", flush=True)
