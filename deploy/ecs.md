# ECS 部署说明

ECS + Docker + Nginx + 阿里云 RDS MySQL 是本项目推荐的正式部署方式。Render 暂时作为 optional deployment 或 1-3 天回滚备份保留；`render.yaml` 只会被 Render 平台读取，不影响 ECS、Docker Compose 或本地服务器部署。

## 推荐架构

```text
浏览器
  -> ECS 上的 Nginx: 80 / 443
  -> ECS 上的 Docker 容器: 127.0.0.1:8000
  -> 阿里云 RDS MySQL 内网地址: 3306
```

根目录 `Dockerfile` 会构建前端，并由 FastAPI 在同一个容器中托管静态页面。因此正式 ECS 部署只需要一个应用容器，Nginx 负责公网域名、HTTPS、上传大小限制和反向代理。

## 1. 准备 ECS

1. ECS 与 RDS 建议放在同一地域、同一 VPC。
2. 在 ECS 上安装 Docker 和 Nginx。
3. ECS 安全组公网只开放 `80` 和 `443`。
4. 应用端口不要暴露到公网，Docker 只绑定 `127.0.0.1:8000`。
5. 创建运行时目录：

```bash
sudo mkdir -p /srv/novel-deconstructor/{storage,uploads,outputs}
sudo chown -R $USER:$USER /srv/novel-deconstructor
```

## 2. 配置 RDS

1. 创建 MySQL 数据库，例如 `novel_deconstructor_prod`。
2. 创建专用数据库用户，只授予该库所需权限。
3. ECS 与 RDS 在同一 VPC 时，优先使用 RDS 内网地址。
4. RDS 白名单或安全组只放行 ECS 私网 IP，或放行 ECS 所在安全组。
5. 除非网络拓扑确实要求，不建议使用 RDS 公网地址。

数据库连接串格式：

```env
APP_DATABASE_URL=mysql+pymysql://<user>:<url_encoded_password>@<rds-internal-host>:3306/<database>?charset=utf8mb4
```

如果密码里包含 `@`、`#`、`:`、`/`、`?`、`&` 或空格，需要先做 URL 编码。

## 3. 创建 ECS 环境变量文件

在 ECS 上创建 `/srv/novel-deconstructor/.env`。这个文件只放在服务器，不要提交到仓库。

```env
APP_DATABASE_URL=mysql+pymysql://<user>:<url_encoded_password>@<rds-internal-host>:3306/<database>?charset=utf8mb4
APP_STORAGE_DIR=/app/backend/storage
APP_UPLOAD_DIR=/app/backend/uploads
APP_OUTPUT_DIR=/app/backend/outputs
APP_KNOWLEDGE_DIR=/app/backend/storage/knowledge
APP_REQUIRE_AUTH=true
APP_AUTH_SESSION_DAYS=30

MAX_UPLOAD_SIZE_MB=20
MAX_CHAPTER_CHARS=12000
CHUNK_OVERLAP_CHARS=800
KNOWLEDGE_CHUNK_SIZE=900
KNOWLEDGE_CHUNK_OVERLAP=120
RETRIEVAL_TOP_K=6
DEFAULT_CONCURRENCY=1
ALLOW_ABSOLUTE_OUTPUT_PATH=false
ENABLE_DIRECTORY_PICKER=false

CORS_ORIGINS=https://your-domain.example

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=
OPENAI_TEMPERATURE=0.3
OPENAI_MAX_TOKENS=8192

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro

DOUBAO_API_KEY=
ARK_API_KEY=
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=doubao-seed-2-0-pro-260215
```

同域名 Nginx 反代时，浏览器通常访问同源地址，CORS 不会成为主要问题。仍建议把 `CORS_ORIGINS` 写成正式域名，方便后续前后端分离或排查。

## 4. 构建并运行容器

在 ECS 的仓库根目录执行：

```bash
docker build -t novel-deconstructor:latest .
docker rm -f novel-deconstructor
docker run -d \
  --name novel-deconstructor \
  --restart unless-stopped \
  --env-file /srv/novel-deconstructor/.env \
  -p 127.0.0.1:8000:8000 \
  -v /srv/novel-deconstructor/storage:/app/backend/storage \
  -v /srv/novel-deconstructor/uploads:/app/backend/uploads \
  -v /srv/novel-deconstructor/outputs:/app/backend/outputs \
  novel-deconstructor:latest
```

检查健康接口：

```bash
curl http://127.0.0.1:8000/health
```

期望返回：

```json
{"ok":true,"service":"novel-deconstructor"}
```

## 5. 配置 Nginx 反向代理

示例 `/etc/nginx/conf.d/novel-deconstructor.conf`：

```nginx
server {
    listen 80;
    server_name your-domain.example;

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

重载 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

如果后续添加 HTTPS，Nginx 仍然反代到 `http://127.0.0.1:8000` 即可。

## 6. 安全组建议

ECS 安全组：

- 入方向 `80/tcp` 放行公网访问。
- 入方向 `443/tcp` 放行公网访问。
- SSH 只放行自己的固定 IP。
- 不要公网开放 `8000/tcp`。

RDS 安全组或白名单：

- MySQL `3306/tcp` 只放行 ECS 私网 IP 或 ECS 安全组。
- 优先使用 RDS 内网地址。
- 不要把 RDS 放开到 `0.0.0.0/0`。

## 7. 本地服务器说明

本地或局域网部署可以继续使用 Docker Compose：

```bash
copy .env.example .env
docker compose up --build
```

本地 Compose 会分别启动前端和后端两个容器。ECS 正式部署建议使用根目录 `Dockerfile` 的单容器构建，再放到 Nginx 后面，这样更适合小型云服务器运维，也减少跨域配置。

## 8. Render 回滚窗口

保留 `render.yaml`。ECS 切换期间，Render 可以继续运行 1-3 天作为回滚备份。确认 ECS 稳定后，暂停或删除 Render 服务，避免重复公开部署和额外费用。
