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
from llm_analyzer import analyze_ticket_conversation, analyze_general_conversation
from telegram_bot import TelegramBot

# 设置日志，记录到文件和控制台，方便调试和追踪运行状态
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 从 .env 文件加载环境变量，确保敏感信息不硬编码到代码中
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord Bot Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Telegram Bot Token
MODEL_ID = os.getenv('MODEL_ID')  # LLM 模型 ID
LLM_API_KEY = os.getenv('LLM_API_KEY')  # LLM API 密钥
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'  # LLM API 基础 URL

# 初始化配置管理器，用于管理 Discord 服务器的配置（如 Ticket 频道、监控频道等）
config_manager = ConfigManager()

# 设置 Discord Bot 的 intents，确保能够接收消息和服务器事件
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 记录 Bot 启动时间，用于过滤启动前的消息
bot_start_time = datetime.datetime.now(datetime.timezone.utc)

# 用于存储 Ticket 频道的创建时间，方便后续分析
ticket_creation_times = {}

# Bot 就绪事件，启动时执行，同步斜杠命令并记录登录状态
@bot.event
async def on_ready():
    logger.info(f'Discord Bot 成功登录为 {bot.user}')
    try:
        await bot.tree.sync()  # 同步斜杠命令到 Discord
        logger.info("斜杠命令已成功同步到 Discord")
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")

# 监听消息事件，处理 Ticket 频道消息，自动分析 Ticket 或实时处理消息
@bot.event
async def on_message(message):
    # 忽略 Bot 自己的消息和启动前的消息
    if message.author == bot.user or message.created_at < bot_start_time:
        return
    guild_id = str(message.guild.id)
    config = config_manager.get_guild_config(guild_id)
    # 检查消息是否来自 Ticket 频道
    if is_ticket_channel(message.channel, config):
        # 如果是新 Ticket 频道，记录创建时间并启动自动分析
        if message.channel.id not in ticket_creation_times:
            ticket_creation_times[message.channel.id] = message.created_at
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))
        logger.info(f"处理消息，频道: {message.channel.name}")
        asyncio.create_task(process_message(message, guild_id))
    await bot.process_commands(message)

# 自动分析 Ticket 频道，1小时后执行分析并同步结果到 Telegram
async def auto_analyze_ticket(channel, guild_id):
    await asyncio.sleep(3600)  # 等待1小时
    conversation = await get_conversation(channel)  # 获取频道对话
    # 使用 LLM 分析对话，生成问题反馈
    problem = await asyncio.to_thread(analyze_ticket_conversation, conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    if problem and problem['is_valid']:
        problem['id'] = await config_manager.get_next_problem_id()  # 为问题分配唯一 ID
        tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')
        if tg_channel_id:
            await telegram_bot.send_problem_form(problem, tg_channel_id)  # 发送到 Telegram
    else:
        logger.info(f"频道 {channel.name} 不构成有效问题")

# 实时消息处理（可扩展），目前为空，未来可添加功能
async def process_message(message, guild_id):
    pass

# 权限检查，确保只有管理员或指定角色可以执行命令
def is_allowed(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])
    if interaction.user.guild_permissions.administrator:
        return True
    return any(interaction.user.get_role(role_id) for role_id in allowed_roles)

# 斜杠命令：设置 Ticket 类别 ID，用于标识 Ticket 频道
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

# 斜杠命令：获取当前 Discord 服务器 ID，方便配置
@bot.tree.command(name="get_server_id", description="获取当前 Discord 服务器 ID")
@app_commands.check(is_allowed)
async def get_server_id(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    logger.info(f"执行 /get_server_id，返回服务器 ID: {guild_id}")
    await interaction.response.send_message(f'当前 Discord 服务器 ID: {guild_id}', ephemeral=True)

# 斜杠命令：手动触发分析，生成问题反馈并同步到 Telegram
@bot.tree.command(name="msg_warp", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_allowed)
async def msg_warp(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    if not is_ticket_channel(channel, config_manager.get_guild_config(guild_id)):
        await interaction.response.send_message("只能在 Ticket 频道中使用", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    conversation = await get_conversation(channel)
    problem = await asyncio.to_thread(analyze_ticket_conversation, conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    problem['id'] = await config_manager.get_next_problem_id()
    tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')
    if tg_channel_id:
        await telegram_bot.send_problem_form(problem, tg_channel_id)
    await interaction.followup.send(f"问题反馈已生成并同步，ID: {problem['id']}", ephemeral=True)

# 斜杠命令：设置 Telegram 推送频道 ID，用于同步问题反馈
@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    guild_id = str(interaction.guild.id)
    config_manager.config.setdefault('guilds', {}).setdefault(guild_id, {})['tg_channel_id'] = tg_channel_id
    await config_manager.save_config()
    logger.info(f"服务器 {guild_id} 设置 Telegram 推送频道为: {tg_channel_id}")
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}', ephemeral=True)

# 斜杠命令：设置允许使用 Bot 命令的身份组
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

# 斜杠命令：移除允许使用 Bot 命令的身份组
@bot.tree.command(name="remove_access", description="移除允许使用 Bot 命令的身份组")
@app_commands.describe(role="要移除的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)
async def remove_access(interaction: discord.Interaction, role: discord.Role):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id in allowed_roles:
        allowed_roles.remove(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)
        await interaction.response.send_message(f'已移除身份组 {role.name} 的命令权限', ephemeral=True)
    else:
        await interaction.response.send_message(f'身份组 {role.name} 不在允许列表中', ephemeral=True)

# 斜杠命令：列出允许使用 Bot 命令的身份组
@bot.tree.command(name="list_access", description="列出允许使用 Bot 命令的身份组")
@app_commands.checks.has_permissions(administrator=True)
async def list_access(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if allowed_roles:
        roles = [interaction.guild.get_role(role_id).name for role_id in allowed_roles if interaction.guild.get_role(role_id)]
        await interaction.response.send_message(f'允许使用命令的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        await interaction.response.send_message('没有设置允许的身份组', ephemeral=True)

# 斜杠命令：设置监控的 General Chat 频道，最多5个
@bot.tree.command(name="set_monitor_channels", description="设置监控的 General Chat 频道（最多5个）")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def set_monitor_channels(interaction: discord.Interaction, channels: str):
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]
    if len(channel_ids) > 5:
        await interaction.response.send_message("最多只能设置5个频道", ephemeral=True)
        return
    await config_manager.set_guild_config(guild_id, 'monitor_channels', channel_ids)
    await interaction.response.send_message(f'已设置监控频道: {channel_ids}', ephemeral=True)

# 斜杠命令：移除监控的 General Chat 频道
@bot.tree.command(name="remove_monitor_channels", description="移除监控的 General Chat 频道")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def remove_monitor_channels(interaction: discord.Interaction, channels: str):
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]
    current_channels = config_manager.get_guild_config(guild_id).get('monitor_channels', [])
    updated_channels = [ch for ch in current_channels if ch not in channel_ids]
    await config_manager.set_guild_config(guild_id, 'monitor_channels', updated_channels)
    await interaction.response.send_message(f'已移除监控频道: {channel_ids}', ephemeral=True)

# 斜杠命令：设置监控参数，包括周期和最大消息条数
@bot.tree.command(name="set_monitor_params", description="设置监控周期和最大消息条数")
@app_commands.describe(period_hours="监控周期（小时）", max_messages="最大消息条数")
@app_commands.check(is_allowed)
async def set_monitor_params(interaction: discord.Interaction, period_hours: int, max_messages: int):
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'monitor_period', period_hours)
    await config_manager.set_guild_config(guild_id, 'monitor_max_messages', max_messages)
    await interaction.response.send_message(f'已设置监控周期为 {period_hours} 小时，最大消息条数为 {max_messages}', ephemeral=True)

# 初始化 Telegram Bot，传递 LLM 相关参数，确保可以访问
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot, LLM_API_KEY, BASE_URL, MODEL_ID)

# 主程序，启动 Discord 和 Telegram Bot
async def main():
    logger.info("启动 Discord Bot...")
    logger.info("启动 Telegram Bot...")
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),
        telegram_bot.run()
    )

if __name__ == "__main__":
    asyncio.run(main())