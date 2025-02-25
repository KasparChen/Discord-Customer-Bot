import discord
from discord.ext import commands
import asyncio
import datetime
import json
import os
import logging
import traceback
from dotenv import load_dotenv
import telegram
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.request import HTTPXRequest
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from pydantic import BaseModel
from langchain.output_parsers import PydanticOutputParser
import aiohttp

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 清理环境变量
if 'SSL_CERT_FILE' in os.environ:
    del os.environ['SSL_CERT_FILE']

# 加载 .env 文件
load_dotenv()

logger.info("脚本开始运行...")

# 配置项
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MODEL_ID = os.getenv('MODEL_ID')
LLM_API_KEY = os.getenv('LLM_API_KEY')
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
CONFIG_FILE = 'config.json'

# 加载配置文件
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
else:
    CONFIG = {
        'telegram_users': {},
        'guilds': {}
    }

# 保存配置文件
def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(CONFIG, f, indent=4)

# 设置 Discord Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True

# 创建 Discord Bot 实例
discord_bot = commands.Bot(command_prefix='/', intents=intents)

# 创建 Telegram Bot 实例
telegram_bot = telegram.Bot(
    token=TELEGRAM_TOKEN,
    request=HTTPXRequest(
        http_version="1.1",
        connection_pool_size=10
    )
)
logger.info("Telegram Bot 已初始化")

# 定义问题表单的结构
class Problem(BaseModel):
    problem_type: str
    summary: str
    source: str
    user: str
    timestamp: str
    details: str
    original: str

# Discord 机器人启动事件
@discord_bot.event
async def on_ready():
    logger.info(f'Discord 机器人已登录为 {discord_bot.user}')
    discord_bot.loop.create_task(periodic_analysis())
    # 启动 Telegram Bot
    discord_bot.loop.create_task(start_telegram_bot())

# Discord 事件：新频道创建
@discord_bot.event
async def on_guild_channel_create(channel):
    guild_id = str(channel.guild.id)
    config = CONFIG.get('guilds', {}).get(guild_id, {})
    if channel.category_id in config.get('ticket_category_ids', []):
        logger.info(f"检测到新 Ticket 频道: {channel.name} (ID: {channel.id}) 在类别 {channel.category_id}")
    elif channel.category_id in config.get('monitor_category_ids', []):
        logger.info(f"检测到新监控频道: {channel.name} (ID: {channel.id}) 在类别 {channel.category_id}")

# Discord 命令：设置 Ticket 类别 ID
@discord_bot.command(name='set_ticket_cate')
async def set_ticket_cate(ctx, *, category_ids: str):
    guild_id = str(ctx.guild.id)
    ids = [int(id.strip()) for id in category_ids.split(',')]
    if 'guilds' not in CONFIG:
        CONFIG['guilds'] = {}
    if guild_id not in CONFIG['guilds']:
        CONFIG['guilds'][guild_id] = {}
    CONFIG['guilds'][guild_id]['ticket_category_ids'] = ids
    save_config()
    await ctx.send(f'Ticket 类别 ID 已设置为: {ids}')

# Discord 命令：设置监控类别 ID
@discord_bot.command(name='set_monitor_categories')
async def set_monitor_categories(ctx, *, category_ids: str):
    guild_id = str(ctx.guild.id)
    ids = [int(id.strip()) for id in category_ids.split(',')]
    if 'guilds' not in CONFIG:
        CONFIG['guilds'] = {}
    if guild_id not in CONFIG['guilds']:
        CONFIG['guilds'][guild_id] = {}
    CONFIG['guilds'][guild_id]['monitor_category_ids'] = ids
    save_config()
    await ctx.send(f'监控类别 ID 已设置为: {ids}')

# Discord 命令：获取当前 Discord 服务器 ID
@discord_bot.command(name='get_server_id')
async def get_server_id(ctx):
    guild_id = ctx.guild.id
    await ctx.send(f'当前 Discord 服务器 ID: {guild_id}')

# Discord 监听消息事件
@discord_bot.event
async def on_message(message):
    if message.author == discord_bot.user:
        return

    guild_id = str(message.guild.id)
    config = CONFIG.get('guilds', {}).get(guild_id, {})

    if is_ticket_channel(message.channel, config):
        conversation = await get_conversation(message.channel)
        problem = analyze_conversation(conversation, message.channel, guild_id)
        if problem:
            for tg_user, settings in CONFIG['telegram_users'].items():
                if guild_id in settings.get('guild_ids', []):
                    await send_problem_form(problem, settings['tg_channel_id'])
    elif is_monitor_channel(message.channel, config):
        pass  # 监控频道通过定期分析处理

    await discord_bot.process_commands(message)

# 判断是否为 Ticket 频道
def is_ticket_channel(channel, config):
    return channel.category_id in config.get('ticket_category_ids', [])

# 判断是否为监控类别下的频道
def is_monitor_channel(channel, config):
    return channel.category_id in config.get('monitor_category_ids', [])

# 获取频道对话内容
async def get_conversation(channel):
    messages = []
    async for msg in channel.history(limit=50):
        messages.append({
            'user': msg.author.name,
            'content': msg.content,
            'timestamp': msg.created_at.isoformat()
        })
    return messages

# 使用 LLM 分析对话并提取问题
def analyze_conversation(conversation, channel, guild_id):
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    logger.info(f"Analyzing conversation in guild {guild_id}")

    llm = ChatOpenAI(
        openai_api_key=LLM_API_KEY,
        base_url=BASE_URL,
        model=MODEL_ID
    )

    parser = PydanticOutputParser(pydantic_object=Problem)

    system_prompt = """
    你是一个人工智能助手，负责分析 Discord 频道的对话内容，提取潜在问题，并整理为结构化格式。
    任务：
    1. 识别对话中的问题或需求。
    2. 判断问题类型（BUG、功能优化、建议）。
    3. 提取问题简述、详情和原文。
    4. 以 JSON 格式输出结果。
    如果没有明确问题，返回空结果。
    """

    user_prompt = f"""
    请分析以下对话，提取问题并按此格式输出：
    {parser.get_format_instructions()}
    
    对话内容：
    {conversation_text}
    """

    try:
        response = llm([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        problem = parser.parse(response.content)
        problem.source = 'Ticket' if is_ticket_channel(channel, CONFIG.get('guilds', {}).get(guild_id, {})) else 'General Chat'
        return problem.dict()
    except Exception as e:
        logger.error(f"LLM 分析出错: {e}")
        return None

# 发送问题表单到 Telegram
async def send_problem_form(problem, tg_channel_id):
    if problem and tg_channel_id:
        form = (
            f"**问题类型**: {problem['problem_type']}\n"
            f"**问题简述**: {problem['summary']}\n"
            f"**来源**: {problem['source']}\n"
            f"**用户**: {problem['user']}\n"
            f"**时间**: {problem['timestamp']}\n"
            f"**问题详情**: {problem['details']}\n"
            f"**问题原文**: {problem['original']}\n"
        )
        await telegram_bot.send_message(chat_id=tg_channel_id, text=form)
        logger.info(f"已发送问题表单: {problem['summary']}")

# 定期分析监控类别下的频道
async def periodic_analysis():
    while True:
        for guild_id, config in CONFIG.get('guilds', {}).items():
            guild = discord_bot.get_guild(int(guild_id))
            if not guild:
                continue
            for category_id in config.get('monitor_category_ids', []):
                category = discord.utils.get(guild.categories, id=category_id)
                if category:
                    for channel in category.text_channels:
                        since = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
                        messages = []
                        async for msg in channel.history(after=since):
                            messages.append({
                                'user': msg.author.name,
                                'content': msg.content,
                                'timestamp': msg.created_at.isoformat()
                            })
                        if messages:
                            problem = analyze_conversation(messages, channel, guild_id)
                            if problem:
                                for tg_user, settings in CONFIG['telegram_users'].items():
                                    if guild_id in settings.get('guild_ids', []):
                                        await send_problem_form(problem, settings['tg_channel_id'])
        await asyncio.sleep(7200)  # 每 2 小时运行一次

# Telegram Bot 启动函数
async def start_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('set_discord_guild', set_discord_guild))
    application.add_handler(CommandHandler('set_tg_channel', set_tg_channel))
    application.add_handler(CommandHandler('get_tg_group_id', get_tg_group_id))
    await application.initialize()
    await application.start()
    logger.info("Telegram Bot 已启动")
    await application.run_polling()

# Telegram 命令：设置监听的 Discord 服务器 ID
async def set_discord_guild(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /set_discord_guild command")
    tg_user_id = str(update.effective_user.id)
    guild_id = context.args[0]
    if tg_user_id not in CONFIG['telegram_users']:
        CONFIG['telegram_users'][tg_user_id] = {'guild_ids': [], 'tg_channel_id': ''}
    CONFIG['telegram_users'][tg_user_id]['guild_ids'].append(guild_id)
    save_config()
    await update.message.reply_text(f'已添加监听 Discord 服务器 ID: {guild_id}')

# Telegram 命令：设置 Telegram 推送频道 ID
async def set_tg_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /set_tg_channel command")
    tg_user_id = str(update.effective_user.id)
    tg_channel_id = context.args[0]
    if tg_user_id not in CONFIG['telegram_users']:
        CONFIG['telegram_users'][tg_user_id] = {'guild_ids': [], 'tg_channel_id': ''}
    CONFIG['telegram_users'][tg_user_id]['tg_channel_id'] = tg_channel_id
    save_config()
    await update.message.reply_text(f'已设置 Telegram 推送频道: {tg_channel_id}')

# Telegram 命令：获取当前 Telegram 群组/频道 ID
async def get_tg_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /get_tg_group_id command")
    chat_id = update.effective_chat.id
    await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')

# 主函数：仅运行 Discord，Telegram 在 on_ready 中启动
if __name__ == "__main__":
    try:
        discord_bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"主程序发生错误: {e}")
        traceback.print_exc()