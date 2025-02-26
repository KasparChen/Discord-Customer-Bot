import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler  # 用于日志轮转，避免文件过大
from dotenv import load_dotenv
import datetime
from config_manager import ConfigManager
from utils import get_conversation, is_ticket_channel
from llm_analyzer import analyze_ticket_conversation, analyze_general_conversation
from telegram_bot import TelegramBot

# 配置日志记录，使用轮转日志保存到文件并输出到控制台
handler = RotatingFileHandler(
    'bot.log',           # 日志文件路径
    maxBytes=5*1024*1024, # 单个日志文件最大 5MB
    backupCount=5         # 保留 5 个备份文件
)
logging.basicConfig(
    level=logging.INFO,   # 设置日志级别为 INFO，记录 INFO 及以上级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 日志格式：时间-模块名-级别-消息
    handlers=[
        handler,          # 使用轮转文件处理器
        logging.StreamHandler()  # 同时输出到控制台
    ]
)
logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器

# 设置 httpx 日志级别为 WARNING，避免频繁的 getUpdates 请求污染日志
logging.getLogger("httpx").setLevel(logging.WARNING)

# 从 .env 文件加载环境变量
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord Bot 的 Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Telegram Bot 的 Token
MODEL_ID = os.getenv('MODEL_ID')  # LLM 模型 ID
LLM_API_KEY = os.getenv('LLM_API_KEY')  # LLM API Key
BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'  # LLM API 的基础 URL

# 初始化配置管理器和 Discord Bot
config_manager = ConfigManager()  # 用于管理配置文件
intents = discord.Intents.default()  # 设置 Bot 的默认权限
intents.message_content = True  # 启用消息内容读取权限
intents.guilds = True  # 启用服务器相关权限
intents.guild_messages = True  # 启用服务器消息读取权限
bot = commands.Bot(command_prefix='/', intents=intents)  # 创建 Bot 实例，命令前缀为 /

# 全局变量
bot_start_time = datetime.datetime.now(datetime.timezone.utc)  # 记录 Bot 启动时间（UTC）
ticket_creation_times = {}  # 存储 Ticket 频道的创建时间

# Bot 就绪事件：当 Bot 成功登录时触发
@bot.event
async def on_ready():
    logger.info(f'Discord Bot 成功登录为 {bot.user}')  # 记录 Bot 登录成功
    try:
        synced = await bot.tree.sync()  # 将斜杠命令同步到 Discord
        logger.info(f"斜杠命令已成功同步到 Discord，同步了 {len(synced)} 个命令")  # 记录同步成功的详细信息
    except Exception as e:
        logger.error(f"斜杠命令同步失败: {e}")  # 记录同步失败的错误

# 监听消息事件：处理所有新消息
@bot.event
async def on_message(message):
    # 忽略 Bot 自己的消息或 Bot 启动前的消息
    if message.author == bot.user or message.created_at < bot_start_time:
        return
    guild_id = str(message.guild.id)  # 获取服务器 ID
    config = config_manager.get_guild_config(guild_id)  # 获取服务器配置
    # 如果消息来自 Ticket 频道
    if is_ticket_channel(message.channel, config):
        # 如果是新 Ticket 频道，记录创建时间并启动自动分析任务
        if message.channel.id not in ticket_creation_times:
            ticket_creation_times[message.channel.id] = message.created_at
            logger.info(f"检测到新 Ticket 频道: {message.channel.name}，创建时间: {message.created_at}")  # 记录新 Ticket 频道
            asyncio.create_task(auto_analyze_ticket(message.channel, guild_id))
        logger.info(f"处理消息，频道: {message.channel.name}，发送者: {message.author.name}，内容: {message.content[:50]}...")  # 记录消息处理详情
        asyncio.create_task(process_message(message, guild_id))  # 处理消息（可扩展）
    await bot.process_commands(message)  # 处理传统命令（如果有）

# 自动分析 Ticket 频道：等待1小时后分析对话
async def auto_analyze_ticket(channel, guild_id):
    logger.info(f"开始自动分析 Ticket 频道: {channel.name}，等待 1 小时")  # 记录分析开始
    await asyncio.sleep(3600)  # 等待1小时（3600秒）
    conversation = await get_conversation(channel)  # 获取频道对话
    # 使用 LLM 分析对话，生成问题反馈（异步运行，避免阻塞）
    problem = await asyncio.to_thread(analyze_ticket_conversation, conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    if problem and problem['is_valid']:  # 如果分析结果有效
        problem['id'] = await config_manager.get_next_problem_id()  # 为问题分配唯一 ID
        tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')  # 获取 Telegram 推送频道 ID
        if tg_channel_id:  # 如果设置了推送频道
            await telegram_bot.send_problem_form(problem, tg_channel_id)  # 发送问题反馈到 Telegram
            logger.info(f"问题反馈已发送到 Telegram 频道 {tg_channel_id}，问题 ID: {problem['id']}")  # 记录发送成功
    else:
        logger.info(f"频道 {channel.name} 不构成有效问题")  # 记录无效结果

# 实时消息处理：目前为空，可根据需求扩展
async def process_message(message, guild_id):
    pass  # 占位符，未来可添加实时处理逻辑

# 权限检查函数：判断用户是否有权限使用命令
def is_allowed(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)  # 获取服务器 ID
    config = config_manager.get_guild_config(guild_id)  # 获取服务器配置
    allowed_roles = config.get('allowed_roles', [])  # 获取允许的角色列表
    # 如果用户是管理员，直接通过
    if interaction.user.guild_permissions.administrator:
        logger.info(f"用户 {interaction.user.name} 是管理员，允许执行命令")  # 记录管理员权限
        return True
    # 检查用户是否拥有允许的角色
    has_permission = any(role.id in allowed_roles for role in interaction.user.roles)
    logger.info(f"用户 {interaction.user.name} 检查权限，结果: {has_permission}")  # 记录权限检查结果
    return has_permission

# 命令：设置 Ticket 类别 ID
@bot.tree.command(name="set_ticket_cate", description="设置 Ticket 类别 ID（用逗号分隔）")
@app_commands.describe(category_ids="Ticket 类别 ID（用逗号分隔）")
@app_commands.check(is_allowed)  # 限制只有允许的用户可以使用
async def set_ticket_cate(interaction: discord.Interaction, category_ids: str):
    guild_id = str(interaction.guild.id)  # 获取服务器 ID
    try:
        # 将输入的类别 ID 解析为整数列表
        ids = [int(id.strip()) for id in category_ids.split(',')]
        await config_manager.set_guild_config(guild_id, 'ticket_category_ids', ids)  # 保存配置
        config = config_manager.get_guild_config(guild_id)  # 获取更新后的配置
        logger.info(f"用户 {interaction.user.name} 设置 Ticket 类别 ID: {ids}")  # 记录设置操作
        # 回复用户，显示设置结果和当前配置（仅用户可见）
        await interaction.response.send_message(f'Ticket 类别 ID 已设置为: {ids}\n当前 Ticket 类别 ID: {config.get("ticket_category_ids", [])}', ephemeral=True)
    except ValueError:
        logger.warning(f"用户 {interaction.user.name} 输入无效的类别 ID: {category_ids}")  # 记录输入错误
        # 如果输入无效，提示用户
        await interaction.response.send_message("输入错误，请提供有效的类别 ID（用逗号分隔）。", ephemeral=True)

# 命令：查看 Ticket 类别 ID
@bot.tree.command(name="check_ticket_cate", description="查看当前的 Ticket 类别 ID")
@app_commands.check(is_allowed)
async def check_ticket_cate(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    ticket_cate_ids = config.get('ticket_category_ids', [])  # 获取当前类别 ID
    if ticket_cate_ids:
        guild = interaction.guild
        categories = [guild.get_channel(cid) for cid in ticket_cate_ids if guild.get_channel(cid) and guild.get_channel(cid).type == discord.ChannelType.category]
        if categories:
            response = "当前 Ticket 类别:\n" + "\n".join([f"{cate.name} (ID: {cate.id})" for cate in categories])
        else:
            response = "当前 Ticket 类别 ID 未对应任何类别"
    else:
        response = "尚未设置 Ticket 类别"
    logger.info(f"用户 {interaction.user.name} 查看 Ticket 类别: {response}")  # 记录查看操作
    await interaction.response.send_message(response, ephemeral=True)

# 命令：设置 Telegram 推送频道 ID
@bot.tree.command(name="set_tg_channel", description="设置 Telegram 推送频道 ID")
@app_commands.describe(tg_channel_id="Telegram 频道 ID")
@app_commands.check(is_allowed)
async def set_tg_channel(interaction: discord.Interaction, tg_channel_id: str):
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'tg_channel_id', tg_channel_id)  # 保存 Telegram 频道 ID
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置 Telegram 推送频道: {tg_channel_id}")  # 记录设置操作
    # 回复用户，显示设置结果和当前配置
    await interaction.response.send_message(f'已设置 Telegram 推送频道: {tg_channel_id}\n当前 Telegram 推送频道: {config.get("tg_channel_id", "未设置")}', ephemeral=True)

# 命令：查看 Telegram 推送频道 ID
@bot.tree.command(name="check_tg_channel", description="查看当前的 Telegram 推送频道")
@app_commands.check(is_allowed)
async def check_tg_channel(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    tg_channel_id = config.get('tg_channel_id', '未设置')  # 获取当前 Telegram 频道 ID
    if tg_channel_id != '未设置':
        response = f"当前 Telegram 推送频道 ID: {tg_channel_id}\n请自行确认ID是否正确。"
    else:
        response = "尚未设置 Telegram 推送频道"
    logger.info(f"用户 {interaction.user.name} 查看 Telegram 推送频道: {tg_channel_id}")  # 记录查看操作
    await interaction.response.send_message(response, ephemeral=True)

# 命令：设置监控频道（General Chat）
@bot.tree.command(name="set_monitor_channels", description="设置监控的 General Chat 频道（最多5个）")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def set_monitor_channels(interaction: discord.Interaction, channels: str):
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]  # 解析频道 ID
    if len(channel_ids) > 5:  # 限制最多5个频道
        logger.warning(f"用户 {interaction.user.name} 尝试设置超过5个监控频道: {channel_ids}")  # 记录超限尝试
        await interaction.response.send_message("最多只能设置5个频道", ephemeral=True)
        return
    await config_manager.set_guild_config(guild_id, 'monitor_channels', channel_ids)  # 保存配置
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置监控频道: {channel_ids}")  # 记录设置操作
    await interaction.response.send_message(f'已设置监控频道: {channel_ids}\n当前监控频道: {config.get("monitor_channels", [])}', ephemeral=True)

# 命令：移除监控频道
@bot.tree.command(name="remove_monitor_channels", description="移除监控的 General Chat 频道")
@app_commands.describe(channels="频道 ID（用逗号分隔）")
@app_commands.check(is_allowed)
async def remove_monitor_channels(interaction: discord.Interaction, channels: str):
    guild_id = str(interaction.guild.id)
    channel_ids = [int(id.strip()) for id in channels.split(',')]  # 解析要移除的频道 ID
    current_channels = config_manager.get_guild_config(guild_id).get('monitor_channels', [])  # 获取当前监控频道
    updated_channels = [ch for ch in current_channels if ch not in channel_ids]  # 更新列表
    await config_manager.set_guild_config(guild_id, 'monitor_channels', updated_channels)  # 保存配置
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 移除监控频道: {channel_ids}")  # 记录移除操作
    await interaction.response.send_message(f'已移除监控频道: {channel_ids}\n当前监控频道: {config.get("monitor_channels", [])}', ephemeral=True)

# 命令：查看监控频道
@bot.tree.command(name="check_monitor_channels", description="查看当前监控的频道")
@app_commands.check(is_allowed)
async def check_monitor_channels(interaction: discord.Interaction):
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
    logger.info(f"用户 {interaction.user.name} 查看监控频道: {response}")  # 记录查看操作
    await interaction.response.send_message(response, ephemeral=True)

# 命令：设置监控参数
@bot.tree.command(name="set_monitor_params", description="设置监控周期和最大消息条数")
@app_commands.describe(period_hours="监控周期（小时）", max_messages="最大消息条数")
@app_commands.check(is_allowed)
async def set_monitor_params(interaction: discord.Interaction, period_hours: int, max_messages: int):
    guild_id = str(interaction.guild.id)
    await config_manager.set_guild_config(guild_id, 'monitor_period', period_hours)  # 设置周期
    await config_manager.set_guild_config(guild_id, 'monitor_max_messages', max_messages)  # 设置最大消息数
    config = config_manager.get_guild_config(guild_id)
    logger.info(f"用户 {interaction.user.name} 设置监控参数: 周期={period_hours}小时, 最大消息数={max_messages}")  # 记录设置操作
    await interaction.response.send_message(f'已设置监控周期为 {period_hours} 小时，最大消息条数为 {max_messages}\n当前监控周期: {config.get("monitor_period", 3)} 小时，最大消息条数: {config.get("monitor_max_messages", 100)}', ephemeral=True)

# 命令：查看监控参数
@bot.tree.command(name="check_monitor_params", description="查看当前监控参数")
@app_commands.check(is_allowed)
async def check_monitor_params(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    period = config.get('monitor_period', 3)  # 默认周期3小时
    max_messages = config.get('monitor_max_messages', 100)  # 默认最大消息数100
    logger.info(f"用户 {interaction.user.name} 查看监控参数: 周期={period}小时, 最大消息数={max_messages}")  # 记录查看操作
    await interaction.response.send_message(f'当前监控周期: {period} 小时，最大消息条数: {max_messages}', ephemeral=True)

# 命令：设置允许使用 Bot 的角色
@bot.tree.command(name="set_access", description="设置允许使用 Bot 命令的身份组")
@app_commands.describe(role="允许的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)  # 仅管理员可使用
async def set_access(interaction: discord.Interaction, role: discord.Role):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id not in allowed_roles:  # 如果角色不在列表中
        allowed_roles.append(role.id)  # 添加角色
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)  # 保存配置
        config = config_manager.get_guild_config(guild_id)
        roles = [interaction.guild.get_role(rid).name for rid in config.get("allowed_roles", []) if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 设置允许角色: {role.name}")  # 记录设置操作
        await interaction.response.send_message(f'已允许身份组 {role.name} 使用命令\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 尝试重复设置允许角色: {role.name}")  # 记录重复设置
        await interaction.response.send_message(f'身份组 {role.name} 已有权限', ephemeral=True)

# 命令：移除允许使用的角色
@bot.tree.command(name="remove_access", description="移除允许使用 Bot 命令的身份组")
@app_commands.describe(role="要移除的身份组（@身份组）")
@app_commands.checks.has_permissions(administrator=True)
async def remove_access(interaction: discord.Interaction, role: discord.Role):
    guild_id = str(interaction.guild.id)
    allowed_roles = config_manager.get_guild_config(guild_id).get('allowed_roles', [])
    if role.id in allowed_roles:  # 如果角色在列表中
        allowed_roles.remove(role.id)  # 移除角色
        await config_manager.set_guild_config(guild_id, 'allowed_roles', allowed_roles)  # 保存配置
        config = config_manager.get_guild_config(guild_id)
        roles = [interaction.guild.get_role(rid).name for rid in config.get("allowed_roles", []) if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 移除允许角色: {role.name}")  # 记录移除操作
        await interaction.response.send_message(f'已移除身份组 {role.name} 的命令权限\n当前允许的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 尝试移除不存在的允许角色: {role.name}")  # 记录无效移除
        await interaction.response.send_message(f'身份组 {role.name} 不在允许列表中', ephemeral=True)

# 命令：查看允许的角色
@bot.tree.command(name="check_access", description="查看允许使用 Bot 命令的身份组")
@app_commands.checks.has_permissions(administrator=True)
async def check_access(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    config = config_manager.get_guild_config(guild_id)
    allowed_roles = config.get('allowed_roles', [])
    if allowed_roles:
        roles = [interaction.guild.get_role(rid).name for rid in allowed_roles if interaction.guild.get_role(rid)]
        logger.info(f"用户 {interaction.user.name} 查看允许角色: {', '.join(roles)}")  # 记录查看操作
        await interaction.response.send_message(f'当前允许使用命令的身份组: {", ".join(roles)}', ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 查看允许角色: 无")  # 记录无角色情况
        await interaction.response.send_message('没有设置允许的身份组', ephemeral=True)

# 命令：手动触发 LLM 分析并同步到 Telegram
@bot.tree.command(name="msg_warp", description="手动触发 LLM 分析并同步到 Telegram")
@app_commands.check(is_allowed)
async def msg_warp(interaction: discord.Interaction):
    channel = interaction.channel
    guild_id = str(interaction.guild.id)
    if not is_ticket_channel(channel, config_manager.get_guild_config(guild_id)):  # 限制只能在 Ticket 频道使用
        logger.warning(f"用户 {interaction.user.name} 尝试在非 Ticket 频道 {channel.name} 使用 msg_warp")  # 记录非法使用
        await interaction.response.send_message("只能在 Ticket 频道中使用", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)  # 延迟响应，避免超时
    conversation = await get_conversation(channel)  # 获取对话
    logger.info(f"用户 {interaction.user.name} 触发手动分析，频道: {channel.name}")  # 记录手动分析
    problem = await asyncio.to_thread(analyze_ticket_conversation, conversation, channel, guild_id, config_manager.get_guild_config(guild_id), LLM_API_KEY, BASE_URL, MODEL_ID)
    if problem['is_valid']:  # 如果分析有效
        problem['id'] = await config_manager.get_next_problem_id()  # 分配 ID
        tg_channel_id = config_manager.get_guild_config(guild_id).get('tg_channel_id')
        if tg_channel_id:
            await telegram_bot.send_problem_form(problem, tg_channel_id)  # 发送到 Telegram
            logger.info(f"用户 {interaction.user.name} 手动分析完成，问题 ID: {problem['id']} 已发送到 {tg_channel_id}")  # 记录发送成功
        await interaction.followup.send(f"问题反馈已生成并同步，ID: {problem['id']}", ephemeral=True)
    else:
        logger.info(f"用户 {interaction.user.name} 手动分析结果无效，频道: {channel.name}")  # 记录无效结果
        await interaction.followup.send("分析结果无效，未生成问题反馈", ephemeral=True)

# 初始化 Telegram Bot 实例
telegram_bot = TelegramBot(TELEGRAM_TOKEN, config_manager, bot, LLM_API_KEY, BASE_URL, MODEL_ID)

# 主程序：同时启动 Discord 和 Telegram Bot
async def main():
    logger.info(f"启动 Discord Bot，Token: {DISCORD_TOKEN[:5]}...")  # 记录 Discord Bot 启动，仅显示 Token 前5位
    logger.info(f"启动 Telegram Bot，Token: {TELEGRAM_TOKEN[:5]}...")  # 记录 Telegram Bot 启动
    logger.info(f"LLM 配置 - API Key: {LLM_API_KEY[:5]}..., Base URL: {BASE_URL}, Model ID: {MODEL_ID}")  # 记录 LLM 配置
    await asyncio.gather(
        bot.start(DISCORD_TOKEN),  # 启动 Discord Bot
        telegram_bot.run()  # 启动 Telegram Bot
    )

# 程序入口
if __name__ == "__main__":
    asyncio.run(main())  # 运行主程序