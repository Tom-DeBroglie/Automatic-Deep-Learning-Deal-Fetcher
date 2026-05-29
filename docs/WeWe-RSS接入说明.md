# WeWe RSS 接入说明

WeWe RSS 的作用是把微信公众号文章转成 RSS。

流程是：

```text
微信公众号文章 -> WeWe RSS -> RSS 链接 -> 本仓库脚本读取
```

## 本地 Docker 部署

新建文件夹：

```powershell
mkdir D:\wewe-rss
cd D:\wewe-rss
```

创建 `docker-compose.yml`：

```yaml
version: '3.9'

services:
  db:
    image: mysql:8.3.0
    command: --mysql-native-password=ON
    environment:
      MYSQL_ROOT_PASSWORD: 123456
      TZ: Asia/Shanghai
      MYSQL_DATABASE: wewe-rss
    volumes:
      - db_data:/var/lib/mysql
    healthcheck:
      test: ['CMD', 'mysqladmin', 'ping', '-h', 'localhost']
      timeout: 45s
      interval: 10s
      retries: 10

  app:
    image: cooderl/wewe-rss:latest
    ports:
      - "4000:4000"
    depends_on:
      db:
        condition: service_healthy
    environment:
      - DATABASE_URL=mysql://root:123456@db:3306/wewe-rss?schema=public&connect_timeout=30&pool_timeout=30&socket_timeout=30
      - AUTH_CODE=123456
      - SERVER_ORIGIN_URL=http://localhost:4000
      - CRON_EXPRESSION=35 5,17 * * *

volumes:
  db_data:
```

启动：

```powershell
docker compose up -d
```

打开：

```text
http://localhost:4000
```

登录码：

```text
123456
```

进入后台后：

1. 账号管理 -> 扫码登录微信读书。
2. 公众号源 -> 添加公众号文章分享链接。
3. 复制生成的 RSS 链接。
4. 把 RSS 链接加入 GitHub Secrets 的 `RSS_URLS`。

## 服务器部署

如果部署在服务器上，把：

```yaml
SERVER_ORIGIN_URL=http://localhost:4000
```

改成：

```yaml
SERVER_ORIGIN_URL=http://你的服务器IP:4000
```

然后 `RSS_URLS` 里也填写服务器地址生成的 RSS 链接。
