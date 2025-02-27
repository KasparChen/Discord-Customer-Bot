import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler  # 用于日志轮转，避免文件过大
from dotenv import load_dotenv
import datetime
import pytz  # 新增，用于处理时区
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

# 配置心跳日志记录器
heartbeat_logger = logging.getLogger('heartbeat')
heartbeat_handler = RotatingFileHandler(
    'heartbeat.log',     # 心跳日志文件路径
    maxBytes=5*1024*1024, # 单个日志文件最大 5MB
    backupCount=5         # 保留 5 个备份文件
)
heartbeat_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
heartbeat_logger.addHandler(heartbeat_handler)
heartbeat_logger.setLevel(logging.INFO)

# 设置 httpx 日志级别为 WARNING，避免频繁的 getUpdates 请求污染日志
logging.getLogger("httpx").setLevel(logging.WARNING)

# 加载环境变量
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord Bot 的 Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Telegram Bot 的 Token
MODEL_ID = os.getenv('MODEL_ID')  # LLM 模型 ID
LLM_API_KEY = os.getenv('LLM_API_KEY')  # LLM API 密钥
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'  # LLM API 基础 URL

# 初始化配置管理器和 Discord Bot
config_manager = ConfigManager()  # 用于管理服务器配置
intents = discord.Intents.default()  # 设置 Discord Bot 的权限意图
intents.message_content = True  # 启用消息内容监听
intents.guilds = True  # 启用服务器相关事件
intents.guild_messages = True  # 启用服务器消息事件
bot = commands.Bot(command_prefix='/', intents=intents)  # 创建 Bot 实例，使用斜杠命令前缀

# 全局变量
bot_start_time = datetime.datetime.now(datetime.timezone.utc)  # Bot 启动时间，用于过滤旧消息
ticket_creation_times = {}  # 存储 Ticket 频道的创建时间

@bot.event
async def on_ready():
    """Bot 就绪事件，当 Bot 成功登录 Discord 时触发"""
    logger.info(f'Discord Bot 成功登录为 {bot.user}')
    try:
        synced = await bot.tree.sync()  # 同步斜杠命令到 Discord
        logger.info(f"斜杠命令已成功同步到 Discord，同步了 {len(synced)} 个命令")
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")

@bot.event
async def on_message(message):
    """消息监听事件，处理每条新消息"""
    if message.author == bot.user or message.created_at < bot_start_time:  # 忽略 Bot 自己的消息和启动前的消息
        return
    guild_id = str(message.guild.id)  # 获取服务器 ID
    config = config_manager.get_guild_config(guild_id)  # 获取服务器配置
    if is_ticket_channel(message.channel, config):  # 检查是否为 Ticket 频道
        if message.channel.id not in ticket_creation_times:  # 如果是新 Ticket 频道
            ticket_creation_times[message.channel.id] = message.created_at  # 记录创建时间
            logger.info(f"检测到新 Ticket 频道: {message.channel.name}，创建时间: {message.created_at}")
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))  # 异步启动自动分析任务
        logger.info(f"处理消息，频道: {message.channel.name}，发送者: {message.author.name}，内容: {message.content[:50]}...")
        asyncio.create_task(process_message(message, guild_id))  # 异步处理消息
    await bot.process_commands(message)  # 处理其他命令

async def auto_analyze_ticket(channel, guild_id):
    """自动分析 Ticket 频道，等待1小时后执行"""
    logger.info(f"开始自动分析 Ticket 频道: {channel.name}，等待 1 小时")
    await asyncio.sleep(3600)  # 等待1小时（3600秒）
    conversation = await get_conversation(channel)  # 获取频道对话内容
    creation_time = ticket_creation_times.get(channel.id)  # 获取频道创建时间
    if creation_time:
        # 使用 LLM 分析 Ticket 对话，运行在单独线程以避免阻塞
        problem = await asyncio.to_thread(
            analyze_ticket_conversation, conversation, channel, guild_id,
            config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID, creation_time
        )
        if problem and problem['is_valid']:  # 如果分析结果有效
            problem['id'] = await config_manager.get_next_problem_id()  # 为问题分配唯一 ID
            tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')  # 获取 Telegram 推送频道 ID
            if tg_channel_id:
                await telegram_bot.send_problem_form(problem, tg_channel_id)  # 发送问题到 Telegram
                logger.info(f"问题反馈已发送到 Telegram 频道 {tg_channel_id}，问题 ID: {problem['id']}")
        else:
            logger.info(f"频道 {channel.name} 不构成有效问题")
    else:
        logger.error(f"无法获取频道 {channel.name} 的创建时间")

async def process_message(message, guild_id):
    """实时消息处理（可扩展，目前为空）"""
    pass  # 占位符，可根据需求扩展功能

def is_allowed(interaction: discord.Interaction):
    """检查用户是否有权限使用命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])  # 获取允许的角色列表
    if interaction.user.guild_permissions.administrator:  # 如果用户是管理员
        logger.info(f"用户 {interaction.user.name} 是管理员，允许执行命令")
        return True
    has_permission = any(role.id in allowed_roles for role in interaction.user.roles)  # 检查用户角色是否在允许列表中
    logger.info(f"用户 {interaction.user.name} 检查权限，结果: {has_permission}")
    return has_permission

@bot.tree.command(name="set_ticket_cate", description="设置 Ticket 类别 ID（用逗号分隔）")
@app_commands.describe(category_ids="Ticket 类别 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def set_ticket_cate(interaction: discord.Interaction, category_ids: str):
    """设置 Ticket 类别 ID 的斜杠命令"""
    guild_id = str(interaction.guild.id)
    try:
        ids = [int(id.strip()) for id in category_ids.split(',')]  # 将输入转换为整数列表
        await config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)  # 更新配置
        config = config_manager.get_guild_config(guild_id)
        logger.info(f"用户 {interaction.user.name} 设置 Ticket 类别 ID: {ids}")
        await interaction.response.send_message(f'Ticket 类别 ID 已设置为: {ids}\n当前 Ticket 类别 ID: {config.get("ticket_category_ids", [])}', ephemeral=True)
    except ValueError:
        logger.warning(f"用户 {interaction.user.name} 输入无效的类别 ID: {category_ids}")
        await interaction.response.send_message("输入错误，请提供有效的类别 ID（用逗号分隔）。", ephemeral=True)

@bot.tree.command(name="check_ticket_cate", description="查看当前的 Ticket 类别 ID")
@app_commands.check(is_allowed)
async def check_ticket_cate(interaction: discord.Interaction):
    """查看当前 Ticket 类别 ID 的斜杠命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    ticket_cate_ids = config.get('ticket_category_ids', [])
    if ticket_cate_ids:
        guild = interaction.guild
        categories = [guild.get_channel(cid) for cid in ticket_cate_ids if guild.get_channel(cid) and guild.get_channel(cid).type == discord.ChannelType.category]
        if categories:
            response = "当前 Ticket 类别:\n" + "\n".join([f"{cate.name} (ID: {cate.id})" for cate in categories])
        else:
            response = "当前 Ticket 类别 ID 未对应任何类别"
    else:
        response = "尚未设置 Ticket 类别"
    logger.info(f"用户 {interaction.user.name} 查看 Ticket 类别: {response}")
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    """设置 Telegram 推送频道 ID 的斜杠命令"""
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'tg_channel_id', tg_channel_id)  # 更新配置
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置 Telegram 推送频道: {tg_channel_id}")
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}\n当前 Telegram 推送频道: {config.get("tg_channel_id", "未设置")}', ephemeral=True)

@bot.tree.command(name="check_tg_channel", description="查看当前的 Telegram 推送频道")
@app_commands.check(is_allowed)
async def check_tg_channel(interaction: discord.Interaction):
    """查看当前 Telegram 推送频道的斜杠命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    tg_channel_id = config.get('tg_channel_id', '未设置')
    if tg_channel_id != '未设置':
        response = f"当前 Telegram 推送频道 ID: {tg_channel_id}\n请自行确认ID是否正确。"
    else:
        response = "尚未设置 Telegram 推送频道"
    logger.info(f"用户 {interaction.user.name} 查看 Telegram 推送频道: {tg_channel_id}")
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_monitor_channels", description="设置监控的 General Chat 频道（最多5个）")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def set_monitor_channels(interaction: discord.Interaction, channels: str):
    """设置监控频道的斜杠命令"""
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]  # 将输入转换为整数列表
    if len(channel_ids) > 5:  # 限制最多5个频道
        logger.warning(f"用户 {interaction.user.name} 尝试设置超过5个监控频道: {channel_ids}")
        await interaction.response.send_message("最多只能设置5个频道", ephemeral=True)
        return
    await config_manager.set_guild_config(guild_id, 'monitor_channels', channel_ids)  # 更新配置
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置监控频道: {channel_ids}")
    await interaction.response.send_message(f'已设置监控频道: {channel_ids}\n当前监控频道: {config.get("monitor_channels", [])}', ephemeral=True)

@bot.tree.command(name="remove_monitor_channels", description="移除监控的 General Chat 频道")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def remove_monitor_channels(interaction: discord.Interaction, channels: str):
    """移除监控频道的斜杠命令"""
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]  # 将输入转换为整数列表
    current_channels = config_manager.get_guild_config(guild_id).get('monitor_channels', [])
    updated_channels = [ch for ch in current_channels if ch not in channel_ids]  # 移除指定频道
    await config_manager.set_guild_config(guild_id, 'monitor_channels', updated_channels)  # 更新配置
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 移除监控频道: {channel_ids}")
    await interaction.response.send_message(f'已移除监控频道: {channel_ids}\n当前监控频道: {config.get("monitor_channels", [])}', ephemeral=True)

@bot.tree.command(name="check_monitor_channels", description="查看当前监控的频道")
@app_commands.check(is_allowed)
async def check_monitor_channels(interaction: discord.Interaction):
    """查看当前监控频道的斜杠命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    monitor_channels = config.get('monitor_channels', [])
    if monitor_channels:
        guild = interaction.guild
        channels = [guild.get_channel(cid) for cid in monitor_channels if guild.get_channel(cid)]
        if channels:
            response = "当前监控频道:\n" + "\n".join([f"{ch.name} (ID: {ch.id})" for ch in channels])
        else:
            response = "当前监控频道 ID 未对应任何频道"
    else:
        response = "尚未设置监控频道"
    logger.info(f"用户 {interaction.user.name} 查看监控频道: {response}")
    await interaction.response.send_message(response, ephemeral=True)

@bot.tree.command(name="set_monitor_params", description="设置监控周期和最大消息条数")
@app_commands.describe(period_hours="监控周期（小时）", max_messages="最大消息条数")
@app_commands.check(is_allowed)
async def set_monitor_params(interaction: discord.Interaction, period_hours: int, max_messages: int):
    """设置监控参数的斜杠命令"""
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'monitor_period', period_hours)  # 设置监控周期
    await config_manager.set_guild_config(guild_id, 'monitor_max_messages', max_messages)  # 设置最大消息数
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置监控参数: 周期={period_hours}小时, 最大消息数={max_messages}")
    await interaction.response.send_message(f'已设置监控周期为 {period_hours} 小时，最大消息条数为 {max_messages}\n当前监控周期: {config.get("monitor_period", 3)} 小时，最大消息条数: {config.get("monitor_max_messages", 100)}', ephemeral=True)

@bot.tree.command(name="check_monitor_params", description="查看当前监控参数")
@app_commands.check(is_allowed)
async def check_monitor_params(interaction: discord.Interaction):
    """查看当前监控参数的斜杠命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    period = config.get('monitor_period', 3)  # 默认周期为3小时
    max_messages = config.get('monitor_max_messages', 100)  # 默认最大消息数为100
    logger.info(f"用户 {interaction.user.name} 查看监控参数: 周期={period}小时, 最大消息数={max_messages}")
    await interaction.response.send_message(f'当前监控周期: {period} 小时，最大消息条数: {max_messages}', ephemeral=True)

@bot.tree.command(name="set_access", description="设置允许使用 Bot 命令的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员使用
async def set_access(interaction: discord.Interaction, role: discord.Role):
    """设置允许使用 Bot 命令的角色的斜杠命令"""
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id not in allowed_roles:  # 如果角色尚未被添加
        allowed_roles.append(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)  # 更新配置
        config = config_manager.get_guild_config(guild_id)
        roles = [interaction.guild.get_role(rid).name for rid in config.get("allowed_roles", []) if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 设置允许角色: {role.name}")
        await interaction.response.send_message(f'已允许身份组 {role.name} 使用命令\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 尝试重复设置允许角色: {role.name}")
        await interaction.response.send_message(f'身份组 {role.name} 已有权限', ephemeral=True)

@bot.tree.command(name="remove_access", description="移除允许使用 Bot 命令的身份组")
@app_commands.describe(role="要移除的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员使用
async def remove_access(interaction: discord.Interaction, role: discord.Role):
    """移除允许使用 Bot 命令的角色的斜杠命令"""
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id in allowed_roles:  # 如果角色在允许列表中
        allowed_roles.remove(role.id)
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)  # 更新配置
        config = config_manager.get_guild_config(guild_id)
        roles = [interaction.guild.get_role(rid).name for rid in config.get("allowed_roles", []) if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 移除允许角色: {role.name}")
        await interaction.response.send_message(f'已移除身份组 {role.name} 的命令权限\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 尝试移除不存在的允许角色: {role.name}")
        await interaction.response.send_message(f'身份组 {role.name} 不在允许列表中', ephemeral=True)

@bot.tree.command(name="check_access", description="查看允许使用 Bot 命令的身份组")
@app_commands.checks.has_permissions(administrator=True)  # 仅限管理员使用
async def check_access(interaction: discord.Interaction):
    """查看允许使用 Bot 命令的角色的斜杠命令"""
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])
    if allowed_roles:
        roles = [interaction.guild.get_role(rid).name for rid in allowed_roles if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 查看允许角色: {', '.join(roles)}")
        await interaction.response.send_message(f'当前允许使用命令的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 查看允许角色: 无")
        await interaction.response.send_message('没有设置允许的身份组', ephemeral=True)

@bot.tree.command(name="warp_msg", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_allowed)
async def warp_msg(interaction: discord.Interaction):
    """
    手动触发 LLM 分析当前 Ticket 频道的内容，并将结果同步到 Telegram
    包含时间戳兜底策略：如果无法获取频道创建时间，则使用第一条消息时间
    """
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)

    # 检查是否为 Ticket 频道
    if not is_ticket_channel(channel, config):
        logger.warning(f"用户 {interaction.user.name} 尝试在非 Ticket 频道 {channel.name} 使用 warp_msg")
        await interaction.response.send_message("只能在 Ticket 频道中使用", ephemeral=True)
        return

    # 延迟响应，避免超时
    await interaction.response.defer(ephemeral=True)

    # 获取频道会话
    conversation = await get_conversation(channel)

    # 获取时间戳，包含兜底策略
    channel = interaction.channel
    creation_time = channel.created_at
    if creation_time is None:
        try:
            async for message in channel.history(limit=1, oldest_first=True):
                creation_time = message.created_at
                logger.info(f"采用首条消息的创建时间戳: {creation_time}")
        except Exception as e:
            # 如果失败，使用当前时间作为最后兜底
            logger.error(f"无法获取频道 {channel.name} 的第一条消息时间: {e}")
            creation_time = datetime.datetime.now(datetime.timezone.utc)
            logger.info(f"使用当前时间作为频道 {channel.name} 的时间戳: {creation_time}")

    # 执行分析并同步结果
    if creation_time:
        problem = await asyncio.to_thread(
            analyze_ticket_conversation, conversation, channel, guild_id,
            config, LLM_API_KEY, BASE_URL, MODEL_ID, creation_time
        )
        if problem['is_valid']:
            problem['id'] = await config_manager.get_next_problem_id()
            tg_channel_id = config.get('tg_channel_id')
            if tg_channel_id:
                await telegram_bot.send_problem_form(problem, tg_channel_id)
                logger.info(f"用户 {interaction.user.name} 手动分析完成，问题 ID: {problem['id']} 已发送到 {tg_channel_id}")
            await interaction.followup.send(f"问题反馈已生成并同步，ID: {problem['id']}", ephemeral=True)
        else:
            logger.info(f"用户 {interaction.user.name} 手动分析结果无效，频道: {channel.name}")
            await interaction.followup.send("分析结果无效，未生成问题反馈", ephemeral=True)
    else:
        logger.error(f"无法获取频道 {channel.name} 的时间戳")
        await interaction.followup.send("无法获取频道时间戳", ephemeral=True)

@bot.tree.command(name="set_timezone", description="设置时区偏移（UTC + x）")
@app_commands.describe(offset="时区偏移量（整数，例如 8 表示 UTC+8）")
@app_commands.check(is_allowed)
async def set_timezone(interaction: discord.Interaction, offset: int):
    """设置时区偏移的斜杠命令，用于调整问题总结中的时间戳"""
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'timezone', offset)  # 将时区偏移量存储到配置中
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置时区偏移: UTC+{offset}")
    await interaction.response.send_message(
        f'时区偏移已设置为 UTC+{offset}\n当前时区偏移: {config.get("timezone", "未设置")}',
        ephemeral=True
    )

# 创建 Telegram Bot 实例
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot, LLM_API_KEY, BASE_URL, MODEL_ID)

async def heartbeat_task():
    """心跳任务，每分钟记录一次日志以确认 Bot 运行状态，固定使用 UTC+8"""
    tz = pytz.timezone('Asia/Shanghai')  # 设置时区为 UTC+8（中国标准时间）
    lasting_mins = 0
    while True:
        local_time = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M") + f" UTC+8"  # 获取当前 UTC+8 时间
        lasting_mins += 1
        heartbeat_logger.info(f"Bot alive at {local_time}, lasting for {lasting_mins} mins")  # 记录带时间戳的心跳日志
        await asyncio.sleep(60)  # 每60秒记录一次

async def main():
    """主程序：启动 Discord Bot、Telegram Bot 和心跳任务"""
    logger.info(f"启动 Discord Bot，Token: {DISCORD_TOKEN[:5]}...")
    logger.info(f"启动 Telegram Bot，Token: {TELEGRAM_TOKEN[:5]}...")
    logger.info(f"LLM 配置 - API Key: {LLM_API_KEY[:5]}..., Base URL: {BASE_URL}, Model ID: {MODEL_ID}")
    asyncio.create_task(heartbeat_task())  # 启动心跳任务
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),  # 启动 Discord Bot
        telegram_bot.run()  # 启动 Telegram Bot
    )

if __name__ == "__main__":
    asyncio.run(main())  # 运行主程序