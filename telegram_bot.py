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

logger = logging.getLogger(__name__)

# 自定义过滤器，屏蔽非错误级别的 getUpdates 日志，避免日志污染
class NoGetUpdatesFilter(logging.Filter):
    def filter(self, record):
        """
        过滤掉非错误级别的 getUpdates 日志。
        
        Args:
            record (logging.LogRecord): 日志记录对象
        
        Returns:
            bool: True 表示保留日志，False 表示过滤掉
        """
        msg = record.getMessage()
        if "getUpdates" in msg and record.levelno < logging.ERROR:
            return False
        return True

for handler in logging.getLogger().handlers:
    handler.addFilter(NoGetUpdatesFilter())

class TelegramBot:
    def __init__(self, token, config_manager, discord_bot, default_llm_api_key, default_base_url, default_model_id):
        """
        初始化 Telegram Bot，设置基本属性。
        
        Args:
            token (str): Telegram Bot 的 Token
            config_manager (ConfigManager): 配置管理器实例
            discord_bot (discord.Bot): Discord Bot 实例
            default_llm_api_key (str): 默认 LLM API 密钥
            default_base_url (str): 默认 LLM API 基础 URL
            default_model_id (str): 默认 LLM 模型 ID
        """
        self.application = Application.builder().token(token).build()  # 创建 Telegram Application 实例
        self.config_manager = config_manager  # 用于访问配置
        self.discord_bot = discord_bot  # 用于跨平台交互
        self.default_llm_api_key = default_llm_api_key  # 默认 LLM 配置
        self.default_base_url = default_base_url
        self.default_model_id = default_model_id
        self.heartbeat_channels = set()  # 存储启用了心跳日志接收的 Telegram 频道 ID
        self.is_polling = False  # 标志位，跟踪轮询状态
        logger.info("Telegram Bot 初始化完成")

    async def send_problem_form(self, problem, tg_channel_id):
        """
        将问题反馈以 HTML 格式发送到指定的 Telegram 频道。
        
        Args:
            problem (dict): 问题信息，包含 id、problem_type、summary 等字段
            tg_channel_id (str): Telegram 频道 ID
        """
        # 构建简洁的 HTML 格式消息，使用 <b> 加粗关键信息
        form = (
            f"<b>----- Issue #{problem['id']} -----</b>\n"
            f"类型: <b>{problem['problem_type']}</b>\n\n"
            f"来源: <b>{problem['source']}</b>\n\n"
            f"时间: <b>{problem['timestamp']}</b>\n\n"
            f"简述: {problem['summary']}\n\n"
            f"详情: {problem['details']}\n\n"
            f"<a href=\"{problem['link']}\"><em>🔗 跳转至 Ticket</em></a>\n"
            f"------------------------------------------"
        )
        try:
            await self.application.bot.send_message(
                chat_id=tg_channel_id,
                text=form,
                parse_mode='HTML',  # 指定 HTML 解析模式
                disable_web_page_preview=True  # 禁用链接预览
            )
            logger.info(f"问题已发送到 {tg_channel_id}: {problem['problem_type']}")
        except Exception as e:
            logger.error(f"发送问题到 {tg_channel_id} 失败: {e}")

    async def send_general_summary(self, summary, tg_channel_id):
        """
        将 General Chat 总结发送到指定的 Telegram 频道。
        
        Args:
            summary (dict): 总结信息，包含 emotion、discussion_summary 等字段
            tg_channel_id (str): Telegram 频道 ID
        """
        form = (
            f"<b>===== Chat Summary =====</b>\n"
            f"发布时间: <b>{summary['publish_time']}</b>\n\n"
            f"监控周期: <b>{summary['monitor_period']}</b>\n\n"
            f"监控消息数: <b>{summary['monitored_messages']}</b>\n\n"
            f"周期内消息数: <b>{summary['total_messages']}</b>\n\n"
            f"情绪: <b>{summary['emotion']}</b>\n\n"
            f"讨论概述: {summary['discussion_summary']}\n\n"
            f"重点关注事件: {summary['key_events']}\n\n"
            f"建议: {summary['suggestion']}\n"
            f"============================"
        )
        try:
            await self.application.bot.send_message(chat_id=tg_channel_id, text=form, parse_mode='HTML')
            logger.info(f"General Chat 总结已发送到 {tg_channel_id}")
        except Exception as e:
            logger.error(f"发送总结到 {tg_channel_id} 失败: {e}")

    async def periodic_general_analysis(self):
        """
        定期分析 Discord General Chat 频道并发送总结到 Telegram。
        - 监控周期根据每个服务器的 monitor_period 动态调整，确保监控周期=回溯周期。
        - 如果 Bot 未激活，则跳过分析。
        """
        while True:
            if not self.config_manager.is_bot_activated():
                logger.info("Bot 未激活，跳过 General Chat 分析")
                await asyncio.sleep(60)  # 未激活时每分钟检查一次，避免频繁空转
                continue
            
            guilds_config = self.config_manager.config.get('guilds', {})
            min_sleep = float('inf')  # 用于记录下次最早执行时间
            
            for guild_id, config in guilds_config.items():
                guild = self.discord_bot.get_guild(int(guild_id))
                if not guild:
                    continue
                
                monitor_channels = config.get('monitor_channels', [])
                period_hours = config.get('monitor_period', 2)  # 默认 2 小时
                period_seconds = period_hours * 3600  # 转换为秒
                
                for channel_id in monitor_channels:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        max_messages = config.get('monitor_max_messages', 100)  # 默认 100 条
                        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=period_hours)
                        messages = [msg async for msg in channel.history(limit=None, after=since)]
                        total_messages = len(messages)
                        monitored_messages = min(total_messages, max_messages)
                        conversation = await get_conversation(channel, limit=monitored_messages)
                        llm_config = self.config_manager.get_llm_config(guild_id) or {
                            'api_key': self.default_llm_api_key,
                            'model_id': self.default_model_id,
                            'base_url': self.default_base_url
                        }
                        summary = analyze_general_conversation(
                            conversation, channel, guild_id, config,
                            llm_config['api_key'], llm_config['base_url'], llm_config['model_id']
                        )
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
                            await self.send_general_summary(summary, tg_channel_id)
                
                # 更新下次最早执行时间
                min_sleep = min(min_sleep, period_seconds)
            
            # 等待下次执行，使用所有服务器中最短的周期
            sleep_duration = min_sleep if min_sleep != float('inf') else 7200  # 默认 2 小时
            logger.info(f"下次 General Chat 分析将在 {sleep_duration / 3600} 小时后执行")
            await asyncio.sleep(sleep_duration)

    async def get_group_id(self, update: Update, context):
        """
        Telegram 命令：获取当前群组或频道的 ID。
        
        Args:
            update (Update): Telegram 更新对象
            context: 命令上下文
        """
        chat_id = update.effective_chat.id
        await update.message.reply_text(f'当前 Telegram 群组/频道 ID: {chat_id}')

    async def current_binding(self, update: Update, context):
        """
        Telegram 命令：查看与当前 Telegram 频道绑定的 Discord 服务器。
        
        Args:
            update (Update): Telegram 更新对象
            context: 命令上下文
        """
        current_tg_channel_id = str(update.effective_chat.id)
        bound_servers = []
        guilds_config = self.config_manager.config.get('guilds', {})
        for guild_id, config in guilds_config.items():
            if config.get('tg_channel_id') == current_tg_channel_id:
                guild = self.discord_bot.get_guild(int(guild_id))
                if guild:
                    bound_servers.append({'name': guild.name, 'id': guild_id})
        response = "当前绑定的 Discord 服务器:\n" + "\n".join([f"- {s['name']} (ID: {s['id']})" for s in bound_servers]) if bound_servers else "当前没有绑定的 Discord 服务器"
        await update.message.reply_text(response)

    async def heartbeat_on(self, update: Update, context):
        """
        Telegram 命令：开启心跳日志接收，每分钟推送一次。
        
        Args:
            update (Update): Telegram 更新对象
            context: 命令上下文
        """
        chat_id = update.effective_chat.id
        if chat_id not in self.heartbeat_channels:
            self.heartbeat_channels.add(chat_id)
            await update.message.reply_text("心跳日志接收已开启")
        else:
            await update.message.reply_text("心跳日志接收已处于开启状态")

    async def heartbeat_off(self, update: Update, context):
        """
        Telegram 命令：关闭心跳日志接收。
        
        Args:
            update (Update): Telegram 更新对象
            context: 命令上下文
        """
        chat_id = update.effective_chat.id
        if chat_id in self.heartbeat_channels:
            self.heartbeat_channels.remove(chat_id)
            await update.message.reply_text("心跳日志接收已关闭")
        else:
            await update.message.reply_text("心跳日志接收未开启")

    async def send_heartbeat_logs(self):
        """
        定期发送心跳日志到启用了接收的 Telegram 频道。
        - 每 60 秒检查并发送最新日志。
        """
        while True:
            await asyncio.sleep(60)
            if self.heartbeat_channels:
                with open('heartbeat.log', 'r') as f:
                    lines = f.readlines()
                    if lines:
                        latest_log = lines[-1].strip()
                        for chat_id in self.heartbeat_channels:
                            try:
                                await self.application.bot.send_message(chat_id=chat_id, text=f"心跳日志: {latest_log}")
                            except Exception as e:
                                logger.error(f"发送心跳日志到 {chat_id} 失败: {e}")

    async def run(self):
        """
        启动 Telegram Bot 的主循环，注册命令并开始轮询。
        """
        logger.info("Telegram Bot 启动中...")
        
        # 检查是否已在轮询
        if self.is_polling:
            logger.warning("Telegram Bot 已在轮询中，跳过重复启动")
            return
        
        # 注册 Telegram 命令处理器
        self.application.add_handler(CommandHandler('get_group_id', self.get_group_id))
        self.application.add_handler(CommandHandler('current_binding', self.current_binding))
        self.application.add_handler(CommandHandler('heartbeat_on', self.heartbeat_on))
        self.application.add_handler(CommandHandler('heartbeat_off', self.heartbeat_off))
        
        # 启动定期任务
        asyncio.create_task(self.periodic_general_analysis())
        asyncio.create_task(self.send_heartbeat_logs())
        
        try:
            await self.application.initialize()
            await self.application.start()
            logger.info("准备启动 Telegram 轮询...")
            self.is_polling = True
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            logger.info("Telegram Bot 已启动并开始轮询")
            await asyncio.Event().wait()  # 保持运行
        except Exception as e:
            self.is_polling = False
            if "Conflict" in str(e):
                logger.error(f"Telegram 轮询冲突: {e} - 请确保没有其他实例使用相同 TOKEN，或者等待之前的轮询终止")
            else:
                logger.error(f"Telegram Bot 启动失败: {e}")
            raise
        finally:
            self.is_polling = False
            logger.info("Telegram Bot 轮询已停止")