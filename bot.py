import discord
from discord.ext import commands
import asyncio
import datetime
import json
import os
import logging
import threading
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from telegram.request import HTTPXRequest
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from pydantic import BaseModel
from langchain.output_parsers import PydanticOutputParser

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MODEL_ID = os.getenv('MODEL_ID')
LLM_API_KEY = os.getenv('LLM_API_KEY')
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
CONFIG_FILE = 'config.json'

# 加载配置
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
else:
    CONFIG = {'telegram_users': {}, 'guilds': {}}

# 配置锁
config_lock = threading.Lock()

# 保存配置
def save_config():
    with config_lock:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(CONFIG, f, indent=4)

# Discord Bot 设置
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
discord_bot = commands.Bot(command_prefix='/', intents=intents)

# Telegram Bot 设置
telegram_bot = Application.builder().token(TELEGRAM_TOKEN).build()

# 问题表单结构
class Problem(BaseModel):
    problem_type: str
    summary: str
    source: str
    user: str
    timestamp: str
    details: str
    original: str

# Discord 事件
@discord_bot.event
async def on_ready():
    logger.info(f'Discord 机器人已登录为 {discord_bot.user}')
    discord_bot.loop.create_task(periodic_analysis())

@discord_bot.event
async def on_message(message):
    if message.author == discord_bot.user:
        return
    guild_id = str(message.guild.id)
    with config_lock:
        config = CONFIG.get('guilds', {}).get(guild_id, {})
    if is_ticket_channel(message.channel, config):
        conversation = await get_conversation(message.channel)
        problem = analyze_conversation(conversation, message.channel, guild_id)
        if problem:
            with config_lock:
                for tg_user, settings in CONFIG['telegram_users'].items():
                    if guild_id in settings.get('guild_ids', []):
                        await send_problem_form(problem, settings['tg_channel_id'])
    await discord_bot.process_commands(message)

# Discord 命令
@discord_bot.command()
async def set_ticket_cate(ctx, *, category_ids: str):
    guild_id = str(ctx.guild.id)
    ids = [int(id.strip()) for id in category_ids.split(',')]
    with config_lock:
        CONFIG.setdefault('guilds', {}).setdefault(guild_id, {})['ticket_category_ids'] = ids
        save_config()
    await ctx.send(f'Ticket 类别 ID 已设置为: {ids}')

# 辅助函数
def is_ticket_channel(channel, config):
    return channel.category_id in config.get('ticket_category_ids', [])

async def get_conversation(channel):
    messages = []
    async for msg in channel.history(limit=50):
        messages.append({'user': msg.author.name, 'content': msg.content, 'timestamp': msg.created_at.isoformat()})
    return messages

def analyze_conversation(conversation, channel, guild_id):
    conversation_text = "\n".join([f"{msg['user']}: {msg['content']}" for msg in conversation])
    llm = ChatOpenAI(openai_api_key=LLM_API_KEY, base_url=BASE_URL, model=MODEL_ID)
    parser = PydanticOutputParser(pydantic_object=Problem)
    system_prompt = "分析对话，提取问题并以 JSON 格式输出，若无问题返回空结果。"
    user_prompt = f"{parser.get_format_instructions()}\n对话内容：\n{conversation_text}"
    try:
        response = llm([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        problem = parser.parse(response.content)
        with config_lock:
            config = CONFIG.get('guilds', {}).get(guild_id, {})
        problem.source = 'Ticket' if is_ticket_channel(channel, config) else 'General Chat'
        return problem.dict()
    except Exception as e:
        logger.error(f"LLM 分析出错: {e}")
        return None

async def send_problem_form(problem, tg_channel_id):
    if problem and tg_channel_id:
        form = f"**问题类型**: {problem['problem_type']}\n**简述**: {problem['summary']}\n**来源**: {problem['source']}"
        await telegram_bot.bot.send_message(chat_id=tg_channel_id, text=form)

async def periodic_analysis():
    while True:
        with config_lock:
            guilds_config = CONFIG.get('guilds', {}).copy()
        for guild_id, config in guilds_config.items():
            guild = discord_bot.get_guild(int(guild_id))
            if guild:
                for category_id in config.get('monitor_category_ids', []):
                    category = discord.utils.get(guild.categories, id=category_id)
                    if category:
                        for channel in category.text_channels:
                            since = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
                            messages = [msg async for msg in channel.history(after=since)]
                            if messages:
                                problem = analyze_conversation(messages, channel, guild_id)
                                if problem:
                                    with config_lock:
                                        for tg_user, settings in CONFIG['telegram_users'].items():
                                            if guild_id in settings.get('guild_ids', []):
                                                await send_problem_form(problem, settings['tg_channel_id'])
        await asyncio.sleep(7200)

# Telegram 命令
async def set_discord_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user_id = str(update.effective_user.id)
    guild_id = context.args[0]
    with config_lock:
        CONFIG.setdefault('telegram_users', {}).setdefault(tg_user_id, {'guild_ids': [], 'tg_channel_id': ''})['guild_ids'].append(guild_id)
        save_config()
    await update.message.reply_text(f'已添加监听 Discord 服务器 ID: {guild_id}')

def run_telegram_bot():
    telegram_bot.add_handler(CommandHandler('set_discord_guild', set_discord_guild))
    telegram_bot.run_polling()

# 主程序
if __name__ == "__main__":
    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    telegram_thread.start()
    discord_bot.run(DISCORD_TOKEN)