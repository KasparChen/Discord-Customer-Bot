import asyncio
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
import logging
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_conversation
from utils import get_conversation, is_ticket_channel

# 设置 telegram 模块的日志级别为 WARNING，减少轮询日志输出
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot):
        self.application = Application.builder().token(token).build()
        self.config_manager = config_manager
        self.discord_bot = discord_bot
        logger.info("Telegram Bot 正在初始化...")

    async def set_discord_guild(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_user_id = str(update.effective_user.id)
        if not context.args:
            await update.message.reply_text("请提供 Discord 服务器 ID，例如：/set_discord_guild 123456789")
            return
        guild_id = context.args[0]
        current_guilds = self.config_manager.get_telegram_user_config(tg_user_id).get('guild_ids', [])
        self.config_manager.set_telegram_user_config(tg_user_id, 'guild_ids', current_guilds + [guild_id])
        logger.info(f"用户 {tg_user_id} 添加了 Discord 服务器 ID: {guild_id}")
        await update.message.reply_text(f'已添加监听 Discord 服务器 ID: {guild_id}')

    async def set_tg_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_user_id = str(update.effective_user.id)
        if not context.args:
            await update.message.reply_text("请提供 Telegram 频道 ID，例如：/set_tg_channel -100123456789")
            return
        tg_channel_id = context.args[0]
        self.config_manager.set_telegram_user_config(tg_user_id, 'tg_channel_id', tg_channel_id)
        logger.info(f"用户 {tg_user_id} 设置 Telegram 推送频道为: {tg_channel_id}")
        await update.message.reply_text(f'已设置 Telegram 推送频道: {tg_channel_id}')

    async def get_tg_group_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        logger.info(f"Telegram 用户查询群组 ID: {chat_id}")
        await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')

    async def send_problem_form(self, problem, tg_channel_id):
        if problem and tg_channel_id:
            form = f"**问题类型**: {problem['problem_type']}\n**简述**: {problem['summary']}\n**来源**: {problem['source']}"
            try:
                await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
                logger.info(f"Telegram Bot 发送问题到 {tg_channel_id}: {problem['problem_type']}")
            except Exception as e:
                logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def periodic_analysis(self):
        logger.info("Telegram Bot 开始定时分析 Discord 对话...")
        while True:
            try:
                guilds_config = self.config_manager.config.get('guilds', {})
                telegram_users = self.config_manager.config.get('telegram_users', {})
                for guild_id, config in guilds_config.items():
                    guild = self.discord_bot.get_guild(int(guild_id))
                    if guild:
                        for category_id in config.get('monitor_category_ids', []):
                            category = discord.utils.get(guild.categories, id=category_id)
                            if category:
                                for channel in category.text_channels:
                                    since = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
                                    messages = [msg async for msg in channel.history(after=since)]
                                    if messages:
                                        problem = analyze_conversation(messages, channel, guild_id, config, "your_llm_api_key", "https://ark.cn-beijing.volces.com/api/v3", "your_model_id")
                                        if problem:
                                            for tg_user, settings in telegram_users.items():
                                                if guild_id in settings.get('guild_ids', []):
                                                    logger.info(f"Telegram Bot 定时任务采集并发送问题 {{DC server ID: {guild_id} | 类型: {problem['problem_type']} | TG Channel ID: {settings['tg_channel_id']}}}")
                                                    await self.send_problem_form(problem, settings['tg_channel_id'])
            except Exception as e:
                logger.error(f"定时分析任务发生错误: {e}")
            await asyncio.sleep(7200)  # 每 2 小时检查一次

    async def run(self):
        logger.info("Telegram Bot 正在启动...")
        # 注册指令处理函数
        self.application.add_handler(CommandHandler('set_discord_guild', self.set_discord_guild))
        self.application.add_handler(CommandHandler('set_tg_channel', self.set_tg_channel))
        self.application.add_handler(CommandHandler('get_tg_group_id', self.get_tg_group_id))
        # 启动定时分析任务
        asyncio.create_task(self.periodic_analysis())
        # 初始化并启动 bot
        await self.application.initialize()
        await self.application.start()
        logger.info("Telegram Bot 已成功启动")
        # 运行轮询，忽略启动前的更新
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        # 保持事件循环运行
        await asyncio.Event().wait()