# Discord-Customer-Bot

A tailored Discord community tool for summarizing user issues, featuring intelligent Ticket validation and refinement, alongside periodic monitoring of General Chat for problems and sentiment.

Powered by xAI, this project is open-sourced under the MIT License. Contributions and feedback from the community are warmly welcomed!

**[中文版 (Chinese Version)](./README.md)**

---

## Overview

Discord-Customer-Bot is a specialized tool designed to streamline user issue management within Discord communities. It excels at validating and refining Ticket-based problems while periodically monitoring General Chat for user concerns and emotional trends. Tailored for small teams unable to maintain a 7/24 Discord presence and Web3 operators facing low-quality inquiries—such as unclear logic, heavy emotional venting, or invalid issues—this bot leverages AI-driven periodic summaries and structured reporting to enhance efficiency and provide a buffer for response planning. The structured data output also empowers teams to analyze problem distributions effectively. Additionally, the `/warp_msg` command significantly boosts collaboration between Moderators and teams by enabling swift manual issue escalation.

Notably, 99% of this project’s codebase was crafted by xAI’s Grok 3 Beta.

---

## Features in Detail

### Discord Features
- **Ticket Management**  
  Automatically detects and analyzes conversations in Discord Ticket channels, generating structured issue reports synced to Telegram.  
  - **Auto-Analysis**: For channels under specified categories (`ticket_category_ids`), the Bot waits 1 hour (3600 seconds) before analyzing the conversation to determine issue validity.  
  - **Manual Trigger**: The `/warp_msg` command instantly analyzes the current Ticket channel, ideal for Moderators needing rapid feedback.  
  - **Parameters**:  
    - `ticket_category_ids`: List of Ticket category IDs (e.g., `[123456789, 987654321]`), set via `/set_ticket_cate`.  
    - **Timestamp Fallback**: Uses channel creation time, falling back to the first message’s time or current time if unavailable.  
  - **Use Case**: Streamlining complex user issues for team task assignment.

- **General Chat Monitoring**  
  Periodically analyzes designated General Chat channels, producing sentiment and event summaries to track community dynamics.  
  - **Monitoring Logic**: Checks all `monitor_channels` every 2 hours (7200 seconds), analyzing messages from the specified period.  
  - **Parameters**:  
    - `monitor_channels`: List of channel IDs to monitor (max 5, e.g., `[111111111, 222222222]`), set via `/set_monitor_channels`.  
    - `monitor_period`: Monitoring period in hours (default 3), set via `/set_monitor_params period_hours <hours>`.  
    - `monitor_max_messages`: Max messages analyzed per cycle (default 100), set via `/set_monitor_params max_messages <count>`.  
  - **Output**: Includes sentiment (positive/negative/neutral), discussion summary, and key events (e.g., product issues).  
  - **Use Case**: Identifying recurring issues or community sentiment shifts.

- **Permission Control**  
  Restricts command usage to authorized roles for secure operation.  
  - **Parameters**:  
    - `allowed_roles`: List of role IDs with command access (e.g., `[333333333, 444444444]`), added via `/set_access`, removed via `/remove_access`.  
  - **Permission Logic**: Administrators have default access; others require a matching role in `allowed_roles`.  
  - **Use Case**: Preventing unauthorized command misuse in structured teams.

- **Timezone Support**  
  Adjusts timestamps in reports to match local timezones.  
  - **Parameters**:  
    - `timezone`: UTC offset (integer, e.g., 8 for UTC+8), set via `/set_timezone offset <offset>`.  
  - **Output Format**: Timestamps as `yyyy-mm-dd HH:MM UTC+x` (e.g., `2025-02-27 14:30 UTC+8`).  
  - **Use Case**: Ensuring time consistency for cross-timezone teams.

- **Command List**  
  - `/set_ticket_cate <category_ids>`: Set Ticket category IDs (comma-separated, e.g., `123456789, 987654321`).  
    - Example: `/set_ticket_cate 123456789, 987654321`  
  - `/check_ticket_cate`: Display current Ticket categories and names.  
  - `/set_tg_channel <tg_channel_id>`: Set Telegram notification channel (e.g., `@MyChannel`).  
    - Example: `/set_tg_channel @MyChannel`  
  - `/check_tg_channel`: Show bound Telegram channel.  
  - `/set_monitor_channels <channels>`: Set monitoring channel IDs (max 5, comma-separated).  
    - Example: `/set_monitor_channels 111111111, 222222222`  
  - `/remove_monitor_channels <channels>`: Remove specified monitoring channels.  
    - Example: `/remove_monitor_channels 111111111`  
  - `/check_monitor_channels`: List current monitoring channels and names.  
  - `/set_monitor_params <period_hours> <max_messages>`: Set monitoring period and max messages.  
    - Example: `/set_monitor_params 4 200` (every 4 hours, up to 200 messages)  
  - `/check_monitor_params`: View current monitoring parameters.  
  - `/set_access <role>`: Grant command access to a role (admin only).  
    - Example: `/set_access @Moderator`  
  - `/remove_access <role>`: Revoke command access from a role (admin only).  
  - `/check_access`: List authorized roles (admin only).  
  - `/warp_msg`: Manually analyze and sync the current Ticket channel.  
  - `/set_timezone <offset>`: Set timezone offset.  
    - Example: `/set_timezone 8`  
  - `/help`: Show all command help.

### Telegram Features
- **Issue Push**  
  Sends Discord Ticket issues to a specified Telegram channel in concise HTML format with jump links.  
  - **Parameters**:  
    - `tg_channel_id`: Telegram channel ID (e.g., `@MyChannel`), set via Discord’s `/set_tg_channel`.  
  - **Output Example**:  
    ~~~
    ----- Issue #1 -----
    Type: Bug Report
    Source: ticket-001
    Time: 2025-02-27 14:30 UTC+8
    Summary: User reports login failure
    Details: User describes login failing with “Error 500”
    🔗 Go to Ticket
    ---------------------
    ~~~
  - **Use Case**: Real-time team notifications for critical issues.

- **Summary Reports**  
  Delivers periodic General Chat summaries with sentiment and event analysis.  
  - **Parameter Dependency**: Relies on Discord’s `monitor_channels` and `monitor_period`.  
  - **Output Example**:
    ~~~
    ===== Chat Summary =====
    Published: 2025-02-27 14:30 UTC+8
    Monitor Period: 4 hours
    Monitored Messages: 200
    Total Messages: 350
    Sentiment: Negative
    Discussion Summary: Lukewarm response to new feature
    Key Events: Multiple mentions of slow loading
    =========================
    ~~~
  - **Use Case**: Periodic insights into community trends and issues.

- **Commands**  
  - `/get_group_id`: Retrieve the current Telegram group/channel ID for binding.  
  - `/current_binding`: List Discord servers bound to the current Telegram channel.  
    - Example Output: `Bound Discord Servers: MyServer (ID: 123456789)`  
  - `/heartbeat_on`: Enable heartbeat log reception, sending Bot status every minute.  
    - Example Log: `Heartbeat: 2025-02-27 14:30 UTC+8 - Bot alive`  
  - `/heartbeat_off`: Disable heartbeat log reception.

---

## Deployment Guide

### Prerequisites
- Python 3.9+
- Discord and Telegram accounts
- LLM API key (defaults to `ark.cn-beijing.volces.com`)

### Obtain Discord Bot Token
1. Visit the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a new application and add a Bot.
3. Enable the following Intents under Bot settings:
   - `Guilds`: For guild-related events.
   - `Guild Messages`: For message events.
   - `Message Content`: To read message content.
4. Copy the Token and add it to `.env`.

### Obtain Telegram Bot Token
1. Message `@BotFather` on Telegram.
2. Use `/newbot` and follow prompts to create a Bot.
3. Copy the Token and add it to `.env`.
4. **Note**: Set command list via `/setcommands` in `@BotFather`, matching the code, e.g.:
   ~~~
   get_group_id - Get current group/channel ID
   current_binding - View bound Discord servers
   heartbeat_on - Enable heartbeat log reception
   heartbeat_off - Disable heartbeat log reception
   ~~~

### Configure `.env` File
Create a `.env` file in the root directory:
~~~
DISCORD_TOKEN=your_discord_bot_token
TELEGRAM_TOKEN=your_telegram_bot_token
MODEL_ID=your_llm_model_id
LLM_API_KEY=your_llm_api_key
~~~

### Install Dependencies
~~~
pip install -r requirements.txt
~~~

### Run the Bot
~~~
python bot.py
~~~

### Verify Operation
- Check `bot.log` and `heartbeat.log` for startup confirmation.
- Use `/help` in Discord to view command assistance.

---

## Project Structure
- `bot.py`: Main entry point, launches Discord and Telegram bots.
- `config_manager.py`: Handles configuration and issue ID generation.
- `llm_analyzer.py`: LLM-based conversation analysis.
- `models.py`: Data model definitions.
- `telegram_bot.py`: Telegram Bot implementation.
- `utils.py`: Utility functions.

---

## Contributing
We welcome contributions! Follow these steps:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit changes (`git commit -m "Add your feature"`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a Pull Request.

---

## License
MIT License © 2025 KasparChen