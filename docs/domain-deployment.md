# 自有域名部署

目标：让聚宽稳定访问你的后端，不再依赖 localtunnel 这种临时地址。

推荐形态：

```text
聚宽策略
  -> https://quant.example.com/api/v1/joinquant/signals
  -> Nginx 443
  -> 127.0.0.1:8000 FastAPI
  -> data/backend/strategies/*.json
```

## 1. 准备服务器和域名

你需要一台有公网 IP 的云服务器。域名 DNS 添加一条记录：

```text
类型: A
主机记录: quant
记录值: 你的服务器公网 IP
```

生效后检查：

```bash
dig +short quant.example.com
```

应返回服务器公网 IP。

## 2. 在服务器运行后端

进入网站目录：

```bash
cd /home/yt/quant/website
```

设置 webhook token：

```bash
export JOINQUANT_WEBHOOK_TOKEN="replace-with-a-long-random-token"
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

生产环境建议用 systemd。示例 `/etc/systemd/system/quant-website.service`：

```ini
[Unit]
Description=Quant Website API
After=network.target

[Service]
WorkingDirectory=/home/yt/quant/website
Environment=JOINQUANT_WEBHOOK_TOKEN=replace-with-a-long-random-token
ExecStart=/usr/bin/python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quant-website
sudo systemctl status quant-website
```

## 3. 配置 Nginx

安装：

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

站点配置 `/etc/nginx/sites-available/quant-website`：

```nginx
server {
    listen 80;
    server_name quant.example.com;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/quant-website /etc/nginx/sites-enabled/quant-website
sudo nginx -t
sudo systemctl reload nginx
```

申请 HTTPS：

```bash
sudo certbot --nginx -d quant.example.com
```

## 4. 聚宽策略替换地址

把补丁文件里的：

```python
WEBHOOK_URL = "https://stupid-masks-prove.loca.lt/api/v1/joinquant/signals"
WEBHOOK_TOKEN = "dev-joinquant-token"
```

替换成：

```python
WEBHOOK_URL = "https://quant.example.com/api/v1/joinquant/signals"
WEBHOOK_TOKEN = "replace-with-a-long-random-token"
```

## 5. 联调检查

从任意外部机器测试：

```bash
curl -X POST https://quant.example.com/api/v1/joinquant/signals \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: replace-with-a-long-random-token" \
  -d '{"strategy_name":"五福闹新春 v4.3","recommendations":[{"symbol":"159915.XSHE","name":"创业板ETF易方达","action":"buy","score":4.8,"suggested_weight_pct":100}],"logs":["domain webhook test"],"events":[{"time":"13:10","label":"域名联调","status":"done"}]}'
```

打开：

```text
https://quant.example.com/etf.html
```

后端文件：

```text
data/backend/strategies/etf.json
data/backend/strategies/joinquant-signals.jsonl
data/backend/strategies/joinquant-full-logs.jsonl
```

## 6. 安全建议

- 只把 `JOINQUANT_WEBHOOK_TOKEN` 放在服务器环境变量或 systemd 环境里。
- 不要把真实 token 写入公开仓库。
- Nginx 必须启用 HTTPS，聚宽侧优先用 `https://`。
- 如果你的页面也公开访问，后续可以给管理页面加登录；webhook 入口至少已有 token 校验。
