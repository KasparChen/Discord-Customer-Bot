import asyncio
import json
import os

CONFIG_FILE = 'config.json'  # 配置文件路径
config_lock = asyncio.Lock()  # 异步锁，用于保护配置文件读写

class ConfigManager:
    def __init__(self):
        self.config = self.load_config()  # 加载配置文件
        self.problem_id_counter = self.config.get('problem_id_counter', 0)  # 初始化问题 ID 计数器

    # 加载配置文件，如果不存在则返回默认配置
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {'telegram_users': {}, 'guilds': {}, 'problem_id_counter': 0}  # 默认配置

    # 异步保存配置文件
    async def save_config(self):
        async with config_lock:  # 使用锁防止并发写入
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)  # 保存为 JSON 格式

    # 获取指定服务器的配置
    def get_guild_config(self, guild_id):
        return self.config.get('guilds', {}).get(guild_id, {})

    # 设置指定服务器的配置项
    async def set_guild_config(self, guild_id, key, value):
        self.config.setdefault('guilds', {}).setdefault(guild_id, {})[key] = value
        await self.save_config()  # 保存更改

    # 获取下一个问题 ID 并递增计数器
    async def get_next_problem_id(self):
        self.problem_id_counter += 1
        self.config['problem_id_counter'] = self.problem_id_counter
        await self.save_config()  # 保存计数器
        return self.problem_id_counter