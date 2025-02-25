import asyncio
import logging
from telegram.ext import Application, CommandHandler
from telegram import Update
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_general_conversation
from utils import get_conversation

# 设置日志，记录 Telegram Bot 的运行状态和错误
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot, llm_api_key, base_url, model_id):
        """
        初始化 Telegram Bot，并接收 LLM 相关参数。
        
        参数:
            token (str): Telegram Bot Token
            config_manager (ConfigManager): Discord 配置管理器
            discord_bot (discord.Bot): Discord Bot 实例
            llm_api_key (str): LLM API 密钥
            base_url (str): LLM API 基础 URL
            model_id (str): LLM 模型 ID
        """
        self.application = Application.builder().token(token).build()
        self.config_manager = config_manager
        self.discord_bot = discord_bot
        self.llm_api_key = llm_api_key
        self.base_url = base_url
        self.model_id = model_id
        logger.info("Telegram Bot 初始化完成")

    async def send_problem_form(self, problem, tg_channel_id):
        """
        发送问题反馈到指定的 Telegram 频道。
        
        参数:
            problem (dict): 问题反馈数据，包含 ID、类型、简述、来源等字段
            tg_channel_id (str): Telegram 频道 ID
        """
        form = f"ID: {problem['id']}\n**问题类型**: {problem['problem_type']}\n**简述**: {problem['summary']}\n**来源**: {problem['source']}"
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
            logger.info(f"发送问题到 {tg_channel_id}: {problem['problem_type']}")
        except Exception as e:
            logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def send_general_summary(self, summary, tg_channel_id):
        """
        发送 General Chat 对话总结到指定的 Telegram 频道。
        
        参数:
            summary (dict): 对话总结数据，包含发布时间、监控周期、情绪、讨论概述等字段
            tg_channel_id (str): Telegram 频道 ID
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
            logger.info(f"发送 General Chat 总结到 {tg_channel_id}")
        except Exception as e:
            logger.error(f"发送总结到 {tg_channel_id} 失败: {e}")

    async def periodic_general_analysis(self):
        """
        定时分析 General Chat 对话，生成总结并发送到 Telegram。

        - 每2小时执行一次。
        - 根据配置获取监控频道，分析指定周期内的对话。
        - 使用 LLM 生成总结报告。
        """
        while True:
            guilds_config = self.config_manager.config.get('guilds', {})
            for guild_id, config in guilds_config.items():
                guild = self.discord_bot.get_guild(int(guild_id))
                if guild:
                    monitor_channels = config.get('monitor_channels', [])
                    for channel_id in monitor_channels:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            period_hours = config.get('monitor_period', 3)  # 默认3小时
                            max_messages = config.get('monitor_max_messages', 100)  # 默认100条
                            since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)
                            messages = [msg async for msg in channel.history(limit=None, after=since)]
                            total_messages = len(messages)
                            monitored_messages = min(total_messages, max_messages)
                            conversation = await get_conversation(channel, limit=monitored_messages)
                            # 使用 LLM 分析对话，传递必要的参数
                            summary = analyze_general_conversation(conversation, channel, guild_id, config, self.llm_api_key, self.base_url, self.model_id)
                            summary['publish_time'] = datetime.datetime.now().isoformat()
                            summary['monitor_period'] = f"{period_hours} 小时"
                            summary['monitored_messages'] = monitored_messages
                            summary['total_messages'] = total_messages
                            tg_channel_id = config.get('tg_channel_id')
                            if tg_channel_id:
                                await self.send_general_summary(summary, tg_channel_id)
            await asyncio.sleep(7200)  # 每2小时执行一次

    async def run(self):
        """启动 Telegram Bot，初始化并运行定时任务和消息处理"""
        logger.info("Telegram Bot 启动中...")
        # 启动定时分析任务
        asyncio.create_task(self.periodic_general_analysis())
        # 初始化并运行 Telegram Bot
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot 已启动")
        await asyncio.Event().wait()