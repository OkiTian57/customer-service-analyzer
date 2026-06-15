#!/usr/bin/env python3
"""
客服对话结构化信息提取工具
使用 LLM (通义千问 qwen-max) 自动提取
"""

import json
import os
import re
from pathlib import Path

import requests
from pydantic import ValidationError

from schema import (
    ExtractionResult, Issue, Sentiment, ChurnRisk,
    AgentPerformance, Entities, VALID_TAGS
)

# --- 配置 ---
API_KEY = "your-api-key-here"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen-max"


def build_system_prompt() -> str:
    """系统 prompt：定义角色和输出约束"""
    return """你是客服数据分析师，专门从客服对话中提取结构化信息。

## 核心规则
1. 只输出 JSON，不要任何解释或 markdown 格式
2. JSON 必须合法，能被标准 JSON 解析器解析
3. 字段取值必须严格遵循枚举值
4. 没有的信息用空字符串、空数组或 null，不要编造

## 字段定义

### issues（诉求列表）
- 如果用户问了多个不相关的问题，拆成多个 issue
- issue_id 从 1 开始递增
- issue_category 必须是以下之一：退款/退货、换货/补发、订单查询、物流问题、账户安全、商品咨询、优惠券/活动、产品建议、投诉/抱怨、其他
- is_resolved: true=已解决, false=未解决, "pending"=待跟进（用字符串）
- resolution_type: 已解决、待跟进、用户放弃、转其他部门、未解决
- compensation: 有补偿写具体（如"20元优惠券"），否则写"无"

### sentiment（情绪）
- initial: 用户第一条消息的情绪
- final: 对话结束时用户的情绪
- sentiment_options: angry, frustrated, neutral, satisfied, happy
- 情绪变化描述要具体（如"从愤怒到平静"）

### churn_risk（流失风险）
- has_risk: 用户明确表示要去别家、不再购买、极度失望
- risk_level: high/medium/low，无风险则为 null
- risk_reason: 具体原因，无风险为空字符串

### agent_performance（客服表现）
- response_quality: 1-5分（1=很差，5=优秀）
- was_transferred: 是否从智能客服转接（用户说"转人工"）
- proactive_compensation: 客服主动提出补偿（不是用户要求的）

### entities（实体）
- 提取所有订单号（DD2024...）、商品名、手机号、金额
- 没有则为空数组 []

### tags（标签）
可选标签（只选真正符合的）：
- 多诉求：用户问了多个不相关问题
- 转人工：对话中要求转人工
- 情绪爆发：用户有强烈情绪表达（大量感叹号、辱骂、威胁）
- 信息缺失：用户没有提供必要信息（如不记得订单号）
- 话题切换：对话中途换了话题
- 重复投诉：用户提到之前也遇到过类似问题
- 流失风险：用户表示要离开
- 产品建议：用户提出建议
- 沉默用户：用户只说了"你好"之类没明确诉求
- 仅咨询：纯咨询类，无售后诉求

### manager_note
如果对话有异常情况，给主管写一句简短备注。正常情况写空字符串。"""


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
}}"""


def parse_llm_output(content: str) -> dict:
    """从 LLM 输出中提取 JSON"""
    # 尝试从 ```json ... ``` 中提取
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # 尝试直接找 JSON 对象
    json_match = re.search(r'(\{.*\})', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # 直接尝试解析
    return json.loads(content)


def validate_result(data: dict) -> ExtractionResult:
    """校验并转换结果"""
    # 处理 is_resolved 可能是字符串 "pending" 的情况
    for issue in data.get("issues", []):
        if issue.get("is_resolved") == "pending":
            issue["is_resolved"] = "pending"

    return ExtractionResult(**data)


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    """调用 DashScope API"""
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

    # 确保 conversation_id 正确
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

    print(f"共 {len(conversations)} 条对话需要处理\n")

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

    output_path = Path(__file__).parent.parent / "output" / "extraction_results.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n完成：成功 {len(results)}/{len(conversations)}")
    print(f"结果保存到：{output_path}")


if __name__ == "__main__":
    main()
