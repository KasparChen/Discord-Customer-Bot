import discord
from discord.ext import commands
import asyncio
import threading
from dotenv import load_dotenv
import os
import logging
from config_manager import ConfigManager
from utils import get_conversation, is_ticket_channel
from llm_analyzer import analyze_conversation
from telegram_bot import TelegramBot

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

# 初始化配置管理器
config_manager = ConfigManager()

# Discord Bot 设置
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
discord_bot = commands.Bot(command_prefix='/', intents=intents)

# Telegram Bot 初始化
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, discord_bot)

@discord_bot.event
async def on_ready():
    # Discord 机器人启动时的事件
    logger.info(f'Discord Bot 成功登录为 {discord_bot.user}')
    print(f'Discord Bot 成功登录为 {discord_bot.user}')

@discord_bot.event
async def on_message(message):
    # 处理 Discord 消息
    if message.author == discord_bot.user:
        return
    guild_id = str(message.guild.id)
    config = config_manager.get_guild_config(guild_id)
    if is_ticket_channel(message.channel, config):
        logger.info(f"Discord Bot 开始处理消息，频道: {message.channel.name}")
        print(f"Discord Bot 开始处理消息，频道: {message.channel.name}")
        asyncio.create_task(process_message(message, guild_id))
    await discord_bot.process_commands(message)

async def process_message(message, guild_id):
    # 处理消息并推送问题
    try:
        conversation = await get_conversation(message.channel)
        problem = analyze_conversation(conversation, message.channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
        if problem:
            telegram_users = config_manager.config.get('telegram_users', {})
            for tg_user, settings in telegram_users.items():
                if guild_id in settings.get('guild_ids', []):
                    logger.info(f"Discord Bot 采集并发送问题 {{DC server ID: {guild_id} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
                    print(f"Discord Bot 采集并发送问题 {{DC server ID: {guild_id} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
                    await telegram_bot.send_problem_form(problem, settings['tg_channel_id'])
    except Exception as e:
        logger.error(f"处理消息时发生错误: {e}")
        print(f"处理消息时发生错误: {e}")

@discord_bot.command()
async def set_ticket_cate(ctx, *, category_ids: str):
    # 设置 Ticket 类别 ID
    guild_id = str(ctx.guild.id)
    try:
        ids = [int(id.strip()) for id in category_ids.split(',')]
        config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)
        logger.info(f"Discord Bot 设置 Ticket 类别 ID: {ids}")
        print(f"Discord Bot 设置 Ticket 类别 ID: {ids}")
        await ctx.send(f'Ticket 类别 ID 已设置为: {ids}')
    except ValueError:
        logger.error("设置 Ticket 类别 ID 输入错误")
        print("设置 Ticket 类别 ID 输入错误")
        await ctx.send("输入错误，请提供有效的类别 ID（用逗号分隔）。")

@discord_bot.command()
async def get_server_id(ctx):
    # 获取当前 Discord 服务器 ID
    guild_id = str(ctx.guild.id)
    logger.info(f"Discord Bot 执行 /get_server_id，返回服务器 ID: {guild_id}")
    print(f"Discord Bot 执行 /get_server_id，返回服务器 ID: {guild_id}")
    await ctx.send(f'当前 Discord 服务器 ID: {guild_id}')

# 主程序
if __name__ == "__main__":
    logger.info("Discord Bot 正在启动...")
    print("Discord Bot 正在启动...")
    telegram_thread = threading.Thread(target=telegram_bot.run, daemon=True)
    telegram_thread.start()
    discord_bot.run(DISCORD_TOKEN)