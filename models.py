from pydantic import BaseModel

# 定义问题反馈的数据模型
class Problem(BaseModel):
    problem_type: str    # 问题类型，例如 "bug" 或 "question"
    summary: str         # 问题简述
    source: str          # 问题来源，例如 "Ticket" 或 "General Chat"
    user: str            # 提出问题的用户
    timestamp: str       # 问题的时间戳
    details: str         # 问题的详细描述
    original: str        # 原始对话内容
    is_valid: bool       # 是否有效
    id: int              # 唯一 ID