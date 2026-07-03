# 校园事件报警系统

一个本地可运行的校园事件上报与管理员确认系统。用户可以提交事件类型、描述、时间、地点等信息，系统会保存到 SQLite 数据库，并通过 DeepSeek 适配器进行事件分类、紧急度评估与处理建议生成。

当前版本在没有 DeepSeek API Key 时会自动使用本地规则评估，方便先完成开发和测试。拿到 API 模板和 Key 后，只需要补全 `.env` 并按模板调整 `campus_alerts/deepseek.py` 中的请求结构。

## 功能

- 用户事件上报：类型、描述、时间、地点、上报人、联系方式
- SQLite 持久化存储
- DeepSeek 分类/紧急度评估/处理建议适配器
- 管理员事件列表
- 按紧急度、类型、时间、状态排序
- 管理员确认事件

## 快速开始

```powershell
python server.py
```

打开：

- 用户上报页：http://127.0.0.1:8000/
- 管理员页：http://127.0.0.1:8000/admin

## DeepSeek 配置

复制 `.env.example` 为 `.env`，填写：

```env
DEEPSEEK_API_KEY=你的 API Key
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING_TYPE=enabled
DEEPSEEK_REASONING_EFFORT=high
```

未配置 Key 时，系统会继续使用本地规则评估，不会阻塞事件上报。

## 测试

```powershell
python -m unittest discover -s tests
```

## API

- `POST /api/events`：创建事件
- `GET /api/events?sort=urgency|type|time|status`：获取事件列表
- `POST /api/events/{id}/confirm`：确认事件
- `GET /api/health`：健康检查
