import asyncio
import json
import os

CONFIG_FILE = 'config.json'  # 配置文件路径
config_lock = asyncio.Lock()  # 异步锁，确保配置写入安全

class ConfigManager:
    def __init__(self):
        """初始化配置管理器，加载配置文件。"""
        self.config = self.load_config()
        self.problem_id_counter = self.config.get('problem_id_counter', 0)

    def load_config(self):
        """加载配置文件，如果文件不存在，返回默认配置。"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {'telegram_users': {}, 'guilds': {}, 'problem_id_counter': 0}

    async def save_config(self):
        """异步保存配置文件，使用锁防止并发写入冲突。"""
        async with config_lock:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)

    def get_guild_config(self, guild_id):
        """获取指定服务器的配置。"""
        return self.config.get('guilds', {}).get(guild_id, {})

    async def set_guild_config(self, guild_id, key, value):
        """设置指定服务器的配置项并保存。"""
        self.config.setdefault('guilds', {}).setdefault(guild_id, {})[key] = value
        await self.save_config()

    async def get_next_problem_id(self):
        """生成并返回下一个问题 ID，更新计数器并保存。"""
        self.problem_id_counter += 1
        self.config['problem_id_counter'] = self.problem_id_counter
        await self.save_config()
        return self.problem_id_counter