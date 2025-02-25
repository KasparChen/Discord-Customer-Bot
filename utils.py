import discord

# 获取频道对话
async def get_conversation(channel, limit=50):
    """获取指定频道的最近对话
    参数:
        channel: Discord 频道对象
        limit: 获取的消息数量上限，默认 50
    返回:
        list: 对话列表，每个元素包含 user, content, timestamp
    """
    messages = []
    async for msg in channel.history(limit=limit):  # 异步遍历消息历史
        messages.append({
            'user': msg.author.name,  # 用户名
            'content': msg.content,  # 消息内容
            'timestamp': msg.created_at.isoformat()  # 时间戳
        })
    return messages

# 判断是否为 Ticket 频道
def is_ticket_channel(channel, config):
    """判断给定频道是否为 Ticket 频道
    参数:
        channel: Discord 频道对象
        config: 服务器配置
    返回:
        bool: 是否为 Ticket 频道
    """
    return channel.category_id in config.get('ticket_category_ids', [])  # 检查频道的类别 ID