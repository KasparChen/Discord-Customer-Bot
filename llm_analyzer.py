from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
from models import Problem, GeneralSummary
import logging
from utils import is_ticket_channel

logger = logging.getLogger(__name__)

# 分析 Ticket 对话
def analyze_ticket_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    """使用 LLM 分析 Ticket 频道的对话，生成问题反馈
    参数:
        conversation: 对话列表，每个元素包含 user, content, timestamp
        channel: Discord 频道对象
        guild_id: 服务器 ID
        config: 服务器配置
        llm_api_key: LLM API Key
        base_url: LLM 基础 URL
        model_id: LLM 模型 ID
    返回:
        problem: 问题字典，符合用户指定格式
    """
    # 将对话转换为文本格式
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)  # 初始化 LLM
    parser = PydanticOutputParser(pydantic_object=Problem)  # 创建解析器，确保输出符合 Problem 模型
    # 系统提示，指导 LLM 分析对话并生成结构化输出
    system_prompt = (
        "你是一个智能助手，任务是分析 Discord Ticket 中的对话内容，判断是否构成有效问题。"
        "如果内容有效，请以 JSON 格式返回以下字段："
        "- problem_type（问题类型，如功能建议、Bug 报告等）"
        "- summary（问题简述，简明扼要、一针见血）"
        "- details（问题详情，客观转述对话内容）"
        "- user（提出问题的用户）"
        "- timestamp（频道内首次发言的时间戳）"
        "- original（原始对话内容）"
        "- is_valid（是否有效，true/false）"
        "如果无效，返回 is_valid: false 并简要说明原因。"
        "来源将由程序自动设置为 Ticket 频道名称，例如 #1234-username。"
    )
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])  # 调用 LLM
    problem = parser.parse(response.content)  # 解析 LLM 输出
    problem.source = channel.name if is_ticket_channel(channel, config) else 'General Chat'  # 设置来源为频道名
    logger.info(f"对话分析完成，发现问题: {problem.problem_type}")
    return problem.dict()  # 返回字典格式

# 分析 General Chat 对话
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
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    parser = PydanticOutputParser(pydantic_object=GeneralSummary)
    system_prompt = (
        "你是一个智能助手，分析 Discord General Chat 对话，生成总结报告。"
        "报告应包括："
        "- emotion（整体情绪，如积极、消极、中立等）"
        "- discussion_summary（讨论概述，新闻播报风格，简明扼要）"
        "- key_events（重点关注事件，如产品问题、情绪性发言等，默认‘无’）"
    )
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    summary = parser.parse(response.content)
    return summary.dict()