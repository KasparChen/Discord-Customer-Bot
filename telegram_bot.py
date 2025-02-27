import asyncio
import logging
from telegram.ext import Application, CommandHandler
from telegram import Update
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_general_conversation
from utils import get_conversation
from datetime import timezone, timedelta
import urllib.parse

logger = logging.getLogger(__name__)

# 自定义过滤器：屏蔽非错误级别的 getUpdates 日志，避免日志污染
class NoGetUpdatesFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "getUpdates" in msg and record.levelno < logging.ERROR:
            return False
        return True

for handler in logging.getLogger().handlers:
    handler.addFilter(NoGetUpdatesFilter())

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot, llm_api_key, base_url, model_id):
        """初始化 Telegram Bot"""
        self.application = Application.builder().token(token).build()  # 创建 Telegram Application 实例
        self.config_manager = config_manager  # 配置管理器实例
        self.discord_bot = discord_bot  # Discord Bot 实例，用于跨平台交互
        self.llm_api_key = llm_api_key  # LLM API 密钥
        self.base_url = base_url  # LLM API 基础 URL
        self.model_id = model_id  # LLM 模型 ID
        self.heartbeat_channels = set()  # 存储启用了心跳日志接收的 Telegram 频道 ID
        logger.info("Telegram Bot 初始化完成")

    async def send_problem_form(self, problem, tg_channel_id):
        """
        将问题反馈发送到指定的 Telegram 频道，使用简洁的 HTML 格式。
        
        参数:
            problem (dict): 包含问题信息的字典，键包括 id, problem_type, summary, source, timestamp, details, link
            tg_channel_id (str): Telegram 频道的 ID
        """
        # 构建简洁的 HTML 格式消息
        form = (
            f"<b>----- Issue #{problem['id']} -----</b>\n"  # 使用 <b> 标签加粗标题
            f"类型: {problem['problem_type']}\n"
            f"来源: {problem['source']}\n"
            f"时间: {problem['timestamp']}\n"
            f"简述: {problem['summary']}\n"
            f"详情: {problem['details']}\n"
            f"<a href=\"{problem['link']}\">🔗 跳转至 Ticket</a>\n"  # 简洁的超链接
            f"-----------------------------------\n"
        )
        
        try:
            # 发送 HTML 格式的消息
            await self.application.bot.send_message(
                chat_id=tg_channel_id,
                text=form,
                parse_mode='HTML',  # 指定解析模式为 HTML
                disable_web_page_preview=True  # 禁用链接预览
            )
            logger.info(f"问题已发送到 {tg_channel_id}: {problem['problem_type']}")
        except Exception as e:
            logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def send_general_summary(self, summary, tg_channel_id):
        """将 General Chat 总结发送到指定的 Telegram 频道"""
        form = (
            f"===== Chat Summary =====\n"
            f"发布时间: {summary['publish_time']}\n"  # 使用格式化后的时间戳 yyyy-mm-dd HH:MM UTC+{x}
            f"监控周期: {summary['monitor_period']}\n"
            f"监控消息数: {summary['monitored_messages']}\n"
            f"周期内消息数: {summary['total_messages']}\n"
            f"情绪: {summary['emotion']}\n"
            f"讨论概述: {summary['discussion_summary']}\n"
            f"重点关注事件: {summary['key_events']}\n"
            f"========================="
        )
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
            logger.info(f"General Chat 总结已发送到 {tg_channel_id}")
        except Exception as e:
            logger.error(f"发送总结到 {tg_channel_id} 失败: {e}")

    async def periodic_general_analysis(self):
        """定期分析 Discord General Chat 频道并发送总结到 Telegram"""
        while True:
            guilds_config = self.config_manager.config.get('guilds', {})  # 获取所有服务器配置
            for guild_id, config in guilds_config.items():
                guild = self.discord_bot.get_guild(int(guild_id))  # 获取 Discord 服务器对象
                if guild:
                    monitor_channels = config.get('monitor_channels', [])  # 获取监控频道列表
                    for channel_id in monitor_channels:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            period_hours = config.get('monitor_period', 3)  # 默认监控周期为3小时
                            max_messages = config.get('monitor_max_messages', 100)  # 默认最大消息数为100
                            since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)  # 计算时间范围
                            messages = [msg async for msg in channel.history(limit=None, after=since)]  # 获取消息
                            total_messages = len(messages)
                            monitored_messages = min(total_messages, max_messages)  # 限制分析的消息数量
                            conversation = await get_conversation(channel, limit=monitored_messages)  # 获取对话内容
                            summary = analyze_general_conversation(  # 使用 LLM 分析
                                conversation, channel, guild_id, config,
                                self.llm_api_key, self.base_url, self.model_id
                            )
                            # 获取时区偏移并格式化发布时间
                            timezone_offset = config.get('timezone', 0)
                            tz = timezone(timedelta(hours=timezone_offset))
                            local_time = datetime.datetime.now(tz)
                            formatted_publish_time = local_time.strftime("%Y-%m-%d %H:%M") + f" UTC+{timezone_offset}"
                            summary['publish_time'] = formatted_publish_time
                            summary['monitor_period'] = f"{period_hours} 小时"
                            summary['monitored_messages'] = monitored_messages
                            summary['total_messages'] = total_messages
                            tg_channel_id = config.get('tg_channel_id')
                            if tg_channel_id:
                                await self.send_general_summary(summary, tg_channel_id)  # 发送总结
            await asyncio.sleep(7200)  # 每2小时（7200秒）执行一次

    async def get_group_id(self, update: Update, context):
        """Telegram 命令：获取当前群组或频道的 ID"""
        chat_id = update.effective_chat.id
        await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')
        logger.info(f"用户 {update.effective_user.id} 查询了 Telegram 群组/频道 ID: {chat_id}")

    async def current_binding(self, update: Update, context):
        """Telegram 命令：查看与当前 Telegram 频道绑定的 Discord 服务器"""
        current_tg_channel_id = str(update.effective_chat.id)
        bound_servers = []
        guilds_config = self.config_manager.config.get('guilds', {})
        for guild_id, config in guilds_config.items():
            if config.get('tg_channel_id') == current_tg_channel_id:
                guild = self.discord_bot.get_guild(int(guild_id))
                if guild:
                    bound_servers.append({
                        'name': guild.name,
                        'id': guild_id
                    })
        if bound_servers:
            response = "当前绑定的 Discord 服务器:\n"
            for server in bound_servers:
                response += f"- {server['name']} (ID: {server['id']})\n"
            response += f"总绑定服务器数量: {len(bound_servers)}"
        else:
            response = "当前没有绑定的 Discord 服务器"
        await update.message.reply_text(response)
        logger.info(f"用户 {update.effective_user.id} 查询了当前绑定的 Discord 服务器")

    async def heartbeat_on(self, update: Update, context):
        """Telegram 命令：开启心跳日志接收"""
        chat_id = update.effective_chat.id
        if chat_id not in self.heartbeat_channels:
            self.heartbeat_channels.add(chat_id)
            await update.message.reply_text("心跳日志接收已开启")
            logger.info(f"频道 {chat_id} 开启了心跳日志接收")
        else:
            await update.message.reply_text("心跳日志接收已处于开启状态")

    async def heartbeat_off(self, update: Update, context):
        """Telegram 命令：关闭心跳日志接收"""
        chat_id = update.effective_chat.id
        if chat_id in self.heartbeat_channels:
            self.heartbeat_channels.remove(chat_id)
            await update.message.reply_text("心跳日志接收已关闭")
            logger.info(f"频道 {chat_id} 关闭了心跳日志接收")
        else:
            await update.message.reply_text("心跳日志接收未开启")

    async def send_heartbeat_logs(self):
        """定期发送心跳日志到启用的 Telegram 频道"""
        while True:
            await asyncio.sleep(60)  # 每60秒检查一次
            if self.heartbeat_channels:
                with open('heartbeat.log', 'r') as f:
                    lines = f.readlines()
                    if lines:
                        latest_log = lines[-1].strip()  # 获取最新一行日志，已包含 UTC+8 时间戳
                        for chat_id in self.heartbeat_channels:
                            try:
                                await self.application.bot.send_message(chat_id=chat_id, text=f"心跳日志: {latest_log}")
                            except Exception as e:
                                logger.error(f"发送心跳日志到 {chat_id} 失败: {e}")

    async def run(self):
        """启动 Telegram Bot 的主循环"""
        logger.info("Telegram Bot 启动中...")
        # 注册命令处理器
        self.application.add_handler(CommandHandler('get_group_id', self.get_group_id))
        self.application.add_handler(CommandHandler('current_binding', self.current_binding))
        self.application.add_handler(CommandHandler('heartbeat_on', self.heartbeat_on))
        self.application.add_handler(CommandHandler('heartbeat_off', self.heartbeat_off))
        # 启动定期任务
        asyncio.create_task(self.periodic_general_analysis())  # 启动 General Chat 分析任务
        asyncio.create_task(self.send_heartbeat_logs())  # 启动心跳日志发送任务
        # 初始化并运行 Telegram Bot
        await self.application.initialize()
        await self.application.start()
        # 开始轮询 Telegram 更新
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot 已启动")
        await asyncio.Event().wait()  # 保持运行