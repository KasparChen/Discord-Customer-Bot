from pydantic import BaseModel

# Ticket 问题模型
class Problem(BaseModel):
    """定义 Ticket 问题的结构化模型"""
    problem_type: str  # 问题类型，如功能建议、Bug 报告
    summary: str  # 问题简述，简明扼要
    source: str  # 来源，通常是 Ticket 频道名称
    user: str  # 提出问题的用户
    timestamp: str  # 首次发言的时间戳
    details: str  # 问题详情，客观转述对话
    original: str  # 原始对话内容
    is_valid: bool  # 是否有效
    id: int = 0  # 问题 ID，默认值为 0

# General Chat 总结模型
class GeneralSummary(BaseModel):
    """定义 General Chat 总结的结构化模型"""
    emotion: str  # 整体情绪
    discussion_summary: str  # 讨论概述
    key_events: str  # 重点关注事件