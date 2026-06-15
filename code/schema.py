"""
Schema 定义文件
精确描述提取字段的结构和约束
"""

from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class Issue(BaseModel):
    """单个诉求"""
    issue_id: int = Field(description="诉求编号（多诉求时递增）")
    issue_summary: str = Field(description="一句话概括这个诉求")
    issue_category: Literal[
        "退款/退货", "换货/补发", "订单查询", "物流问题", "账户安全",
        "商品咨询", "优惠券/活动", "产品建议", "投诉/抱怨", "其他"
    ] = Field(description="诉求分类")
    resolution: str = Field(description="一句话概括处理结果")
    is_resolved: Union[bool, Literal["pending"]] = Field(description="是否已解决")
    resolution_type: Literal["已解决", "待跟进", "用户放弃", "转其他部门", "未解决"] = Field(description="解决方式")
    compensation: str = Field(description="补偿内容，无则写'无'")


class Sentiment(BaseModel):
    """情绪信息"""
    initial: Literal["angry", "frustrated", "neutral", "satisfied", "happy"] = Field(description="用户初始情绪")
    final: Literal["angry", "frustrated", "neutral", "satisfied", "happy"] = Field(description="用户最终情绪")
    sentiment_shift: str = Field(description="情绪变化描述，如'从愤怒到平静'")


class ChurnRisk(BaseModel):
    """流失风险"""
    has_risk: bool = Field(description="是否有流失风险")
    risk_level: Optional[Literal["high", "medium", "low"]] = Field(description="风险等级，无风险则为null")
    risk_reason: str = Field(description="风险原因，无风险则写空字符串")


class AgentPerformance(BaseModel):
    """客服表现"""
    response_quality: int = Field(ge=1, le=5, description="客服响应质量评分（1-5）")
    response_quality_reason: str = Field(description="评分理由")
    was_transferred: bool = Field(description="是否从智能客服转接过来的")
    proactive_compensation: bool = Field(description="客服是否主动提出补偿")


class Entities(BaseModel):
    """提取的实体信息"""
    order_numbers: list[str] = Field(default_factory=list, description="订单号列表")
    product_names: list[str] = Field(default_factory=list, description="商品名列表")
    phone_numbers: list[str] = Field(default_factory=list, description="手机号列表")
    amounts: list = Field(default_factory=list, description="金额列表（允许数字或字符串）")


class ExtractionResult(BaseModel):
    """单条对话的提取结果"""
    conversation_id: str = Field(description="对话ID")
    channel: str = Field(description="渠道（在线/电话/邮件等）")
    agent_name: str = Field(description="客服姓名")
    turn_count: int = Field(description="总轮数")
    issues: list[Issue] = Field(description="诉求列表，支持多诉求")
    sentiment: Sentiment = Field(description="情绪信息")
    churn_risk: ChurnRisk = Field(description="流失风险")
    agent_performance: AgentPerformance = Field(description="客服表现")
    entities: Entities = Field(description="提取的实体信息")
    tags: list[str] = Field(description="标签列表")
    manager_note: str = Field(description="给主管的备注")


# 标签枚举值（用于 prompt 和校验）
VALID_TAGS = [
    "多诉求", "转人工", "情绪爆发", "信息缺失", "话题切换",
    "重复投诉", "流失风险", "产品建议", "沉默用户", "仅咨询"
]

# Schema JSON 描述（用于 prompt）
SCHEMA_JSON = ExtractionResult.model_json_schema()
