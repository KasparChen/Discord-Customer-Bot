# Discord-Customer-Bot

一个专为 Discord 社区设计的用户问题总结工具，通过智能分析 Ticket 和 General Chat 对话，助力小团队高效管理用户需求。

本项目由 xAI 提供支持，代码遵循 MIT 许可证开源，欢迎社区贡献与反馈！

**[English Version (英文版)](./README-EN.md)**

---

## 项目简介

Discord-Customer-Bot 是一个针对 Discord 社区内用户问题的高效总结工具，专注于 Ticket 问题的有效性判断、精炼提炼与专属归类，以及 General Chat 中用户问题和情绪的定时监控。对于无法 7/24 小时驻守 Discord 的小团队，以及在社区运营中常面对低质量发问（逻辑混乱、情绪化严重、无效问题）的场景，本工具通过 AI 驱动的定时总结与结构化转述，显著提升问题处理效率并优化团队协作。不仅为团队提供缓冲空间，其结构化的数据也能给团队更好的空间进行问题分布的分析。

此外，`/warp_msg` 命令的加入大幅提升了 Moderators 与团队间的协作效率，让关键问题得以快速响应。

本项目 99% 的代码由 xAI 的 Grok 3 Beta 完成。

---

### 核心功能
- **Ticket 分析与同步**: 自动检测 Discord Ticket 频道中的问题，生成详细反馈并推送到 Telegram。
- **General Chat 监控**: 定期分析指定 General Chat 频道的对话，生成情绪分析和事件总结。
- **灵活配置**: 支持时区调整、权限管理、监控参数设置等多种自定义选项。
- **双平台命令**: 提供 Discord 斜杠命令和 Telegram 命令，操作直观便捷。
- **心跳日志**: 实时记录 Bot 运行状态，确保稳定性。

---

## 功能详解

### Discord 功能
- **Ticket 管理**  
  自动检测并分析 Discord 中的 Ticket 频道对话，生成结构化的问题报告并推送至 Telegram。  
  - **自动分析**: 在指定类别（`ticket_category_ids`）下的频道被识别为 Ticket 频道后，Bot 会等待 1 小时（3600 秒），然后分析对话内容，判断是否构成有效问题。  
  - **手动触发**: 使用 `/warp_msg` 命令可立即分析当前 Ticket 频道，适合 Moderator 需要快速反馈的情况。  
  - **参数说明**:  
    - `ticket_category_ids`: Ticket 类别的 ID 列表（如 `[123456789, 987654321]`），通过 `/set_ticket_cate` 设置。  
    - **时间戳逻辑**: 如果频道创建时间不可用，Bot 会尝试使用第一条消息的时间，或当前时间作为兜底。  
  - **使用场景**: 用户提交复杂问题，团队需快速整理并分配任务。

- **General Chat 监控**  
  定期分析指定 General Chat 频道的对话，生成情绪分析和事件总结，适用于跟踪社区动态。  
  - **监控逻辑**: 每 2 小时（7200 秒）检查一次所有配置的 `monitor_channels`，分析指定周期内的消息。  
  - **参数说明**:  
    - `monitor_channels`: 监控频道 ID 列表（最多 5 个，如 `[111111111, 222222222]`），通过 `/set_monitor_channels` 设置。  
    - `monitor_period`: 监控周期（小时，默认 3），通过 `/set_monitor_params period_hours <小时数>` 设置。  
    - `monitor_max_messages`: 每次分析的最大消息数（默认 100），通过 `/set_monitor_params max_messages <数量>` 设置。  
  - **输出**: 包括情绪（积极/消极/中立）、讨论概述和关键事件（如产品问题）。  
  - **使用场景**: 捕获社区中潜在的不满情绪或重复问题，提升运营效率。

- **权限控制**  
  限制命令的使用权限，确保只有授权角色可以操作。  
  - **参数说明**:  
    - `allowed_roles`: 允许使用命令的角色 ID 列表（如 `[333333333, 444444444]`），通过 `/set_access` 添加，`/remove_access` 删除。  
  - **权限检查**: 管理员默认有权限，普通用户需匹配 `allowed_roles` 中的角色。  
  - **使用场景**: 防止非授权用户误操作，适合团队分工明确的环境。

- **时区支持**  
  调整问题报告中的时间戳以匹配本地时区。  
  - **参数说明**:  
    - `timezone`: UTC 偏移量（整数，如 8 表示 UTC+8），通过 `/set_timezone offset <偏移量>` 设置。  
  - **输出格式**: 时间戳显示为 `yyyy-mm-dd HH:MM UTC+x`（如 `2025-02-27 14:30 UTC+8`）。  
  - **使用场景**: 跨时区团队协作，确保时间一致性。

- **命令列表**  
  - `/set_ticket_cate <category_ids>`: 设置 Ticket 类别 ID，用逗号分隔（如 `123456789, 987654321`）。  
    - 示例: `/set_ticket_cate 123456789, 987654321`  
  - `/check_ticket_cate`: 查看当前设置的 Ticket 类别及其名称。  
  - `/set_tg_channel <tg_channel_id>`: 设置 Telegram 推送频道（如 `@MyChannel`）。  
    - 示例: `/set_tg_channel @MyChannel`  
  - `/check_tg_channel`: 查看当前绑定的 Telegram 频道。  
  - `/set_monitor_channels <channels>`: 设置监控频道 ID（最多 5 个，用逗号分隔）。  
    - 示例: `/set_monitor_channels 111111111, 222222222`  
  - `/remove_monitor_channels <channels>`: 移除指定监控频道。  
    - 示例: `/remove_monitor_channels 111111111`  
  - `/check_monitor_channels`: 查看当前监控频道及其名称。  
  - `/set_monitor_params <period_hours> <max_messages>`: 设置监控周期和最大消息数。  
    - 示例: `/set_monitor_params 4 200`（每 4 小时分析最多 200 条消息）  
  - `/check_monitor_params`: 查看当前监控参数。  
  - `/set_access <role>`: 为指定角色授予命令权限（需管理员权限）。  
    - 示例: `/set_access @Moderator`  
  - `/remove_access <role>`: 移除角色的命令权限（需管理员权限）。  
  - `/check_access`: 查看授权角色列表（需管理员权限）。  
  - `/warp_msg`: 手动分析当前 Ticket 频道并推送结果。  
  - `/set_timezone <offset>`: 设置时区偏移。  
    - 示例: `/set_timezone 8`  
  - `/help`: 显示所有命令帮助。

### Telegram 功能
- **问题推送**  
  将 Discord Ticket 问题以 HTML 格式发送至指定 Telegram 频道，格式简洁且包含跳转链接。  
  - **参数说明**:  
    - `tg_channel_id`: Telegram 频道 ID（如 `@MyChannel`），获取后可通过 Discord 的 `/set_tg_channel` 设置为推送目标。  
  - **输出示例**:  
    ~~~
    ----- Issue #1 -----
    类型: Bug 报告
    来源: 001-username
    时间: 2025-02-27 14:30 UTC+8
    简述: 用户报告登录失败
    详情: 用户描述无法登录，提示“错误 500”
    🔗 跳转至 Ticket
    ---------------------
    ~~~
  - **使用场景**: 团队实时接收关键问题通知。

- **总结报告**  
  推送 General Chat 的周期性总结，包含情绪和事件分析。  
  - **参数依赖**: 基于 Discord 的 `monitor_channels` 和 `monitor_period`。  
  - **输出示例**:
    ~~~
    ===== Chat Summary =====
    发布时间: 2025-02-27 14:30 UTC+8
    监控周期: 4 小时
    监控消息数: 200
    周期内消息数: 350
    情绪: 消极
    讨论概述: 用户对新功能反应冷淡
    重点关注事件: 多人提及加载缓慢
    =========================
    ~~~
    - **使用场景**: 定期了解社区情绪和问题趋势。

- **命令支持**  
  - `/get_group_id`: 获取当前 Telegram 群组或频道 ID，用于绑定。  
  - `/current_binding`: 查看与当前 Telegram 频道绑定的 Discord 服务器。  
    - 示例输出: `当前绑定的 Discord 服务器: MyServer (ID: 123456789)`  
  - `/heartbeat_on`: 开启心跳日志接收，每分钟推送 Bot 运行状态。  
    - 示例日志: `心跳日志: 2025-02-27 14:30 UTC+8 - Bot alive`  
  - `/heartbeat_off`: 关闭心跳日志接收。

---

## 部署流程

### 前置条件
- Python 3.9+
- Discord 和 Telegram 账号
- LLM API 密钥（本项目默认使用 `ark.cn-beijing.volces.com`）

### 获取 Discord Bot Token
1. 登录 [Discord 开发者门户](https://discord.com/developers/applications)。
2. 创建新应用，添加 Bot。
3. 在 Bot 页面启用以下权限（Intents）：
   - `Guilds`: 服务器相关事件。
   - `Guild Messages`: 服务器消息事件。
   - `Message Content`: 消息内容监听。
4. 生成并复制 Token，保存至 `.env` 文件。

### 获取 Telegram Bot Token
1. 在 Telegram 中联系 `@BotFather`。
2. 输入 `/newbot`，按提示创建 Bot。
3. 获取 Token，保存至 `.env` 文件。
4. **注意**: 在 `@BotFather` 中通过 `/setcommands` 设置命令列表，确保与代码匹配，例如：
   ~~~
   get_group_id - 获取当前群组或频道 ID
   current_binding - 查看绑定的 Discord 服务器
   heartbeat_on - 开启心跳日志接收
   heartbeat_off - 关闭心跳日志接收
   ~~~

### 配置 `.env` 文件
在项目根目录创建 `.env` 文件，格式如下：
~~~
DISCORD_TOKEN=your_discord_bot_token
TELEGRAM_TOKEN=your_telegram_bot_token
MODEL_ID=your_llm_model_id
LLM_API_KEY=your_llm_api_key
~~~

### 安装依赖
~~~
pip install -r requirements.txt
~~~

### 启动 Bot
~~~
python bot.py
~~~

### 验证运行
- 检查 `bot.log` 和 `heartbeat.log`，确认 Bot 已启动。
- 在 Discord 使用 `/help` 查看命令帮助。

---

## 项目结构
- `bot.py`: 主程序，启动 Discord 和 Telegram Bot。
- `config_manager.py`: 管理配置和问题 ID。
- `llm_analyzer.py`: LLM 对话分析逻辑。
- `models.py`: 数据模型定义。
- `telegram_bot.py`: Telegram Bot 实现。
- `utils.py`: 通用工具函数。

---

## 贡献
欢迎提交 Issue 或 PR！请遵循以下步骤：
1. Fork 本仓库。
2. 创建特性分支（`git checkout -b feature/your-feature`）。
3. 提交更改（`git commit -m "Add your feature"`）。
4. 推送到分支（`git push origin feature/your-feature`）。
5. 创建 Pull Request。

---

## 许可证
MIT License © 2025 KasparChen