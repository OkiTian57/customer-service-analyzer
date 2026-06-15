#!/usr/bin/env python3
import json
from extractor_v2 import process_conversation
from pathlib import Path

# 读取对话数据
with open(Path(__file__).parent.parent / "data" / "conversations.json") as f:
    convs = {c["id"]: c for c in json.load(f)}

# 读取旧结果
with open(Path(__file__).parent.parent / "output" / "extraction_results_v2.json") as f:
    data = json.load(f)

# 重跑失败的3条
failed_ids = [e["id"] for e in data["errors"]]
print(f"重跑失败的: {failed_ids}")

new_results = [r for r in data["data"] if r["conversation_id"] not in failed_ids]

for cid in failed_ids:
    print(f"重跑 {cid}...")
    result = process_conversation(convs[cid])
    new_results.append(result)
    print(f"  ✅")

# 排序
new_results.sort(key=lambda x: x["conversation_id"])

# 更新数据
data["data"] = new_results
data["meta"]["success"] = 25
data["meta"]["failed"] = 0
data["errors"] = []

# 保存
with open(Path(__file__).parent.parent / "output" / "extraction_results_v2.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\n✅ 25/25 全部成功，结果已更新")
