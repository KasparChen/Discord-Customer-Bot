import discord
import datetime

async def get_conversation(channel):
    # 获取频道中的最近 50 条消息
    messages = []
    async for msg in channel.history(limit=50):
        messages.append({
            'user': msg.author.name,
            'content': msg.content,
            'timestamp': msg.created_at.isoformat()
        })
    return messages

def is_ticket_channel(channel, config):
    # 判断一个频道是否属于 Ticket 类别
    return channel.category_id in config.get('ticket_category_ids', [])