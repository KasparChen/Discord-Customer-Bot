import discord

async def get_conversation(channel, limit=50):
    """
    获取指定频道的对话内容。
    
    参数:
        channel (discord.Channel): Discord 频道对象
        limit (int): 最大消息条数，默认为50
    
    返回:
        list: 对话内容列表，包含用户、消息内容和时间戳
    """
    messages = []
    async for msg in channel.history(limit=limit):
        messages.append({
            'user': msg.author.name,
            'content': msg.content,
            'timestamp': msg.created_at.isoformat()
        })
    return messages

def is_ticket_channel(channel, config):
    """
    判断指定频道是否为 Ticket 频道。
    
    参数:
        channel (discord.Channel): Discord 频道对象
        config (dict): 服务器配置
    
    返回:
        bool: 是否为 Ticket 频道
    """
    return channel.category_id in config.get('ticket_category_ids', [])