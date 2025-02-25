import asyncio
import logging
from telegram.ext import Application
from telegram import Update
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_general_conversation
from utils import get_conversation

# 获取日志记录器
logger = logging.getLogger(__name__)

# 自定义过滤器：屏蔽 Telegram 的 getUpdates 日志，避免日志过于冗长
class NoGetUpdatesFilter(logging.Filter):
    def filter(self, record):
        return "getUpdates" not in record.getMessage()

for handler in logging.getLogger().handlers:
    handler.addFilter(NoGetUpdatesFilter())  # 为所有日志处理器添加过滤器

# Telegram Bot 类
class TelegramBot:
    def __init__(self, token, config_manager, discord_bot, llm_api_key, base_url, model_id):
        """初始化 Telegram Bot
        参数:
            token: Telegram Bot 的 Token
            config_manager: 配置管理器实例
            discord_bot: Discord Bot 实例，用于跨平台交互
            llm_api_key: LLM 的 API Key
            base_url: LLM 的基础 URL
            model_id: LLM 模型 ID
        """
        self.application = Application.builder().token(token).build()  # 创建 Telegram Bot 应用实例
        self.config_manager = config_manager
        self.discord_bot = discord_bot
        self.llm_api_key = llm_api_key
        self.base_url = base_url
        self.model_id = model_id
        logger.info("Telegram Bot 初始化完成")

    # 发送问题反馈到 Telegram
    async def send_problem_form(self, problem, tg_channel_id):
        """将问题反馈以指定格式发送到 Telegram 频道
        参数:
            problem: 问题字典，包含 id, problem_type, summary, source, timestamp, details 等字段
            tg_channel_id: 目标 Telegram 频道 ID
        """
        # 按照用户指定的格式生成消息
        form = (
            f"--- Issue Summary #{problem['id']} ---\n"
            f"问题类型: {problem['problem_type']}\n"
            f"问题简述: {problem['summary']}\n"
            f"来源: {problem['source']}\n"  # 使用 Ticket 频道的名称，例如 #1234-username
            f"时间: {problem['timestamp']}\n"
            f"问题详情: {problem['details']}\n"
            f"--------------------------"
        )
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form)  # 发送消息
            logger.info(f"问题已发送到 {tg_channel_id}: {problem['problem_type']}")
        except Exception as e:
            logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    # 发送 General Chat 总结到 Telegram
    async def send_general_summary(self, summary, tg_channel_id):
        """将 General Chat 的总结发送到 Telegram 频道
        参数:
            summary: 总结字典，包含 publish_time, monitor_period, monitored_messages 等字段
            tg_channel_id: 目标 Telegram 频道 ID
        """
        form = (
            f"发布时间: {summary['publish_time']}\n"
            f"监控周期: {summary['monitor_period']}\n"
            f"监控消息数: {summary['monitored_messages']}\n"
            f"周期内消息数: {summary['total_messages']}\n"
            f"情绪: {summary['emotion']}\n"
            f"讨论概述: {summary['discussion_summary']}\n"
            f"重点关注事件: {summary['key_events']}"
        )
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
            logger.info(f"General Chat 总结已发送到 {tg_channel_id}")
        except Exception as e:
            logger.error(f"发送总结到 {tg_channel_id} 失败: {e}")

    # 定期分析 General Chat
    async def periodic_general_analysis(self):
        """定期分析所有配置的 General Chat 频道，并发送总结"""
        while True:  # 无限循环，持续运行
            guilds_config = self.config_manager.config.get('guilds', {})  # 获取所有服务器配置
            for guild_id, config in guilds_config.items():
                guild = self.discord_bot.get_guild(int(guild_id))  # 获取服务器对象
                if guild:
                    monitor_channels = config.get('monitor_channels', [])  # 获取监控频道列表
                    for channel_id in monitor_channels:
                        channel = guild.get_channel(channel_id)  # 获取频道对象
                        if channel:
                            period_hours = config.get('monitor_period', 3)  # 默认周期3小时
                            max_messages = config.get('monitor_max_messages', 100)  # 默认最大消息数100
                            since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)  # 计算起始时间
                            messages = [msg async for msg in channel.history(limit=None, after=since)]  # 获取周期内消息
                            total_messages = len(messages)  # 总消息数
                            monitored_messages = min(total_messages, max_messages)  # 实际监控的消息数
                            conversation = await get_conversation(channel, limit=monitored_messages)  # 获取对话
                            # 使用 LLM 分析对话
                            summary = analyze_general_conversation(conversation, channel, guild_id, config, self.llm_api_key, self.base_url, self.model_id)
                            summary['publish_time'] = datetime.datetime.now().isoformat()  # 添加发布时间
                            summary['monitor_period'] = f"{period_hours} 小时"  # 记录监控周期
                            summary['monitored_messages'] = monitored_messages  # 记录监控消息数
                            summary['total_messages'] = total_messages  # 记录总消息数
                            tg_channel_id = config.get('tg_channel_id')  # 获取 Telegram 频道 ID
                            if tg_channel_id:
                                await self.send_general_summary(summary, tg_channel_id)  # 发送总结
            await asyncio.sleep(7200)  # 每2小时检查一次（7200秒）

    # 启动 Telegram Bot
    async def run(self):
        """启动 Telegram Bot 的主循环"""
        logger.info("Telegram Bot 启动中...")
        asyncio.create_task(self.periodic_general_analysis())  # 启动定期分析任务
        await self.application.initialize()  # 初始化应用
        await self.application.start()  # 启动应用
        # 开始轮询 Telegram 更新
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot 已启动")
        await asyncio.Event().wait()  # 保持运行