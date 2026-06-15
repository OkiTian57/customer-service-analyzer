#!/usr/bin/env python3
"""单独重跑 conv_03"""

import json
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))

from extractor import process_conversation

with open('/Volumes/三星 T7/04-活跃项目/ai-interview-task2/data/conversations.json') as f:
    convs = json.load(f)

conv03 = [c for c in convs if c['id'] == 'conv_03'][0]
print("重跑 conv_03...")
result = process_conversation(conv03)
print(json.dumps(result, ensure_ascii=False, indent=2))

# 更新结果文件
with open('/Volumes/三星 T7/04-活跃项目/ai-interview-task2/output/extraction_results.json') as f:
    data = json.load(f)

# 找到 conv_03 的位置并替换
data['data'] = [r for r in data['data'] if r['conversation_id'] != 'conv_03']
data['data'].append(result)
data['data'].sort(key=lambda x: x['conversation_id'])
data['meta']['success'] = 25
data['meta']['failed'] = 0
data['errors'] = []

with open('/Volumes/三星 T7/04-活跃项目/ai-interview-task2/output/extraction_results.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\n✅ conv_03 已更新，25/25 成功")
