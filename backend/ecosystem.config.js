module.exports = {
  apps: [
    {
      name: "chatbot-customize-dashboard-backend",
      script: "/www/wwwroot/chatbot-customize-dashboard/backend/env/bin/uvicorn",
      args: "main:app --host 127.0.0.1 --port 8016",
      cwd: "/www/wwwroot/chatbot-customize-dashboard/backend",
      interpreter: "none",
      watch: false,
      exec_mode: "fork",
      max_memory_restart: "512M"
    }
  ]
}