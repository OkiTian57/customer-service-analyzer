#!/usr/bin/env python3
"""
客服对话结构化信息提取工具 v2
优化点：
1. LLM 切换为 LongCat（节省千问余额）
2. 转人工判断改为场景理解，不用关键词匹配
"""

import json
import re
from pathlib import Path

import requests

from schema import ExtractionResult

# --- 动态读取 openclaw.json 配置 ---
def load_config():
    import json
    with open(Path.home() / ".openclaw" / "openclaw.json") as f:
        d = json.load(f)
    lc = d["models"]["providers"]["longCat"]
    return {
        "api_key": lc["apiKey"],
        "base_url": lc["baseUrl"],
        "model": "LongCat-2.0-Preview"
    }

_cfg = load_config()
API_KEY = _cfg["api_key"]
API_URL = _cfg["base_url"] + "/v1/chat/completions"
MODEL = _cfg["model"]


def build_system_prompt() -> str:
    """系统 prompt：强化场景上下文，不用关键词判断"""
    return """你是客服数据分析师，专门从客服对话中提取结构化信息。

## 你的工作场景
用户正在联系电商平台客服。你要分析这段完整的客服对话，判断用户的真实意图、情绪变化、客服处理质量。

## 核心规则
1. 只输出 JSON，不要任何解释或 markdown 格式
2. JSON 必须合法，能被标准 JSON 解析器解析
3. 字段取值必须严格遵循枚举值
4. 没有的信息用空字符串、空数组或 null，不要编造
5. **所有判断必须基于对话实际内容，不要推断对话之外的情况**

## 字段定义（重点说明易误判字段）

### was_transferred（是否转人工）
**判断标准**：
- 对话中**明确出现**智能客服和人工客服的交接行为
- 例如：用户说"转人工"，然后系统/客服回复"已为您转接人工客服XXX"
- 或者对话里有两个不同客服名称，且出现了转接说明
- **仅仅是用户等待时间长、抱怨服务慢，不算转人工**
- **用户从头到尾只和一个客服对话，没有转接环节，was_transferred = false**

### tags（标签）
- **转人工**：只有 was_transferred = true 时才打这个标签
- **情绪爆发**：用户有强烈情绪（大量感叹号、辱骂、威胁），不是一般的抱怨
- **沉默用户**：用户只说了"你好"之类，没有明确诉求
- **仅咨询**：纯咨询类，无售后诉求
- **多诉求**：用户问了多个不相关的问题
- **信息缺失**：用户没有提供必要信息（如不记得订单号）
- **话题切换**：对话中途换了话题
- **重复投诉**：用户提到之前也遇到过类似问题
- **流失风险**：用户明确表示要去别家、不再购买
- **产品建议**：用户提出建议

### sentiment（情绪）
- initial：用户第一条消息的情绪
- final：对话结束时用户的情绪
- 选项：angry, frustrated, neutral, satisfied, happy

### churn_risk（流失风险）
- has_risk：用户有明确的流失表示（"去别家买了"、"不再来了"）
- 一般的抱怨、不满，不算流失风险

### issues（诉求列表）
- 如果用户问了多个不相关的问题，拆成多个 issue
- issue_category 必须是：退款/退货、换货/补发、订单查询、物流问题、账户安全、商品咨询、优惠券/活动、产品建议、投诉/抱怨、其他
"""


def build_user_prompt(conversation: dict) -> str:
    """为单条对话构造提取 prompt"""
    turns_text = ""
    for i, turn in enumerate(conversation["turns"], 1):
        role = "用户" if turn["role"] == "user" else "客服"
        content = turn["content"]
        turns_text += f"{i}. [{role}] {content}\n"

    return f"""请从以下客服对话中提取结构化信息。

## 对话信息
- 对话ID：{conversation["id"]}
- 渠道：{conversation.get("channel", "未知")}
- 客服：{conversation.get("agent", "未知")}

## 对话内容
{turns_text}

## 输出要求
严格按照以下 JSON 结构输出，不要省略任何字段：
{{
  "conversation_id": "{conversation['id']}",
  "channel": "{conversation.get('channel', '')}",
  "agent_name": "{conversation.get('agent', '')}",
  "turn_count": {len(conversation.get('turns', []))},
  "issues": [
    {{
      "issue_id": 1,
      "issue_summary": "...",
      "issue_category": "...",
      "resolution": "...",
      "is_resolved": true,
      "resolution_type": "已解决",
      "compensation": "无"
    }}
  ],
  "sentiment": {{
    "initial": "neutral",
    "final": "neutral",
    "sentiment_shift": "..."
  }},
  "churn_risk": {{
    "has_risk": false,
    "risk_level": null,
    "risk_reason": ""
  }},
  "agent_performance": {{
    "response_quality": 3,
    "response_quality_reason": "...",
    "was_transferred": false,
    "proactive_compensation": false
  }},
  "entities": {{
    "order_numbers": [],
    "product_names": [],
    "phone_numbers": [],
    "amounts": []
  }},
  "tags": [],
  "manager_note": ""
}}

## 特别注意
1. was_transferred 的判断：只有对话中**明确出现**转接行为才为 true
2. 不要推断对话之外的情况，只基于实际对话内容判断
3. 情绪变化要真实反映用户在对话中的情绪走向"""


def parse_llm_output(content: str) -> dict:
    """从 LLM 输出中提取 JSON"""
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    json_match = re.search(r'(\{.*\})', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    return json.loads(content)


def validate_result(data: dict) -> ExtractionResult:
    """校验并转换结果（LongCat 可能返回中文枚举值，需要映射）"""
    # 映射 resolution_type 中文 -> 英文/标准值
    RESOLUTION_MAP = {
        "已解决": "已解决", "待跟进": "待跟进", "用户放弃": "用户放弃",
        "转其他部门": "转其他部门", "未解决": "未解决",
        "处理中": "待跟进", "进行中": "待跟进"
    }
    for issue in data.get("issues", []):
        rt = issue.get("resolution_type", "")
        if rt in RESOLUTION_MAP:
            issue["resolution_type"] = RESOLUTION_MAP[rt]

    # 映射 risk_level 中文 -> 英文
    RISK_MAP = {"高": "high", "中": "medium", "低": "low"}
    cr = data.get("churn_risk", {})
    if cr.get("risk_level") in RISK_MAP:
        cr["risk_level"] = RISK_MAP[cr["risk_level"]]

    return ExtractionResult(**data)


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    """调用 LongCat API"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    content = data["choices"][0]["message"]["content"]
    return parse_llm_output(content)


def process_conversation(conv: dict) -> dict:
    """处理单条对话"""
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(conv)

    result = call_llm(system_prompt, user_prompt)

    # 确保基础字段正确
    result["conversation_id"] = conv["id"]
    result["channel"] = conv.get("channel", "")
    result["agent_name"] = conv.get("agent", "")
    result["turn_count"] = len(conv.get("turns", []))

    # 校验
    validated = validate_result(result)
    return validated.model_dump(mode="json")


def main():
    # 读取对话数据
    data_path = Path(__file__).parent.parent / "data" / "conversations.json"
    with open(data_path, "r", encoding="utf-8") as f:
        conversations = json.load(f)

    print(f"共 {len(conversations)} 条对话需要处理（模型：{MODEL}）\n")

    results = []
    errors = []

    for i, conv in enumerate(conversations, 1):
        print(f"[{i}/{len(conversations)}] {conv['id']} ... ", end="", flush=True)
        try:
            result = process_conversation(conv)
            results.append(result)
            print("✅")
        except Exception as e:
            errors.append({"id": conv["id"], "error": str(e)})
            print(f"❌ {e}")

    # 保存结果
    output = {
        "meta": {
            "total": len(conversations),
            "success": len(results),
            "failed": len(errors),
            "model": MODEL
        },
        "errors": errors,
        "data": results
    }

    output_path = Path(__file__).parent.parent / "output" / "extraction_results_v2.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n完成：成功 {len(results)}/{len(conversations)}")
    print(f"结果保存到：{output_path}")


if __name__ == "__main__":
    main()
