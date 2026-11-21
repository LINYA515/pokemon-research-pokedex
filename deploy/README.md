# 通用 Linux 轻量部署

这些模板用于单台 Ubuntu/Debian 服务器：Nginx 提供静态前端，将同源 `/api/` 转发到只监听 `127.0.0.1:8765` 的 FastAPI。使用单进程 CPU 运行图鉴、证据问答、队伍分析和遗传算法；不运行图像生成或付费语言模型。`example.com` 是保留的示例域名，必须替换为管理员自己的域名。

本目录没有任何在线实例的地址、凭据或证书。这里的 `pokemon-web` 是部署时新建的无登录系统账户，不是服务器登录用户名。

## 1. 准备可公开的运行文件

需要 Python 3.12、Python venv、Node.js 20.19+ 或 22.12+、npm、Nginx。先安装这些工具，在仓库根目录使用普通用户构建：

```bash
python3 -m venv .venv-cloud
.venv-cloud/bin/python -m pip install -r deploy/requirements-cloud.txt
.venv-cloud/bin/python scripts/build_data.py
cd frontend
npm ci
npm run build
cd ..
```

数据脚本从固定上游版本构建 `data/pokedex.sqlite` 和 `data/manifest.json`，首次构建需要联网。部署依赖固定在 `requirements-cloud.txt`，没有 GPU 或语义模型依赖；网页继续使用结构化证据和 TF-IDF。图片首次访问按需下载，缓存后可复用。

## 2. 安装到独立发布目录

仍在仓库根目录执行。只复制下列白名单内容；不要复制本机配置、私钥、模型、问答日志或生成历史。

```bash
set -euo pipefail
id pokemon-web >/dev/null 2>&1 || sudo useradd --system --home-dir /var/lib/pokemon-web --create-home --shell /usr/sbin/nologin pokemon-web

release="$(date -u +%Y%m%d-%H%M%S)"
release_dir="/opt/pokemon-web/releases/$release"
sudo test ! -e "$release_dir"
sudo install -d -m 755 "$release_dir/backend" "$release_dir/frontend/dist" "$release_dir/data" /var/lib/pokemon-web/artwork
sudo cp backend/*.py "$release_dir/backend/"
sudo cp -R frontend/dist/. "$release_dir/frontend/dist/"
sudo cp data/pokedex.sqlite data/manifest.json "$release_dir/data/"
sudo chmod -R a+rX "$release_dir"
sudo chown -R pokemon-web:pokemon-web /var/lib/pokemon-web
sudo ln -s /var/lib/pokemon-web/artwork "$release_dir/data/artwork"

sudo python3 -m venv /opt/pokemon-web/venv
sudo /opt/pokemon-web/venv/bin/python -m pip install -r deploy/requirements-cloud.txt
sudo ln -sfn "$release_dir" /opt/pokemon-web/current
sudo install -m 644 deploy/pokemon-web.service /etc/systemd/system/pokemon-web.service
```

应用代码和 SQLite 由管理员持有，服务账户只有读取权限。systemd 进一步将系统目录设为只读，仅允许写入 `/var/lib/pokemon-web`。服务配置清空模型环境变量；白名单安装也避免本机配置覆盖这些设置。

## 3. 配置 Nginx 和自启动

```bash
sudo install -d /etc/nginx/snippets /etc/nginx/sites-available /etc/nginx/sites-enabled /var/www/pokemon-acme/.well-known/acme-challenge
sudo install -m 644 deploy/pokemon-proxy.conf /etc/nginx/snippets/pokemon-proxy.conf
sudo install -m 644 deploy/pokemon-limits.conf /etc/nginx/conf.d/pokemon-limits.conf
sudo install -m 644 deploy/pokemon-site.conf /etc/nginx/sites-available/pokemon-web
sudoedit /etc/nginx/sites-available/pokemon-web
```

在编辑器中将 `server_name example.com;` 改成自己的域名。确认域名解析到目标服务器，再启用站点；已有站点时先检查端口和主机名冲突，保留其配置。

```bash
sudo ln -sfn /etc/nginx/sites-available/pokemon-web /etc/nginx/sites-enabled/pokemon-web
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now pokemon-web nginx
sudo systemctl restart pokemon-web
sudo systemctl reload nginx
sudo systemctl is-active pokemon-web nginx
```

在操作系统防火墙与云服务商防火墙中按需允许 TCP 80、443；不要开放后端 8765。现有 SSH 规则无需因此更改。systemd 的内存和 CPU 限额适合小型演示，可按实际负载调整；它不提供高可用或无限并发保证。

## 4. 启用 HTTPS

HTTP 模板用于初始验证和 HTTP-01 证书挑战。正式对外提供服务前，用所选证书服务为自己的域名签发证书，再为该站点配置 HTTPS。不要将示例域名用于申请。

签发后，将当前站点的主要路由放入 HTTPS `server` 块，配置真实的证书文件位置，例如：

```nginx
listen 443 ssl;
listen [::]:443 ssl;
ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
```

这里的 `example.com` 也须替换。保留 80 端口的 `/.well-known/acme-challenge/` 路由，其余 HTTP 请求重定向到自己的 HTTPS 域名。使用证书工具的自动续签机制，并在成功续签后执行 `nginx -t` 和 `systemctl reload nginx`。先完成续签演练，再确认定时器正常运行。证书与账户私钥应留在服务器，不能提交到仓库。

## 5. 验证运行范围

以下请求中的 Host 也须替换为上面配置的域名；它们用于在服务器内验证站点路由：

```bash
curl -fsS -H 'Host: example.com' http://127.0.0.1/api/status
curl -fsS -H 'Host: example.com' -H 'Content-Type: application/json' --data '{"seed":42}' http://127.0.0.1/api/team/optimize
curl -fsS -H 'Host: example.com' http://127.0.0.1/api/generations/status
sudo journalctl -u pokemon-web -n 50 --no-pager
```

还要从另一台电脑打开自己的 HTTPS 地址，检查图鉴图片、问答、组队预览、应用和刷新保存；服务器内部成功不等于公网可访问。浏览器默认执行证书验证，不要通过忽略证书错误来认定验收成功。

- 图像生成状态明确为未启用，历史为空，创建请求返回 403，私有生成图片路由返回 404；提示词预览仍可用。
- API 和图片使用不同限流额度；组队请求另有限流和并发上限，忙时返回 429，可稍后重试。
- 队伍、收藏保存在访问者的浏览器中，不跨设备同步；本部署没有公共用户数据库。
- 数据、图片和模型的权利归属见仓库根目录的第三方声明。

## 更新和回退

更新时重新构建，创建新的发布目录，并按步骤 2 的白名单复制文件。记录 `readlink -f /opt/pokemon-web/current` 返回的旧目录后切换 `current`，重启并完成检查。保留旧目录直到新版本验证成功；本模板没有自动删除旧版本的步骤。

若更改 Python 依赖，先用独立虚拟环境验证，不要假设旧版本能配合新依赖运行。需要回退时，在确认旧目录存在后，将 `current` 指回该目录并重启 `pokemon-web`。Nginx 配置或证书另有修改时，也需单独保留和核对其旧配置。
