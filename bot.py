import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import logging
from dotenv import load_dotenv
import datetime
from config_manager import ConfigManager  # 配置管理模块
from utils import get_conversation, is_ticket_channel  # 工具函数
from llm_analyzer import analyze_conversation  # LLM 分析模块
from telegram_bot import TelegramBot  # Telegram Bot 模块

# 设置日志，记录运行信息到文件和命令行
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),  # 日志保存到 bot.log 文件
        logging.StreamHandler()          # 同时输出到命令行
    ]
)
logger = logging.getLogger(__name__)

# 加载环境变量从 .env 文件
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord Bot 的 Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Telegram Bot 的 Token
MODEL_ID = os.getenv('MODEL_ID')  # LLM 模型 ID
LLM_API_KEY = os.getenv('LLM_API_KEY')  # LLM API 密钥
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'  # LLM API 的基础 URL

# 初始化配置管理器
config_manager = ConfigManager()

# 设置 Discord Bot 的 intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 记录 Bot 启动时间
bot_start_time = datetime.datetime.now(datetime.timezone.utc)

# 用于存储 Ticket 频道的创建时间
ticket_creation_times = {}

# Bot 就绪事件，启动时执行
@bot.event
async def on_ready():
    logger.info(f'Discord Bot 成功登录为 {bot.user}')  # 记录登录成功信息
    try:
        await bot.tree.sync()  # 同步斜杠命令到 Discord
        logger.info("斜杠命令已成功同步到 Discord")
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")

# 监听消息事件，处理 Ticket 频道消息
@bot.event
async def on_message(message):
    if message.author == bot.user:  # 忽略 Bot 自己的消息
        return
    if message.created_at < bot_start_time:  # 忽略 Bot 启动前的消息
        return
    guild_id = str(message.guild.id)  # 获取服务器 ID
    config = config_manager.get_guild_config(guild_id)  # 获取服务器配置
    if is_ticket_channel(message.channel, config):  # 检查是否为 Ticket 频道
        # 如果是新 Ticket 频道，记录创建时间并安排自动分析
        if message.channel.id not in ticket_creation_times:
            ticket_creation_times[message.channel.id] = message.created_at
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))  # 1 小时后自动分析
        logger.info(f"Discord Bot 开始处理消息，频道: {message.channel.name}")
        asyncio.create_task(process_message(message, guild_id))  # 实时处理消息
    await bot.process_commands(message)  # 处理命令

# 自动分析 Ticket 频道内容（1 小时后）
async def auto_analyze_ticket(channel, guild_id):
    await asyncio.sleep(3600)  # 等待 1 小时（3600 秒）
    conversation = await get_conversation(channel)  # 获取频道对话内容
    # 调用 LLM 分析对话
    problem = analyze_conversation(conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    if problem and problem['is_valid']:  # 如果问题有效
        problem['id'] = await config_manager.get_next_problem_id()  # 生成唯一 ID
        telegram_users = config_manager.config.get('telegram_users', {})  # 获取 Telegram 用户配置
        for tg_user, settings in telegram_users.items():
            if guild_id in settings.get('guild_ids', []):  # 检查是否监听该服务器
                logger.info(f"自动分析并发送问题 {{DC server ID: {guild_id} | ID: {problem['id']} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
                await telegram_bot.send_problem_form(problem, settings['tg_channel_id'])  # 发送到 Telegram
    else:
        logger.info(f"Ticket 频道 {channel.name} 不构成有效问题")

# 实时处理消息的函数（可扩展）
async def process_message(message, guild_id):
    pass  # 当前为空，可根据需求添加实时处理逻辑

# 权限检查：命令是否允许当前用户执行
def is_allowed(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])  # 获取允许的身份组 ID
    if interaction.user.guild_permissions.administrator:  # 管理员权限
        return True
    for role_id in allowed_roles:
        if interaction.user.get_role(role_id):  # 用户拥有允许的身份组
            return True
    return False

# 斜杠命令：设置 Ticket 类别 ID
@bot.tree.command(name="set_ticket_cate", description="设置 Ticket 类别 ID（用逗号分隔）")
@app_commands.describe(category_ids="Ticket 类别 ID（用逗号分隔）")
@app_commands.check(is_allowed)  # 权限检查
async def set_ticket_cate(interaction: discord.Interaction, category_ids: str):
    guild_id = str(interaction.guild.id)
    try:
        ids = [int(id.strip()) for id in category_ids.split(',')]  # 解析输入的类别 ID
        await config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)  # 保存配置
        logger.info(f"设置 Ticket 类别 ID: {ids}")
        await interaction.response.send_message(f'Ticket 类别 ID 已设置为: {ids}', ephemeral=True)  # 回复用户
    except ValueError:
        logger.error("设置 Ticket 类别 ID 输入错误")
        await interaction.response.send_message("输入错误，请提供有效的类别 ID（用逗号分隔）。", ephemeral=True)

# 斜杠命令：获取当前服务器 ID
@bot.tree.command(name="get_server_id", description="获取当前 Discord 服务器 ID")
@app_commands.check(is_allowed)  # 权限检查
async def get_server_id(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    logger.info(f"执行 /get_server_id，返回服务器 ID: {guild_id}")
    await interaction.response.send_message(f'当前 Discord 服务器 ID: {guild_id}', ephemeral=True)

# 斜杠命令：手动触发 LLM 分析并同步到 Telegram
@bot.tree.command(name="msg_warp", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_allowed)  # 权限检查
async def msg_warp(interaction: discord.Interaction):
    channel = interaction.channel
    if not is_ticket_channel(channel, config_manager.get_guild_config(str(interaction.guild.id))):  # 检查是否为 Ticket 频道
        await interaction.response.send_message("该命令只能在 Ticket 频道中使用", ephemeral=True)
        return
    conversation = await get_conversation(channel)  # 获取对话内容
    problem = analyze_conversation(conversation, channel, str(interaction.guild.id), config_manager.get_guild_config(str(interaction.guild.id)), LLM_API_KEY, BASE_URL, MODEL_ID)
    problem['id'] = await config_manager.get_next_problem_id()  # 生成唯一 ID
    telegram_users = config_manager.config.get('telegram_users', {})  # 获取 Telegram 用户配置
    for tg_user, settings in telegram_users.items():
        if str(interaction.guild.id) in settings.get('guild_ids', []):  # 检查是否监听该服务器
            logger.info(f"手动触发分析并发送问题 {{DC server ID: {interaction.guild.id} | ID: {problem['id']} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
            await telegram_bot.send_problem_form(problem, settings['tg_channel_id'])  # 发送到 Telegram
    await interaction.response.send_message(f"问题反馈已生成并同步到 Telegram，ID: {problem['id']}", ephemeral=True)

# 斜杠命令：设置 Telegram 推送频道
@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)  # 权限检查
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    guild_id = str(interaction.guild.id)
    config_manager.config.setdefault('guilds', {}).setdefault(guild_id, {})['tg_channel_id'] = tg_channel_id
    await config_manager.save_config()  # 保存配置
    logger.info(f"服务器 {guild_id} 设置 Telegram 推送频道为: {tg_channel_id}")
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}', ephemeral=True)

# 斜杠命令：设置允许使用 Bot 命令的身份组
@bot.tree.command(name="set_access", description="设置允许使用 Bot 命令的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员
async def set_access(interaction: discord.Interaction, role: discord.Role):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id not in allowed_roles:
        allowed_roles.append(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)
        logger.info(f"服务器 {guild_id} 添加允许的身份组: {role.name}")
        await interaction.response.send_message(f'已允许身份组 {role.name} 使用 Bot 命令', ephemeral=True)
    else:
        await interaction.response.send_message(f'身份组 {role.name} 已有权限', ephemeral=True)

# 初始化 Telegram Bot
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot)

# 主程序，启动 Discord 和 Telegram Bot
async def main():
    logger.info("Discord Bot 正在启动...")
    logger.info("Telegram Bot 正在启动...")
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),  # 启动 Discord Bot
        telegram_bot.run()         # 启动 Telegram Bot
    )

if __name__ == "__main__":
    asyncio.run(main())  # 运行主程序