import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import datetime
import pytz
from config_manager import ConfigManager
from utils import get_conversation, is_ticket_channel
from llm_analyzer import analyze_ticket_conversation, analyze_general_conversation
from telegram_bot import TelegramBot

# 配置主日志记录器，使用轮转日志保存到文件并输出到控制台
handler = RotatingFileHandler(
    'bot.log',           # 日志文件路径
    maxBytes=5*1024*1024, # 单个日志文件最大 5MB
    backupCount=5         # 保留 5 个备份文件
)
logging.basicConfig(
    level=logging.INFO,   # 设置日志级别为 INFO
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 配置心跳日志记录器，单独记录 Bot 运行状态
heartbeat_logger = logging.getLogger('heartbeat')
heartbeat_handler = RotatingFileHandler(
    'heartbeat.log',     # 心跳日志文件路径
    maxBytes=5*1024*1024,
    backupCount=5
)
heartbeat_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
heartbeat_logger.addHandler(heartbeat_handler)
heartbeat_logger.setLevel(logging.INFO)

# 设置 httpx 日志级别为 WARNING，避免频繁请求污染日志
logging.getLogger("httpx").setLevel(logging.WARNING)

# 加载环境变量
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MY_ACTIVE_KEY = os.getenv('MY_ACTIVE_KEY')  # 从 .env 读取激活密钥
DEFAULT_LLM_API_KEY = os.getenv('LLM_API_KEY')
DEFAULT_MODEL_ID = os.getenv('MODEL_ID')
DEFAULT_BASE_URL = os.getenv('BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')

# 检查 MY_ACTIVE_KEY 是否配置
if not MY_ACTIVE_KEY:
    logger.error("MY_ACTIVE_KEY 未在 .env 文件中定义，请配置后重启 Bot")
    raise ValueError("MY_ACTIVE_KEY 未定义，请在 .env 文件中设置激活密钥")

# 初始化配置和 Bot
config_manager = ConfigManager()
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='/', intents=intents)
# 全局变量
bot_start_time = datetime.datetime.now(datetime.timezone.utc)  # Bot 启动时间，用于过滤旧消息
ticket_creation_times = {}  # 存储 Ticket 频道的创建时间，键为频道 ID，值为创建时间

# 检查 Bot 是否激活的装饰器，用于限制命令使用
def check_activation():
    async def predicate(interaction: discord.Interaction):
        """
        检查 Bot 是否已激活，若未激活则阻止命令执行。
        
        Args:
            interaction (discord.Interaction): Discord 交互对象
        
        Returns:
            bool: True 表示已激活，False 表示未激活并发送提示
        """
        if not config_manager.is_bot_activated():
            await interaction.response.send_message("Bot 未激活，请使用 `/activate_key` 或 `/activate_llm` 激活。", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

@bot.event
async def on_ready():
    """
    Bot 就绪事件，当 Bot 成功登录 Discord 时触发。
    - 记录登录信息并同步斜杠命令。
    """
    logger.info(f'Discord Bot 成功登录为 {bot.user}')
    try:
        synced = await bot.tree.sync()  # 将斜杠命令同步到 Discord
        logger.info(f"斜杠命令已成功同步到 Discord，同步了 {len(synced)} 个命令")
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")  # 记录同步失败的异常

@bot.event
async def on_message(message):
    """
    消息监听事件，处理每条新消息。
    - 忽略 Bot 自己的消息和启动前的消息。
    - 检查是否为 Ticket 频道并触发分析。
    """
    if message.author == bot.user or message.created_at < bot_start_time:
        return  # 跳过 Bot 自己的消息或旧消息
    guild_id = str(message.guild.id)  # 获取服务器 ID
    config = config_manager.get_guild_config(guild_id)  # 获取服务器配置
    if is_ticket_channel(message.channel, config):  # 检查是否为 Ticket 频道
        if message.channel.id not in ticket_creation_times:
            ticket_creation_times[message.channel.id] = message.created_at  # 记录新 Ticket 频道创建时间
            logger.info(f"检测到新 Ticket 频道: {message.channel.name}")
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))  # 异步启动自动分析
        logger.info(f"处理消息，频道: {message.channel.name}，发送者: {message.author.name}")
        asyncio.create_task(process_message(message, guild_id))  # 异步处理消息
    await bot.process_commands(message)  # 处理其他命令

async def auto_analyze_ticket(channel, guild_id):
    """
    自动分析 Ticket 频道，等待1小时后执行。
    - 如果 Bot 未激活，则跳过分析。
    - 使用服务器绑定的 LLM 配置或默认配置进行分析。
    
    Args:
        channel (discord.Channel): Ticket 频道对象
        guild_id (str): Discord 服务器 ID
    """
    if not config_manager.is_bot_activated():
        logger.info(f"Bot 未激活，跳过自动分析 Ticket 频道: {channel.name}")
        return
    logger.info(f"开始自动分析 Ticket 频道: {channel.name}，等待 1 小时")
    await asyncio.sleep(3600)  # 等待1小时（3600秒）
    conversation = await get_conversation(channel)  # 获取频道对话内容
    creation_time = ticket_creation_times.get(channel.id)  # 获取频道创建时间
    if creation_time:
        # 获取 LLM 配置，优先使用服务器自定义配置
        llm_config = config_manager.get_llm_config(guild_id) or {
            'api_key': DEFAULT_LLM_API_KEY,
            'model_id': DEFAULT_MODEL_ID,
            'base_url': DEFAULT_BASE_URL
        }
        # 在单独线程中运行 LLM 分析，避免阻塞主线程
        problem = await asyncio.to_thread(
            analyze_ticket_conversation, conversation, channel, guild_id,
            config_manager.get_guild_config(guild_id), llm_config['api_key'],
            llm_config['base_url'], llm_config['model_id'], creation_time
        )
        if problem and problem['is_valid']:  # 如果分析结果有效
            problem['id'] = await config_manager.get_next_problem_id()  # 分配唯一问题 ID
            tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')
            if tg_channel_id:
                await telegram_bot.send_problem_form(problem, tg_channel_id)  # 发送问题到 Telegram
                logger.info(f"问题反馈已发送到 Telegram 频道 {tg_channel_id}")
        else:
            logger.info(f"频道 {channel.name} 不构成有效问题")
    else:
        logger.error(f"无法获取频道 {channel.name} 的创建时间")

async def process_message(message, guild_id):
    """
    实时消息处理，当前为空，可根据需求扩展。
    
    Args:
        message (discord.Message): 收到的消息对象
        guild_id (str): Discord 服务器 ID
    """
    pass  # 占位符，留给未来的功能扩展

def is_allowed(interaction: discord.Interaction):
    """
    检查用户是否有权限使用命令。
    - 管理员默认有权限，其他用户需拥有配置的角色。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    
    Returns:
        bool: True 表示有权限，False 表示无权限
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])  # 获取允许的角色 ID 列表
    if interaction.user.guild_permissions.administrator:  # 检查是否为管理员
        logger.info(f"用户 {interaction.user.name} 是管理员，允许执行命令")
        return True
    has_permission = any(role.id in allowed_roles for role in interaction.user.roles)  # 检查用户角色
    logger.info(f"用户 {interaction.user.name} 检查权限，结果: {has_permission}")
    return has_permission

def is_warp_msg_allowed(interaction: discord.Interaction):
    """
    检查用户是否有权限使用 warp_msg 命令
    - 管理员默认有权限
    - 否则检查是否拥有 warp_msg_allowed_roles 中的角色
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    
    Returns:
        bool: True 表示有权限，False 表示无权限
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    warp_msg_allowed_roles = config_manager.get_warp_msg_allowed_roles(guild_id)
    if interaction.user.guild_permissions.administrator:
        logger.info(f"用户 {interaction.user.name} 是管理员，允许使用 warp_msg")
        return True
    has_permission = any(role.id in warp_msg_allowed_roles for role in interaction.user.roles)
    logger.info(f"用户 {interaction.user.name} 检查 warp_msg 权限，结果: {has_permission}")
    return has_permission

@bot.tree.command(name="activate_key", description="使用密钥激活 Bot")
@app_commands.describe(key="激活密钥")
async def activate_key(interaction: discord.Interaction, key: str):
    """
    使用固定密钥激活 Bot，使其可以使用默认 LLM 配置。
    - 密钥必须与 .env 文件中的 MY_ACTIVE_KEY 匹配。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        key (str): 用户提供的激活密钥
    """
    if await config_manager.activate_with_key(key, MY_ACTIVE_KEY):
        await interaction.response.send_message(
            "Bot 已成功激活，使用默认 LLM 配置。请妥善保管激活密钥，避免泄露。",
            ephemeral=True
        )
        logger.info(f"用户 {interaction.user.name} 使用密钥激活 Bot")
    else:
        await interaction.response.send_message(
            "密钥无效或 Bot 已激活，请检查输入或联系管理员。",
            ephemeral=True
        )
        logger.warning(f"用户 {interaction.user.name} 使用无效密钥尝试激活: {key}")

@bot.tree.command(name="activate_llm", description="使用自定义 LLM 配置激活 Bot")
@app_commands.describe(api_key="LLM API Key", model_id="模型 ID", base_url="API Base URL")
async def activate_llm(interaction: discord.Interaction, api_key: str, model_id: str, base_url: str):
    """
    使用自定义 LLM 配置激活 Bot，并绑定到当前服务器。
    - 覆盖之前的服务器 LLM 配置（如果有）。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        api_key (str): LLM API 密钥
        model_id (str): LLM 模型 ID
        base_url (str): LLM API 基础 URL
    """
    guild_id = str(interaction.guild.id)
    await config_manager.activate_with_llm_config(guild_id, api_key, model_id, base_url)
    await interaction.response.send_message(f"Bot 已激活并绑定到服务器 {interaction.guild.name} 的自定义 LLM 配置。", ephemeral=True)
    logger.info(f"用户 {interaction.user.name} 在服务器 {guild_id} 配置了自定义 LLM")

@bot.tree.command(name="set_ticket_cate", description="设置 Ticket 类别 ID")
@app_commands.describe(category_ids="Ticket 类别 ID（用逗号分隔）")
@app_commands.check(is_allowed)
@check_activation()
async def set_ticket_cate(interaction: discord.Interaction, category_ids: str):
    """
    设置服务器的 Ticket 类别 ID，用于识别 Ticket 频道。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        category_ids (str): 以逗号分隔的类别 ID 列表（如 "123, 456"）
    """
    guild_id = str(interaction.guild.id)
    try:
        ids = [int(id.strip()) for id in category_ids.split(',')]  # 将字符串转换为整数列表
        await config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)
        config = config_manager.get_guild_config(guild_id)
        logger.info(f"用户 {interaction.user.name} 设置 Ticket 类别 ID: {ids}")
        await interaction.response.send_message(f'Ticket 类别 ID 已设置为: {ids}', ephemeral=True)
    except ValueError:
        logger.warning(f"用户 {interaction.user.name} 输入无效的类别 ID: {category_ids}")
        await interaction.response.send_message("输入错误，请提供有效的类别 ID。", ephemeral=True)

@bot.tree.command(name="check_ticket_cate", description="查看当前的 Ticket 类别 ID")
@app_commands.check(is_allowed)
@check_activation()
async def check_ticket_cate(interaction: discord.Interaction):
    """
    查看当前服务器的 Ticket 类别 ID 和对应的类别名称。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    ticket_cate_ids = config.get('ticket_category_ids', [])
    if ticket_cate_ids:
        guild = interaction.guild
        categories = [guild.get_channel(cid) for cid in ticket_cate_ids if guild.get_channel(cid) and guild.get_channel(cid).type == discord.ChannelType.category]
        response = "当前 Ticket 类别:\n" + "\n".join([f"{cate.name} (ID: {cate.id})" for cate in categories]) if categories else "当前 Ticket 类别 ID 未对应任何类别"
    else:
        response = "尚未设置 Ticket 类别"
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)
@check_activation()
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    """
    设置 Telegram 推送频道 ID，用于接收问题反馈和总结。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        tg_channel_id (str): Telegram 频道 ID（如 "@MyChannel"）
    """
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'tg_channel_id', tg_channel_id)
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}', ephemeral=True)

@bot.tree.command(name="check_tg_channel", description="查看当前的 Telegram 推送频道")
@app_commands.check(is_allowed)
@check_activation()
async def check_tg_channel(interaction: discord.Interaction):
    """
    查看当前服务器绑定的 Telegram 推送频道。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    tg_channel_id = config.get('tg_channel_id', '未设置')
    response = f"当前 Telegram 推送频道 ID: {tg_channel_id}" if tg_channel_id != '未设置' else "尚未设置 Telegram 推送频道"
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_monitor_channels", description="设置监控的 General Chat 频道")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
@check_activation()
async def set_monitor_channels(interaction: discord.Interaction, channels: str):
    """
    设置需要监控的 General Chat 频道，最多 5 个。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        channels (str): 以逗号分隔的频道 ID 列表（如 "111, 222"）
    """
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]
    if len(channel_ids) > 5:
        await interaction.response.send_message("最多只能设置5个频道", ephemeral=True)
        return
    await config_manager.set_guild_config(guild_id, 'monitor_channels', channel_ids)
    await interaction.response.send_message(f'已设置监控频道: {channel_ids}', ephemeral=True)

@bot.tree.command(name="remove_monitor_channels", description="移除监控的 General Chat 频道")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
@check_activation()
async def remove_monitor_channels(interaction: discord.Interaction, channels: str):
    """
    从监控列表中移除指定的 General Chat 频道。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        channels (str): 以逗号分隔的频道 ID 列表
    """
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]
    current_channels = config_manager.get_guild_config(guild_id).get('monitor_channels', [])
    updated_channels = [ch for ch in current_channels if ch not in channel_ids]
    await config_manager.set_guild_config(guild_id, 'monitor_channels', updated_channels)
    await interaction.response.send_message(f'已移除监控频道: {channel_ids}', ephemeral=True)

@bot.tree.command(name="check_monitor_channels", description="查看当前监控的频道")
@app_commands.check(is_allowed)
@check_activation()
async def check_monitor_channels(interaction: discord.Interaction):
    """
    查看当前服务器的监控频道及其名称。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    monitor_channels = config.get('monitor_channels', [])
    if monitor_channels:
        guild = interaction.guild
        channels = [guild.get_channel(cid) for cid in monitor_channels if guild.get_channel(cid)]
        response = "当前监控频道:\n" + "\n".join([f"{ch.name} (ID: {ch.id})" for ch in channels]) if channels else "当前监控频道 ID 未对应任何频道"
    else:
        response = "尚未设置监控频道"
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_monitor_params", description="设置监控周期和最大消息条数")
@app_commands.describe(period_hours="监控周期（小时）", max_messages="最大消息条数")
@app_commands.check(is_allowed)
@check_activation()
async def set_monitor_params(interaction: discord.Interaction, period_hours: int, max_messages: int):
    """
    设置 General Chat 监控的周期和最大消息数。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        period_hours (int): 监控周期（小时）
        max_messages (int): 每次分析的最大消息数
    """
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'monitor_period', period_hours)
    await config_manager.set_guild_config(guild_id, 'monitor_max_messages', max_messages)
    await interaction.response.send_message(f'已设置监控周期为 {period_hours} 小时，最大消息条数为 {max_messages}', ephemeral=True)

@bot.tree.command(name="check_monitor_params", description="查看当前监控参数")
@app_commands.check(is_allowed)
@check_activation()
async def check_monitor_params(interaction: discord.Interaction):
    """
    查看当前服务器的监控周期和最大消息数。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    period = config.get('monitor_period', 2)  # 默认 2 小时
    max_messages = config.get('monitor_max_messages', 100)  # 默认 100 条
    await interaction.response.send_message(f'当前监控周期: {period} 小时，最大消息条数: {max_messages}', ephemeral=True)

@bot.tree.command(name="set_access", description="设置允许使用 Bot 命令的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)
@check_activation()
async def set_access(interaction: discord.Interaction, role: discord.Role):
    """
    设置允许使用 Bot 命令的角色，仅限管理员操作。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        role (discord.Role): 要授权的身份组
    """
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id not in allowed_roles:
        allowed_roles.append(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)
        roles = [interaction.guild.get_role(rid).name for rid in allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(f'已允许身份组 {role.name} 使用命令\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        await interaction.response.send_message(f'身份组 {role.name} 已有权限', ephemeral=True)

@bot.tree.command(name="remove_access", description="移除允许使用 Bot 命令的身份组")
@app_commands.describe(role="要移除的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)
@check_activation()
async def remove_access(interaction: discord.Interaction, role: discord.Role):
    """
    移除允许使用 Bot 命令的角色，仅限管理员操作。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        role (discord.Role): 要移除权限的身份组
    """
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id in allowed_roles:
        allowed_roles.remove(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)
        roles = [interaction.guild.get_role(rid).name for rid in allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(f'已移除身份组 {role.name} 的命令权限\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        await interaction.response.send_message(f'身份组 {role.name} 不在允许列表中', ephemeral=True)

@bot.tree.command(name="check_access", description="查看允许使用 Bot 命令的身份组")
@app_commands.checks.has_permissions(administrator=True)
@check_activation()
async def check_access(interaction: discord.Interaction):
    """
    查看当前服务器允许使用命令的身份组，仅限管理员。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])
    if allowed_roles:
        roles = [interaction.guild.get_role(rid).name for rid in allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(f'当前允许使用命令的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        await interaction.response.send_message('没有设置允许的身份组', ephemeral=True)

# 新增命令：添加 warp_msg 权限
@bot.tree.command(name="add_warp_msg_access", description="增加允许使用 warp_msg 的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员
@check_activation()
async def add_warp_msg_access(interaction: discord.Interaction, role: discord.Role):
    """
    为 warp_msg 命令添加允许的身份组，仅限管理员操作
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        role (discord.Role): 要添加的身份组
    """
    guild_id = str(interaction.guild.id)
    warp_msg_allowed_roles = config_manager.get_warp_msg_allowed_roles(guild_id)
    if role.id not in warp_msg_allowed_roles:
        warp_msg_allowed_roles.append(role.id)
        await config_manager.set_guild_config(guild_id, 'warp_msg_allowed_roles', warp_msg_allowed_roles)
        roles = [interaction.guild.get_role(rid).name for rid in warp_msg_allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(
            f"已允许身份组 {role.name} 使用 warp_msg\n当前允许的身份组: {', '.join(roles)}",
            ephemeral=True
        )
        logger.info(f"用户 {interaction.user.name} 为 warp_msg 添加角色权限: {role.name}")
    else:
        await interaction.response.send_message(f"身份组 {role.name} 已拥有 warp_msg 权限", ephemeral=True)
        logger.info(f"用户 {interaction.user.name} 尝试重复添加 warp_msg 权限: {role.name}")

# 新增命令：移除 warp_msg 权限
@bot.tree.command(name="remove_warp_msg_access", description="移除允许使用 warp_msg 的身份组")
@app_commands.describe(role="要移除的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员
@check_activation()
async def remove_warp_msg_access(interaction: discord.Interaction, role: discord.Role):
    """
    移除 warp_msg 命令的允许身份组，仅限管理员操作
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        role (discord.Role): 要移除的身份组
    """
    guild_id = str(interaction.guild.id)
    warp_msg_allowed_roles = config_manager.get_warp_msg_allowed_roles(guild_id)
    if role.id in warp_msg_allowed_roles:
        warp_msg_allowed_roles.remove(role.id)
        await config_manager.set_guild_config(guild_id, 'warp_msg_allowed_roles', warp_msg_allowed_roles)
        roles = [interaction.guild.get_role(rid).name for rid in warp_msg_allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(
            f"已移除身份组 {role.name} 的 warp_msg 权限\n当前允许的身份组: {', '.join(roles) if roles else '无'}",
            ephemeral=True
        )
        logger.info(f"用户 {interaction.user.name} 移除 warp_msg 角色权限: {role.name}")
    else:
        await interaction.response.send_message(f"身份组 {role.name} 未拥有 warp_msg 权限", ephemeral=True)
        logger.info(f"用户 {interaction.user.name} 尝试移除不存在的 warp_msg 权限: {role.name}")

# 新增命令：查看 warp_msg 权限
@bot.tree.command(name="check_warp_msg_access", description="查看允许使用 warp_msg 的身份组")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员
@check_activation()
async def check_warp_msg_access(interaction: discord.Interaction):
    """
    查看当前允许使用 warp_msg 的身份组，仅限管理员
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    guild_id = str(interaction.guild.id)
    warp_msg_allowed_roles = config_manager.get_warp_msg_allowed_roles(guild_id)
    if warp_msg_allowed_roles:
        roles = [interaction.guild.get_role(rid).name for rid in warp_msg_allowed_roles if interaction.guild.get_role(rid)]
        await interaction.response.send_message(
            f"当前允许使用 warp_msg 的身份组: {', '.join(roles)}",
            ephemeral=True
        )
        logger.info(f"用户 {interaction.user.name} 查看 warp_msg 权限: {', '.join(roles)}")
    else:
        await interaction.response.send_message("没有设置允许使用 warp_msg 的身份组", ephemeral=True)
        logger.info(f"用户 {interaction.user.name} 查看 warp_msg 权限: 无")

# 修改 warp_msg，添加独立权限检查
@bot.tree.command(name="warp_msg", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_warp_msg_allowed)  # 使用独立的权限检查
@check_activation()
async def warp_msg(interaction: discord.Interaction):
    """
    手动触发 LLM 分析当前 Ticket 频道的内容，并推送结果到 Telegram。
    - 仅限管理员或拥有 warp_msg_allowed_roles 的用户使用
    """
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    if not is_ticket_channel(channel, config):
        await interaction.response.send_message("只能在 Ticket 频道中使用", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    conversation = await get_conversation(channel)
    creation_time = channel.created_at or datetime.datetime.now(datetime.timezone.utc)
    llm_config = config_manager.get_llm_config(guild_id) or {
        'api_key': DEFAULT_LLM_API_KEY,
        'model_id': DEFAULT_MODEL_ID,
        'base_url': DEFAULT_BASE_URL
    }
    problem = await asyncio.to_thread(
        analyze_ticket_conversation, conversation, channel, guild_id,
        config, llm_config['api_key'], llm_config['base_url'], llm_config['model_id'], creation_time
    )
    if problem['is_valid']:
        problem['id'] = await config_manager.get_next_problem_id()
        tg_channel_id = config.get('tg_channel_id')
        if tg_channel_id:
            await telegram_bot.send_problem_form(problem, tg_channel_id)
        await interaction.followup.send(f"问题反馈已生成并同步，ID: {problem['id']}", ephemeral=True)
    else:
        await interaction.followup.send("分析结果无效，未生成问题反馈", ephemeral=True)

@bot.tree.command(name="set_timezone", description="设置时区偏移（UTC + x）")
@app_commands.describe(offset="时区偏移量（整数，例如 8 表示 UTC+8）")
@app_commands.check(is_allowed)
@check_activation()
async def set_timezone(interaction: discord.Interaction, offset: int):
    """
    设置服务器的时区偏移，用于调整时间戳显示。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
        offset (int): UTC 偏移量（如 8 表示 UTC+8）
    """
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'timezone', offset)
    await interaction.response.send_message(f'时区偏移已设置为 UTC+{offset}', ephemeral=True)

@bot.tree.command(name="help", description="显示Bot命令帮助信息")
@app_commands.check(is_allowed)
async def help_command(interaction: discord.Interaction):
    """
    显示所有命令的帮助信息，包含激活和配置流程。
    
    Args:
        interaction (discord.Interaction): Discord 交互对象
    """
    help_text = """
**Discord Bot 命令帮助**

- **重要: 若想使用 TG推送，需要添加 @hermes_dc_bot 为 TG Channel 的管理员**

**激活命令**
- `/activate_key <key>` 使用密钥激活 Bot
- `/activate_llm <api_key> <model_id> <base_url>` 使用自定义 LLM 配置激活 Bot

**必须配置的命令**  
- `/set_ticket_cate category_ids` 设置 Ticket 类别 ID
- `/set_monitor_channels channels` 设置监控频道 ID
- `/set_tg_channel tg_channel_id` 设置 Telegram 推送频道 ID  

**选择性配置的命令**  
- `/set_monitor_params period_hours max_messages` 设置监控参数
- `/set_access role` 设置命令权限角色
- `/remove_access role` 移除权限角色
- `/set_timezone offset` 设置时区偏移  

**Warp_msg 权限管理（仅限管理员）**
- `/add_warp_msg_access <role>` 增加允许使用 warp_msg 的身份组
- `/remove_warp_msg_access <role>` 移除允许使用 warp_msg 的身份组
- `/check_warp_msg_access` 查看允许使用 warp_msg 的身份组

**其他命令**  
- `/warp_msg` 手动分析 Ticket 频道并推送  
- `/check_*` 查询各项配置  
"""
    await interaction.response.send_message(help_text, ephemeral=True)

# 创建 Telegram Bot 实例，传入默认 LLM 配置
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot, DEFAULT_LLM_API_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL_ID)

async def heartbeat_task():
    """
    心跳任务，每分钟记录一次日志以确认 Bot 运行状态，使用固定 UTC+8 时区。
    """
    tz = pytz.timezone('Asia/Shanghai')  # 设置时区为 UTC+8
    lasting_mins = 0
    while True:
        local_time = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M") + " UTC+8"
        lasting_mins += 1
        heartbeat_logger.info(f"Bot alive at {local_time}, lasting for {lasting_mins} mins")
        await asyncio.sleep(60)  # 每 60 秒记录一次

async def main():
    """
    主程序入口，启动 Discord Bot、Telegram Bot 和心跳任务。
    """
    logger.info(f"启动 Discord Bot，Token: {DISCORD_TOKEN[:5]}...")
    logger.info(f"启动 Telegram Bot，Token: {TELEGRAM_TOKEN[:5]}...")
    logger.info(f"激活密钥配置: {MY_ACTIVE_KEY[:5]}...（已隐藏后缀）")  # 仅记录密钥前5位
    
    # 在事件循环运行后保存初始配置（如果有新生成的 encryption_key）
    await config_manager.save_config()
    logger.info("初始配置已保存至 config.json")
    
    asyncio.create_task(heartbeat_task())
    
    # 独立运行 Telegram Bot
    telegram_task = asyncio.create_task(telegram_bot.run())
    
    try:
        # 运行 Discord Bot
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Discord Bot 运行失败: {e}")
        telegram_task.cancel()  # 如果 Discord 失败，取消 Telegram 任务
        raise
    finally:
        await telegram_task  # 确保 Telegram 任务完成

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Bot Aborted Unexpectedly: {e}", exc_info=True)
        raise