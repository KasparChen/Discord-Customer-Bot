import asyncio
import logging
from telegram.ext import Application, CommandHandler
from telegram import Update
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_general_conversation
from utils import get_conversation

# 设置日志记录器
logger = logging.getLogger(__name__)

# 自定义过滤器：屏蔽 Telegram 的 getUpdates 日志，避免频繁记录
class NoGetUpdatesFilter(logging.Filter):
    def filter(self, record):
        return "getUpdates" not in record.getMessage()

for handler in logging.getLogger().handlers:
    handler.addFilter(NoGetUpdatesFilter())

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot, llm_api_key, base_url, model_id):
        """初始化 Telegram Bot
        参数:
            token: Telegram Bot 的 Token
            config_manager: 配置管理器实例，用于读取和管理配置
            discord_bot: Discord Bot 实例，用于跨平台交互
            llm_api_key: LLM 的 API Key
            base_url: LLM 的基础 URL
            model_id: LLM 模型 ID
        """
        self.application = Application.builder().token(token).build()
        self.config_manager = config_manager
        self.discord_bot = discord_bot
        self.llm_api_key = llm_api_key
        self.base_url = base_url
        self.model_id = model_id
        logger.info("Telegram Bot 初始化完成")

    async def send_problem_form(self, problem, tg_channel_id):
        """将问题反馈以指定格式发送到 Telegram 频道
        参数:
            problem: 问题字典，包含 id, problem_type, summary, source, timestamp, details 等字段
            tg_channel_id: 目标 Telegram 频道 ID
        """
        form = (
            f"--- Issue Summary #{problem['id']} ---\n"
            f"问题类型: {problem['problem_type']}\n"
            f"问题简述: {problem['summary']}\n"
            f"来源: {problem['source']}\n"
            f"时间: {problem['timestamp']}\n"
            f"问题详情: {problem['details']}\n"
            f"-----------------------------"
        )
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
            logger.info(f"问题已发送到 {tg_channel_id}: {problem['problem_type']}")
        except Exception as e:
            logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def send_general_summary(self, summary, tg_channel_id):
        """将 General Chat 的总结发送到 Telegram 频道
        参数:
            summary: 总结字典，包含 publish_time, monitor_period, monitored_messages 等字段
            tg_channel_id: 目标 Telegram 频道 ID
        """
        form = (
            f"===== Chat Summary =====\n"
            f"发布时间: {summary['publish_time']}\n"
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
        """定期分析所有配置的 General Chat 频道，并发送总结"""
        while True:
            guilds_config = self.config_manager.config.get('guilds', {})
            for guild_id, config in guilds_config.items():
                guild = self.discord_bot.get_guild(int(guild_id))
                if guild:
                    monitor_channels = config.get('monitor_channels', [])
                    for channel_id in monitor_channels:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            period_hours = config.get('monitor_period', 3)
                            max_messages = config.get('monitor_max_messages', 100)
                            since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)
                            messages = [msg async for msg in channel.history(limit=None, after=since)]
                            total_messages = len(messages)
                            monitored_messages = min(total_messages, max_messages)
                            conversation = await get_conversation(channel, limit=monitored_messages)
                            summary = analyze_general_conversation(
                                conversation, channel, guild_id, config,
                                self.llm_api_key, self.base_url, self.model_id
                            )
                            summary['publish_time'] = datetime.datetime.now().isoformat()
                            summary['monitor_period'] = f"{period_hours} 小时"
                            summary['monitored_messages'] = monitored_messages
                            summary['total_messages'] = total_messages
                            tg_channel_id = config.get('tg_channel_id')
                            if tg_channel_id:
                                await self.send_general_summary(summary, tg_channel_id)
            await asyncio.sleep(7200)  # 每2小时检查一次

    async def get_tg_group_id(self, update: Update, context):
        """获取当前 Telegram 群组或频道的 ID
        命令: /get_tg_group_id
        """
        chat_id = update.effective_chat.id
        await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')
        logger.info(f"用户 {update.effective_user.id} 查询了 Telegram 群组/频道 ID: {chat_id}")

    async def current_binding(self, update: Update, context):
        """查看与当前 Telegram 频道绑定的 Discord 服务器信息
        命令: /current_binding
        功能: 返回绑定到当前 Telegram 频道的 Discord 服务器数量、名称和 ID
        """
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

    async def run(self):
        """启动 Telegram Bot 的主循环"""
        logger.info("Telegram Bot 启动中...")
        # 注册命令处理器
        self.application.add_handler(CommandHandler('get_tg_group_id', self.get_tg_group_id))
        self.application.add_handler(CommandHandler('current_binding', self.current_binding))
        # 启动定期分析任务
        asyncio.create_task(self.periodic_general_analysis())
        # 初始化并运行 Telegram Bot
        await self.application.initialize()
        await self.application.start()
        # 开始轮询 Telegram 更新
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot 已启动")
        await asyncio.Event().wait()  # 保持运行
