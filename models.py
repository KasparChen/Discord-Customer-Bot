from pydantic import BaseModel

class Problem(BaseModel):
    """
    问题反馈模型，定义问题反馈的字段和类型。
    """
    problem_type: str  # 问题类型（如功能建议、Bug 报告等）
    summary: str  # 问题简述
    source: str  # 来源（Ticket 或 General Chat）
    user: str  # 提交用户
    timestamp: str  # 时间戳
    details: str  # 详细描述
    original: str  # 原始对话内容
    is_valid: bool  # 是否有效
    id: int  # 问题 ID

class GeneralSummary(BaseModel):
    """
    对话总结模型，定义总结报告的字段和类型。
    """
    emotion: str  # 对话情绪（积极、消极、中立等）
    discussion_summary: str  # 讨论概述
    key_events: str  # 重点关注事件