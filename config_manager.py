import asyncio
import json
import os
from cryptography.fernet import Fernet  # 用于对称加密和解密 API key

# 配置文件路径常量
CONFIG_FILE = 'config.json'
# 异步锁，用于确保并发写入配置文件时的线程安全
config_lock = asyncio.Lock()

class ConfigManager:
    def __init__(self):
        """
        初始化配置管理器，加载配置并设置加密密钥。
        - 如果配置文件不存在，则创建默认配置。
        - 生成或加载用于加密 API key 的密钥，但不立即保存（留给调用者处理）。
        """
        self.config = self.load_config()  # 同步加载配置
        self.problem_id_counter = self.config.get('problem_id_counter', 0)
        # 获取或生成加密密钥
        self.encryption_key = self.config.get('encryption_key')
        if not self.encryption_key:
            # 生成新密钥，但不异步保存
            self.encryption_key = Fernet.generate_key().decode()
            self.config['encryption_key'] = self.encryption_key
            # 注意：这里不再调用 save_config，留给外部异步上下文处理
        self.cipher = Fernet(self.encryption_key.encode())

    def load_config(self):
        """从文件加载配置，若不存在则返回默认配置"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {
            'telegram_users': {},
            'guilds': {},
            'problem_id_counter': 0,
            'is_activated': False
        }

    async def save_config(self):
        """异步保存配置到文件，使用锁防止并发写入冲突"""
        async with config_lock:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)

    def get_guild_config(self, guild_id):
        """
        获取指定 Discord 服务器的配置。
        
        Args:
            guild_id (str): Discord 服务器的 ID
        
        Returns:
            dict: 该服务器的配置字典，若无则返回空字典
        """
        return self.config.get('guilds', {}).get(guild_id, {})  # 从 guilds 中获取指定 guild_id 的配置

    async def set_guild_config(self, guild_id, key, value):
        """
        设置指定服务器的配置项并保存。
        
        Args:
            guild_id (str): Discord 服务器 ID
            key (str): 配置键（如 'timezone', 'llm_config'）
            value: 配置值（类型根据 key 不同而异）
        
        Raises:
            ValueError: 如果 key 为 'timezone' 且 value 不是整数
        """
        if key == 'timezone' and not isinstance(value, int):
            raise ValueError("时区偏移量必须为整数")  # 验证时区值合法性
        # 确保 guilds 和 guild_id 的字典存在，然后设置 key-value
        self.config.setdefault('guilds', {}).setdefault(guild_id, {})[key] = value
        await self.save_config()  # 保存更新后的配置

    async def get_next_problem_id(self):
        """
        生成并返回下一个唯一的问题 ID，同时更新配置文件。
        
        Returns:
            int: 新生成的问题 ID
        """
        self.problem_id_counter += 1  # 自增计数器
        self.config['problem_id_counter'] = self.problem_id_counter  # 更新配置中的计数器
        await self.save_config()  # 保存更新
        return self.problem_id_counter

    def is_bot_activated(self):
        """
        检查 Bot 是否已通过密钥或 LLM 配置激活。
        
        Returns:
            bool: True 表示已激活，False 表示未激活
        """
        return self.config.get('is_activated', False)  # 获取激活状态，默认 False

    async def activate_with_key(self, key, master_key):
        """
        使用密钥激活 Bot，只有在未激活且密钥正确时生效。
        
        Args:
            key (str): 用户提供的激活密钥
            master_key (str): 系统预设的固定密钥（从环境变量加载）
        
        Returns:
            bool: True 表示激活成功，False 表示失败（密钥错误或已激活）
        """
        if key == master_key and not self.is_bot_activated():
            self.config['is_activated'] = True  # 设置激活状态
            await self.save_config()  # 保存配置
            return True
        return False

    async def activate_with_llm_config(self, guild_id, api_key, model_id, base_url):
        """
        使用自定义 LLM 配置激活 Bot，并将配置绑定到指定服务器。
        - API key 会被加密存储。
        - 如果 Bot 未激活，则激活它。
        
        Args:
            guild_id (str): Discord 服务器 ID
            api_key (str): 用户提供的 LLM API key
            model_id (str): LLM 模型 ID
            base_url (str): LLM API 的基础 URL
        """
        # 加密 API key，确保敏感信息安全
        encrypted_api_key = self.cipher.encrypt(api_key.encode()).decode()
        # 获取或创建服务器配置
        guild_config = self.config.setdefault('guilds', {}).setdefault(guild_id, {})
        # 存储 LLM 配置，包括加密后的 API key
        guild_config['llm_config'] = {
            'api_key': encrypted_api_key,  # 加密存储
            'model_id': model_id,
            'base_url': base_url
        }
        # 如果 Bot 未激活，则激活它
        if not self.config.get('is_activated', False):
            self.config['is_activated'] = True
        await self.save_config()  # 保存更新后的配置

    def get_llm_config(self, guild_id):
        """
        获取 LLM 配置，优先返回服务器绑定的自定义配置，若无则返回 None。
        
        Args:
            guild_id (str): Discord 服务器 ID
        
        Returns:
            dict or None: 包含 api_key（解密后）、model_id 和 base_url 的字典，若无自定义配置则返回 None
        """
        guild_config = self.get_guild_config(guild_id)
        llm_config = guild_config.get('llm_config')
        if llm_config:
            # 解密 API key 并返回完整配置
            decrypted_api_key = self.cipher.decrypt(llm_config['api_key'].encode()).decode()
            return {
                'api_key': decrypted_api_key,
                'model_id': llm_config['model_id'],
                'base_url': llm_config['base_url']
            }
        return None  # 无自定义配置时返回 None
    
    # 新增方法：获取 warp_msg 允许的角色
    def get_warp_msg_allowed_roles(self, guild_id):
        """
        获取指定服务器允许使用 warp_msg 的角色 ID 列表
        
        Args:
            guild_id (str): Discord 服务器 ID
        
        Returns:
            list: 允许的角色 ID 列表，若无则返回空列表
        """
        return self.get_guild_config(guild_id).get('warp_msg_allowed_roles', [])