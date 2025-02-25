from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
from models import Problem
import logging
from utils import is_ticket_channel

logger = logging.getLogger(__name__)

def analyze_conversation(conversation, channel, guild_id, config, llm_api_key, base_url, model_id):
    # 将对话转换为文本
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    
    # 初始化 LLM
    llm = ChatOpenAI(openai_api_key=llm_api_key, base_url=base_url, model=model_id)
    parser = PydanticOutputParser(pydantic_object=Problem)
    
    # 设置系统提示和用户提示
    system_prompt = "分析对话，提取问题并以 JSON 格式输出，若无问题返回空结果。"
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    
    try:
        # 调用 LLM 分析对话
        response = llm([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        problem = parser.parse(response.content)
        
        # 设置问题来源
        problem.source = 'Ticket' if is_ticket_channel(channel, config) else 'General Chat'
        logger.info(f"对话分析完成，发现问题: {problem.problem_type}")
        print(f"对话分析完成，发现问题: {problem.problem_type}")
        return problem.dict()
    except Exception as e:
        logger.error(f"LLM 分析出错: {e}")
        print(f"LLM 分析出错: {e}")
        return None