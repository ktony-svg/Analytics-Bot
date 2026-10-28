module.exports = {
  apps: [
    {
      name: "analytics-bot",
      script: "bot.py",
      interpreter: "python",
      args: "--daemon",
      autorestart: true,
      watch: false,
      max_memory_restart: "500M",
      env: {
        PYTHONUNBUFFERED: "1",
        SCHEDULE_TIME: "09:00",
        WHATSAPP_DISPATCH_MODE: "console",
      },
    },
  ],
};
