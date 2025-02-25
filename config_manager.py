import json
import threading
import os

CONFIG_FILE = 'config.json'  # 配置文件路径
config_lock = threading.Lock()  # 线程锁，确保配置读写安全

class ConfigManager:
    def __init__(self):
        # 初始化时加载配置
        self.config = self.load_config()

    def load_config(self):
        # 如果配置文件存在，读取它；否则返回默认配置
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {'telegram_users': {}, 'guilds': {}}

    def save_config(self):
        # 保存配置到文件，确保线程安全
        with config_lock:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)

    def get_guild_config(self, guild_id):
        # 获取某个 Discord 服务器的配置
        return self.config.get('guilds', {}).get(guild_id, {})

    def set_guild_config(self, guild_id, key, value):
        # 设置 Discord 服务器的配置项
        with config_lock:
            self.config.setdefault('guilds', {}).setdefault(guild_id, {})[key] = value
            self.save_config()

    def get_telegram_user_config(self, tg_user_id):
        # 获取 Telegram 用户的配置
        return self.config.get('telegram_users', {}).get(tg_user_id, {})

    def set_telegram_user_config(self, tg_user_id, key, value):
        # 设置 Telegram 用户的配置项
        with config_lock:
            self.config.setdefault('telegram_users', {}).setdefault(tg_user_id, {})[key] = value
            self.save_config()