import asyncio
import logging
from telegram.ext import Application, CommandHandler
from telegram import Update
import discord
import datetime
from config_manager import ConfigManager
from llm_analyzer import analyze_conversation
from utils import get_conversation

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot):
        """初始化 Telegram Bot"""
        self.application = Application.builder().token(token).build()
        self.config_manager = config_manager
        self.discord_bot = discord_bot
        logger.info("Telegram Bot 初始化完成")

    # 命令：设置要监控的 Discord 服务器
    async def set_discord_guild(self, update: Update, context):
        """处理 /set_discord_guild 命令，添加 Discord 服务器 ID"""
        tg_user_id = str(update.effective_user.id)
        if not context.args:
            await update.message.reply_text("请提供 Discord 服务器 ID，例如 /set_discord_guild 123456789")
            return
        guild_id = context.args[0]
        current_guilds = self.config_manager.config.get('telegram_users', {}).get(tg_user_id, {}).get('guild_ids', [])
        if guild_id not in current_guilds:
            current_guilds.append(guild_id)
            self.config_manager.config.setdefault('telegram_users', {}).setdefault(tg_user_id, {})['guild_ids'] = current_guilds
            await self.config_manager.save_config()
            logger.info(f"用户 {tg_user_id} 添加 Discord 服务器 ID: {guild_id}")
            await update.message.reply_text(f'已添加 Discord 服务器 ID: {guild_id}')
        else:
            await update.message.reply_text(f'服务器 ID {guild_id} 已在监控列表中')

    # 命令：设置 Telegram 通知频道
    async def set_tg_channel(self, update: Update, context):
        """处理 /set_tg_channel 命令，设置 Telegram 通知频道"""
        tg_user_id = str(update.effective_user.id)
        if not context.args:
            await update.message.reply_text("请提供 Telegram 频道 ID，例如 /set_tg_channel -100123456789")
            return
        tg_channel_id = context.args[0]
        self.config_manager.config.setdefault('telegram_users', {}).setdefault(tg_user_id, {})['tg_channel_id'] = tg_channel_id
        await self.config_manager.save_config()
        logger.info(f"用户 {tg_user_id} 设置 Telegram 通知频道: {tg_channel_id}")
        await update.message.reply_text(f'已设置 Telegram 通知频道: {tg_channel_id}')

    # 命令：获取当前 Telegram 群组/频道 ID
    async def get_tg_group_id(self, update: Update, context):
        """处理 /get_tg_group_id 命令，返回当前聊天 ID"""
        chat_id = update.effective_chat.id
        logger.info(f"用户查询 Telegram 群组 ID: {chat_id}")
        await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')

    async def send_problem_form(self, problem, tg_channel_id):
        """发送问题反馈到指定 Telegram 频道"""
        if problem and tg_channel_id:
            form = f"ID: {problem['id']}\n**问题类型**: {problem['problem_type']}\n**简述**: {problem['summary']}\n**来源**: {problem['source']}"
            try:
                await self.application.bot.send_message(chat_id=tg_channel_id, text=form)
                logger.info(f"发送问题到 {tg_channel_id}: {problem['problem_type']}")
            except Exception as e:
                logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def periodic_analysis(self):
        """每2小时分析 Discord 对话"""
        logger.info("开始定时分析 Discord 对话...")
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
                                                logger.info(f"定时分析发送问题 {{DC server ID: {guild_id} | 类型: {problem['problem_type']} | TG Channel ID: {tg_channel_id}}}")
                                                await self.send_problem_form(problem, tg_channel_id)
            except Exception as e:
                logger.error(f"定时分析任务错误: {e}")
            await asyncio.sleep(7200)  # 每2小时

    async def run(self):
        """启动 Telegram Bot"""
        logger.info("Telegram Bot 启动中...")
        # 添加命令处理器
        self.application.add_handler(CommandHandler('set_discord_guild', self.set_discord_guild))
        self.application.add_handler(CommandHandler('set_tg_channel', self.set_tg_channel))
        self.application.add_handler(CommandHandler('get_tg_group_id', self.get_tg_group_id))
        # 启动定时分析任务
        asyncio.create_task(self.periodic_analysis())
        # 初始化并运行 Telegram Bot
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot 已启动")
        # 等待事件循环结束
        await asyncio.Event().wait()
