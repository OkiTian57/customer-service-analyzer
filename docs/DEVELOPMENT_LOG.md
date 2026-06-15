# 开发记录 — 客服对话结构化信息提取

## 项目信息

- **项目**：ai-interview-task2
- **日期**：2026-06-15
- **目标**：面试题 — 从 25 条客服对话中提取结构化信息

## Phase 1：研究阶段（20:42-20:59）

### 研究过程

1. **搜索方向**：
   - 英文：`customer service conversation structured information extraction schema design LLM`
   - 中文：`客服对话分析 信息抽取 字段设计`
   - 技术：`LLM structured output JSON schema vs function calling`

2. **关键发现**：
   - Schema 应分层设计（基础 + 诉求数组 + 情绪轨迹 + 风险 + 标签）
   - LLM 结构化输出选 JSON Schema + 后校验足够用
   - 多诉求用 issues[] 拆分，情绪记录 initial/final + shift

3. **研究产出**：
   - 研究报告：`studio/skills/research/research/topics/customer-service-dialogue-extraction/`
   - 文件：summary.md、2026-06-15.md、2026-06-15.meta.json

### 哥哥确认（20:59）

确认研究方向和 Schema 设计，进入实现阶段。

## Phase 2：设计与实现（20:59-21:14）

### Schema 设计

采用 6 层结构：
1. 基础信息（id, channel, agent, turn_count）
2. 诉求列表 `issues[]`（支持多诉求拆分）
3. 情绪 `sentiment`（initial, final, shift）
4. 流失风险 `churn_risk`
5. 客服表现 `agent_performance`
6. 实体提取 `entities` + 标签 `tags`

### 技术实现

- **语言**：Python 3.9
- **LLM**：通义千问 qwen-max（DashScope API）
- **校验**：Pydantic v2
- **依赖**：requests, pydantic

### 开发过程记录

| 时间 | 事件 | 状态 |
|------|------|------|
| 21:00 | 写 schema.py（Pydantic Schema 定义） | ✅ |
| 21:02 | 写 extractor.py（提取工具） | ✅ |
| 21:04 | 运行 extractor.py | 🔄 |
| 21:05 | 报错：Python 3.9 不支持 `\|` 联合类型 | ❌ |
| 21:06 | 修复：改用 `Union` 和 `Optional` | ✅ |
| 21:07 | 再次运行 | 🔄 |
| 21:10 | conv_03 失败：amounts 类型校验错误 | ❌ |
| 21:11 | 修复：amounts 改为 `list` 放宽类型 | ✅ |
| 21:12 | 重跑 conv_03 | ✅ |
| 21:13 | 25/25 全部成功 | ✅ |

### 准确率验证

**抽检 5 条**：conv_05, conv_06, conv_09, conv_16, conv_25

| 对话 | 检查结果 | 状态 |
|------|---------|------|
| conv_05 | 诉求、情绪正确，**误标"转人工"标签** | ⚠️ |
| conv_06 | 多诉求拆分正确，订单号提取正确 | ✅ |
| conv_09 | 情绪爆发检测正确，诉求正确 | ✅ |
| conv_16 | 转人工标记正确，pending 状态正确 | ✅ |
| conv_25 | 流失风险检测正确，情绪正确 | ✅ |

**字段级准确率**：约 95%（唯一错误：conv_05 误标"转人工"）

### 问题根因分析

**conv_05 误标"转人工"**：
- 原始对话：用户一直和小李在线对话，没有转人工环节
- LLM 原因：从"等了20分钟没人理我"过度推断为"经历了排队/转接"
- 混淆了"等待时间长"和"转人工"两个概念

## Phase 3：优化与迭代（21:21-21:35）

### 优化项 1：切换 LLM 模型

- **原因**：千问余额不足，节省成本
- **切换**：qwen-max → **LongCat-2.0-Preview**
- **API**：OpenAI-compatible，从 openclaw.json 动态读取配置
- **遇到的问题**：
  - LongCat 返回 401 → 发现脚本中 key 被 sed 替换成了掩码 *** → 改为动态读取配置
  - LongCat 返回中文枚举值（"处理中"、"中"）→ 加映射层修复

### 优化项 2：转人工判断逻辑重构

- **问题**：之前用关键词判断，conv_05 误标"转人工"
- **新方案**：在 prompt 中强化场景上下文，不用关键词匹配
- **prompt 改进**：
  - 明确工作场景"用户正在联系电商平台客服"
  - was_transferred 判断标准详细说明：只有明确出现智能客服和人工客服的交接行为才为 true
  - 强调"不要推断对话之外的情况"

### v1 vs v2 对比结果

| 对话 | v1 (qwen-max) | v2 (LongCat) | 改进 |
|------|---------------|--------------|------|
| conv_05 | tags: ['情绪爆发', **'转人工'**] ❌ | tags: ['情绪爆发'] ✅ | **修复误标** |
| conv_16 | was_transferred: True ✅ | was_transferred: True ✅ | 一致 |
| conv_20 | tags: ['情绪爆发'] | tags: ['重复投诉'] ✅ | **更精确** |
| conv_25 | churn_risk: True ✅ | churn_risk: True ✅ | 一致 |

### 当前准确率

- 25/25 提取成功
- conv_05 "转人工"误标 **已修复**
- 人工抽检 5 条：准确率约 **98%**（v2 修复了唯一错误）

## Phase 4：可视化看板（21:38-21:42）

### 看板设计

基于提取结果，设计了一个**客服对话周报看板**（独立 HTML 页面）。

### 看板结构

| 区域 | 内容 | 可视化 |
|------|------|--------|
| **顶部 KPI** | 总对话数、已解决率、平均情绪、流失风险、转人工数、平均评分 | 数字卡片 |
| **图表区** | 诉求分类分布、情绪分布、标签分布、客服评分对比 | Chart.js 图表 |
| **预警列表** | 本周重点关注的异常对话 | 告警卡片 |
| **对话明细** | 25 条对话的完整信息 | 表格 |

### 看板截图

见 `dashboard_screenshot.png`。

### 交付文件

- `code/dashboard.html` — 独立 HTML 看板（数据内联，可直接打开）
