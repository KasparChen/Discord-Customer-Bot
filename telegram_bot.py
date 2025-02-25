import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
import logging
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_conversation
from utils import get_conversation, is_ticket_channel

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot):
        self.application = Application.builder().token(token).build()  # 初始化 Telegram Bot
        self.config_manager = config_manager  # 配置管理器
        self.discord_bot = discord_bot  # Discord Bot 实例
        logger.info("Telegram Bot 正在初始化...")

    # 发送问题反馈到 Telegram 频道
    async def send_problem_form(self, problem, tg_channel_id):
        if problem and tg_channel_id:
            # 格式化问题反馈内容
            form = f"ID: {problem['id']}\n**问题类型**: {problem['problem_type']}\n**简述**: {problem['summary']}\n**来源**: {problem['source']}"
            try:
                await self.application.bot.send_message(chat_id=tg_channel_id, text=form)  # 发送到 Telegram
                logger.info(f"发送问题到 {tg_channel_id}: {problem['problem_type']}")
            except Exception as e:
                logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    # 定时分析 Discord 对话（每 2 小时一次）
    async def periodic_analysis(self):
        logger.info("Telegram Bot 开始定时分析 Discord 对话...")
        while True:
            try:
                guilds_config = self.config_manager.config.get('guilds', {})
                for guild_id, config in guilds_config.items():
                    guild = self.discord_bot.get_guild(int(guild_id))
                    if guild:
                        for category_id in config.get('ticket_category_ids', []):
                            category = discord.utils.get(guild.categories, id=category_id)
                            if category:
                                for channel in category.text_channels:
                                    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
                                    messages = [msg async for msg in channel.history(after=since)]
                                    if messages:
                                        conversation = await get_conversation(channel)
                                        problem = analyze_conversation(conversation, channel, guild_id, config, "your_llm_api_key", "https://ark.cn-beijing.volces.com/api/v3", "your_model_id")
                                        if problem and problem['is_valid']:
                                            problem['id'] = await self.config_manager.get_next_problem_id()
                                            tg_channel_id = config.get('tg_channel_id')
                                            if tg_channel_id:
                                                logger.info(f"定时分析并发送问题 {{DC server ID: {guild_id} | 类型: {problem['problem_type']} | TG Channel ID: {tg_channel_id}}}")
                                                await self.send_problem_form(problem, tg_channel_id)
            except Exception as e:
                logger.error(f"定时分析任务发生错误: {e}")
            await asyncio.sleep(7200)  # 每 2 小时检查一次

    # 运行 Telegram Bot
    def run(self):
        logger.info("Telegram Bot 正在启动...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(self.periodic_analysis())  # 启动定时分析任务
        loop.run_until_complete(self.application.initialize())
        loop.run_until_complete(self.application.start())
        logger.info("Telegram Bot 已成功启动")
        loop.run_forever()