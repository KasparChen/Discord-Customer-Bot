from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
from models import Problem, GeneralSummary
import logging
from utils import is_ticket_channel

# 设置日志，记录 LLM 分析的运行状态和错误
logger = logging.getLogger(__name__)

def analyze_ticket_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    """
    使用 LLM 分析 Ticket 频道的对话，生成问题反馈。
    
    参数:
        conversation (list): 对话内容，包含用户、消息内容和时间戳
        channel (discord.Channel): Discord 频道对象
        guild_id (str): Discord 服务器 ID
        config (dict): 服务器配置
        llm_api_key (str): LLM API 密钥
        base_url (str): LLM API 基础 URL
        model_id (str): LLM 模型 ID
    
    返回:
        dict: 问题反馈数据，包含问题类型、简述、来源等字段
    """
    # 将对话内容格式化为字符串，方便 LLM 处理
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    
    # 初始化 LLM 客户端
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    parser = PydanticOutputParser(pydantic_object=Problem)
    
    # 系统提示，明确 LLM 的任务和要求
    system_prompt = (
        "你是一个智能助手，任务是分析 Discord Ticket 中的对话内容，判断是否构成有效问题。"
        "排除以下无效内容：不发言（空对话）、情绪性发言（如单纯抱怨、辱骂等）、广告或不相关内容。"
        "如果内容有效，请总结问题类型（如功能建议、Bug 报告等）和具体内容。如果无效，请说明原因。"
    )
    
    # 用户提示，包含格式说明和对话内容
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    
    # 调用 LLM 进行分析
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    problem = parser.parse(response.content)
    
    # 设置问题来源
    problem.source = 'Ticket' if is_ticket_channel(channel, config) else 'General Chat'
    
    logger.info(f"对话分析完成，发现问题: {problem.problem_type}")
    return problem.dict()

def analyze_general_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    """
    使用 LLM 分析 General Chat 频道的对话，生成总结报告。
    
    参数:
        conversation (list): 对话内容，包含用户、消息内容和时间戳
        channel (discord.Channel): Discord 频道对象
        guild_id (str): Discord 服务器 ID
        config (dict): 服务器配置
        llm_api_key (str): LLM API 密钥
        base_url (str): LLM API 基础 URL
        model_id (str): LLM 模型 ID
    
    返回:
        dict: 对话总结数据，包含情绪、讨论概述和重点关注事件
    """
    # 将对话内容格式化为字符串，方便 LLM 处理
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    
    # 初始化 LLM 客户端
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    parser = PydanticOutputParser(pydantic_object=GeneralSummary)
    
    # 系统提示，明确 LLM 的任务和要求
    system_prompt = (
        "你是一个智能助手，分析 Discord General Chat 对话，生成总结报告。"
        "报告应包括情绪、讨论概述和重点关注事件。"
        "情绪：判断整体情绪（积极、消极、中立等）。"
        "讨论概述：简明扼要，新闻播报风格。"
        "重点关注事件：列出需要团队关注的事件，如大量情绪性发言、产品问题、诈骗等，默认‘无’。"
    )
    
    # 用户提示，包含格式说明和对话内容
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    
    # 调用 LLM 进行分析
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    summary = parser.parse(response.content)
    
    return summary.dict()