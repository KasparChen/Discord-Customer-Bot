import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import logging
from dotenv import load_dotenv
import datetime
from config_manager import ConfigManager
from utils import get_conversation, is_ticket_channel
from llm_analyzer import analyze_conversation
from telegram_bot import TelegramBot

# 设置日志，记录到文件和控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MODEL_ID = os.getenv('MODEL_ID')
LLM_API_KEY = os.getenv('LLM_API_KEY')
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'

# 初始化配置管理器和 Discord Bot
config_manager = ConfigManager()
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 全局变量
bot_start_time = datetime.datetime.now(datetime.timezone.utc)
ticket_creation_times = {}

# Discord Bot 就绪事件
@bot.event
async def on_ready():
    logger.info(f'Discord Bot 成功登录为 {bot.user}')
    try:
        await bot.tree.sync()
        logger.info("斜杠命令已成功同步到 Discord")
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")

# 监听消息事件，处理 Ticket 频道
@bot.event
async def on_message(message):
    if message.author == bot.user or message.created_at < bot_start_time:
        return
    guild_id = str(message.guild.id)
    config = config_manager.get_guild_config(guild_id)
    if is_ticket_channel(message.channel, config):
        if message.channel.id not in ticket_creation_times:
            ticket_creation_times[message.channel.id] = message.created_at
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))
        logger.info(f"处理消息，频道: {message.channel.name}")
        asyncio.create_task(process_message(message, guild_id))
    await bot.process_commands(message)

# 自动分析 Ticket 频道（1小时后）
async def auto_analyze_ticket(channel, guild_id):
    await asyncio.sleep(3600)  # 等待1小时
    conversation = await get_conversation(channel)
    problem = analyze_conversation(conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    if problem and problem['is_valid']:
        problem['id'] = await config_manager.get_next_problem_id()
        telegram_users = config_manager.config.get('telegram_users', {})
        for tg_user, settings in telegram_users.items():
            if guild_id in settings.get('guild_ids', []):
                logger.info(f"自动分析发送问题 {{DC server ID: {guild_id} | ID: {problem['id']} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
                await telegram_bot.send_problem_form(problem, settings['tg_channel_id'])
    else:
        logger.info(f"频道 {channel.name} 不构成有效问题")

# 实时消息处理（可扩展）
async def process_message(message, guild_id):
    pass

# 权限检查
def is_allowed(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])
    if interaction.user.guild_permissions.administrator:
        return True
    return any(interaction.user.get_role(role_id) for role_id in allowed_roles)

# 斜杠命令：设置 Ticket 类别 ID
@bot.tree.command(name="set_ticket_cate", description="设置 Ticket 类别 ID（用逗号分隔）")
@app_commands.describe(category_ids="Ticket 类别 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def set_ticket_cate(interaction: discord.Interaction, category_ids: str):
    guild_id = str(interaction.guild.id)
    try:
        ids = [int(id.strip()) for id in category_ids.split(',')]
        await config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)
        logger.info(f"设置 Ticket 类别 ID: {ids}")
        await interaction.response.send_message(f'Ticket 类别 ID 已设置为: {ids}', ephemeral=True)
    except ValueError:
        logger.error("设置 Ticket 类别 ID 输入错误")
        await interaction.response.send_message("输入错误，请提供有效的类别 ID（用逗号分隔）。", ephemeral=True)

# 斜杠命令：获取服务器 ID
@bot.tree.command(name="get_server_id", description="获取当前 Discord 服务器 ID")
@app_commands.check(is_allowed)
async def get_server_id(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    logger.info(f"执行 /get_server_id，返回服务器 ID: {guild_id}")
    await interaction.response.send_message(f'当前 Discord 服务器 ID: {guild_id}', ephemeral=True)

# 斜杠命令：手动触发分析
@bot.tree.command(name="msg_warp", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_allowed)
async def msg_warp(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    if not is_ticket_channel(channel, config_manager.get_guild_config(guild_id)):
        await interaction.response.send_message("只能在 Ticket 频道中使用", ephemeral=True)
        return
    conversation = await get_conversation(channel)
    problem = analyze_conversation(conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    problem['id'] = await config_manager.get_next_problem_id()
    telegram_users = config_manager.config.get('telegram_users', {})
    for tg_user, settings in telegram_users.items():
        if guild_id in settings.get('guild_ids', []):
            logger.info(f"手动分析发送问题 {{DC server ID: {guild_id} | ID: {problem['id']} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
            await telegram_bot.send_problem_form(problem, settings['tg_channel_id'])
    await interaction.response.send_message(f"问题反馈已生成并同步，ID: {problem['id']}", ephemeral=True)

# 斜杠命令：设置 Telegram 频道
@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    guild_id = str(interaction.guild.id)
    config_manager.config.setdefault('guilds', {}).setdefault(guild_id, {})['tg_channel_id'] = tg_channel_id
    await config_manager.save_config()
    logger.info(f"服务器 {guild_id} 设置 Telegram 推送频道为: {tg_channel_id}")
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}', ephemeral=True)

# 斜杠命令：设置允许角色
@bot.tree.command(name="set_access", description="设置允许使用 Bot 命令的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)
async def set_access(interaction: discord.Interaction, role: discord.Role):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id not in allowed_roles:
        allowed_roles.append(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)
        logger.info(f"服务器 {guild_id} 添加允许身份组: {role.name}")
        await interaction.response.send_message(f'已允许身份组 {role.name} 使用命令', ephemeral=True)
    else:
        await interaction.response.send_message(f'身份组 {role.name} 已有权限', ephemeral=True)

# 初始化 Telegram Bot
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot)

# 主程序
async def main():
    logger.info("启动 Discord Bot...")
    logger.info("启动 Telegram Bot...")
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),
        telegram_bot.run()
    )

if __name__ == "__main__":
    asyncio.run(main())