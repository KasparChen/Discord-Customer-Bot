import discord

# 获取频道最近 50 条消息的对话内容
async def get_conversation(channel):
    messages = []
    async for msg in channel.history(limit=50):  # 获取最近 50 条消息
        messages.append({
            'user': msg.author.name,      # 用户名
            'content': msg.content,       # 消息内容
            'timestamp': msg.created_at.isoformat()  # 时间戳
        })
    return messages

# 判断是否为 Ticket 频道
def is_ticket_channel(channel, config):
    return channel.category_id in config.get('ticket_category_ids', [])  # 检查频道类别 ID