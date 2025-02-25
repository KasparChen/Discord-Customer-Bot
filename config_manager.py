import asyncio
import json
import os

CONFIG_FILE = 'config.json'  # 配置文件路径
config_lock = asyncio.Lock()  # 异步锁，确保文件写入安全

class ConfigManager:
    def __init__(self):
        """初始化配置管理器"""
        self.config = self.load_config()  # 加载配置文件
        self.problem_id_counter = self.config.get('problem_id_counter', 0)  # 初始化问题 ID 计数器

    # 加载配置文件
    def load_config(self):
        """从文件加载配置，如果文件不存在则返回默认配置
        返回:
            dict: 配置字典
        """
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {'telegram_users': {}, 'guilds': {}, 'problem_id_counter': 0}  # 默认配置

    # 保存配置文件
    async def save_config(self):
        """异步保存配置到文件"""
        async with config_lock:  # 使用锁避免并发写入冲突
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)  # 保存为格式化的 JSON

    # 获取公会配置
    def get_guild_config(self, guild_id):
        """获取指定服务器的配置
        参数:
            guild_id: 服务器 ID
        返回:
            dict: 服务器配置，若无则返回空字典
        """
        return self.config.get('guilds', {}).get(guild_id, {})

    # 设置公会配置
    async def set_guild_config(self, guild_id, key, value):
        """设置指定服务器的配置项
        参数:
            guild_id: 服务器 ID
            key: 配置键
            value: 配置值
        """
        self.config.setdefault('guilds', {}).setdefault(guild_id, {})[key] = value
        await self.save_config()  # 保存更新后的配置

    # 获取下一个问题 ID
    async def get_next_problem_id(self):
        """生成并返回下一个唯一的问题 ID
        返回:
            int: 新问题 ID
        """
        self.problem_id_counter += 1
        self.config['problem_id_counter'] = self.problem_id_counter
        await self.save_config()
        return self.problem_id_counter