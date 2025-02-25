from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
from models import Problem  # 问题模型
import logging
from utils import is_ticket_channel  # 导入 is_ticket_channel 函数

logger = logging.getLogger(__name__)

# 分析对话内容并返回问题反馈
def analyze_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    # 将对话内容格式化为字符串
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    # 初始化 LLM 模型
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    parser = PydanticOutputParser(pydantic_object=Problem)  # 使用 Pydantic 解析器
    # 系统提示，指导 LLM 分析对话
    system_prompt = (
        "你是一个智能助手，任务是分析 Discord Ticket 中的对话内容，判断是否构成有效问题。"
        "排除以下无效内容：不发言（空对话）、情绪性发言（如单纯抱怨、辱骂等）、广告或不相关内容。"
        "如果内容有效，请总结问题类型（如功能建议、Bug 报告等）和具体内容。如果无效，请说明原因。"
    )
    # 用户提示，包含对话内容和解析格式要求
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    try:
        # 调用 LLM 进行ELLM 分析
        response = llm([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        problem = parser.parse(response.content)  # 解析 LLM 返回的内容
        # 设置问题来源
        problem.source = 'Ticket' if is_ticket_channel(channel, config) else 'General Chat'
        logger.info(f"对话分析完成，发现问题: {problem.problem_type}")
        return problem.dict()  # 返回字典格式的问题数据
    except Exception as e:
        logger.error(f"LLM 分析出错: {e}")
        return None  # 分析失败返回 None