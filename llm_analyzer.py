from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
from models import Problem, GeneralSummary
import logging
from utils import is_ticket_channel
from datetime import datetime, timezone, timedelta  # 新增，用于处理时区偏移

logger = logging.getLogger(__name__)

def analyze_ticket_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id, creation_time):
    """使用 LLM 分析 Ticket 频道的对话，生成问题反馈
    参数:
        conversation: 对话列表，每个元素包含 user, content, timestamp
        channel: Discord 频道对象
        guild_id: 服务器 ID
        config: 服务器配置
        llm_api_key: LLM API Key
        base_url: LLM 基础 URL
        model_id: LLM 模型 ID
        creation_time: 频道创建时间（datetime对象）
    返回:
        problem: 问题字典，符合用户指定格式
    """
    # 将对话列表转换为文本格式，供 LLM 分析
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    
    # 初始化 LLM 客户端
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    
    # 创建 Pydantic 解析器，确保 LLM 输出符合 Problem 模型
    parser = PydanticOutputParser(pydantic_object=Problem)
    
    # 系统提示，指导 LLM 分析对话并生成结构化输出
    system_prompt = (
        "你是一个智能助手，任务是分析 Discord Ticket 中的对话内容，判断是否构成有效问题。"
        "如果内容有效，请以 JSON 格式返回以下字段："
        "- problem_type（问题类型，如功能建议、Bug 报告等）"
        "- summary（问题简述，简明扼要、一针见血）"
        "- details（问题详情，客观转述对话内容）"
        "- user（提出问题的用户）"
        "- original（原始对话内容）"
        "- is_valid（是否有效，true/false）"
        "注意：timestamp 字段将由系统提供，不需要生成。"
        "如果无效，返回 is_valid: false 并简要说明原因。"
    )
    
    # 用户提示，包含解析器格式说明和对话内容
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    
    # 调用 LLM，传入系统提示和用户提示
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    
    # 解析 LLM 的响应，生成 Problem 模型实例
    problem = parser.parse(response.content)
    
    # 设置来源（source）为频道名称
    problem.source = channel.name if is_ticket_channel(channel, config) else 'General Chat'
    
    # 获取服务器的时区偏移，默认 UTC+0
    timezone_offset = config.get('timezone', 0)
    tz = timezone(timedelta(hours=timezone_offset))  # 根据偏移量创建时区对象
    local_time = creation_time.astimezone(tz)  # 将创建时间调整为指定时区
    problem.timestamp = local_time.isoformat()  # 设置时间戳为 ISO 格式
    
    # 记录分析完成日志
    logger.info(f"对话分析完成，发现问题: {problem.problem_type}")
    
    # 返回问题字典
    return problem.dict()

def analyze_general_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    """使用 LLM 分析 General Chat 的对话，生成总结报告
    参数:
        conversation: 对话列表
        channel: Discord 频道对象
        guild_id: 服务器 ID
        config: 服务器配置
        llm_api_key: LLM API Key
        base_url: LLM 基础 URL
        model_id: LLM 模型 ID
    返回:
        summary: 总结字典
    """
    # 将对话列表转换为文本格式
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    
    # 初始化 LLM 客户端
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    
    # 创建 Pydantic 解析器，确保输出符合 GeneralSummary 模型
    parser = PydanticOutputParser(pydantic_object=GeneralSummary)
    
    # 系统提示，指导 LLM 分析 General Chat 对话
    system_prompt = (
        "你是一个智能助手，分析 Discord General Chat 对话，生成总结报告。"
        "报告应包括："
        "- emotion（整体情绪，如积极、消极、中立等）"
        "- discussion_summary（讨论概述，新闻播报风格，简明扼要）"
        "- key_events（重点关注事件，如产品问题、情绪性发言等，默认‘无’）"
    )
    
    # 用户提示，包含解析器格式说明和对话内容
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    
    # 调用 LLM
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    
    # 解析 LLM 响应，生成 GeneralSummary 模型实例
    summary = parser.parse(response.content)
    
    # 返回总结字典
    return summary.dict()