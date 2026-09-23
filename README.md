# gov-monitor

政府网站通知监测工具。基于 [gov-site-list](https://github.com/baiyigali/gov-site-list) 的 URL 清单，定期轮询各栏目页，发现新通知后落 SQLite。

## 安装

```bash
pip install gov-monitor
```

## 使用

### 跑一轮监测

```bash
gov-monitor run
```

会遍历 `gov-site-list` 里所有栏目，抓第一页链接，跟数据库里的已有 URL 做 diff，新的入库。

### 启动 Web 服务

```bash
gov-monitor serve notices.db
```

常驻 HTTP 服务，后台每 5 分钟自动跑一轮采集，暴露 API 供下游（AI 分类、写作）调用。
接口文档见 `http://localhost:8000/docs`。

### 查看统计

```bash
gov-monitor stats
```

### Docker 部署

在服务器上新建一个目录，放两个文件：

**Dockerfile**：

```dockerfile
FROM python:3.14-slim
RUN pip install --no-cache-dir git+https://github.com/baiyigali/gov-monitor.git
WORKDIR /data
EXPOSE 8000
CMD ["gov-monitor", "serve", "/data/notices.db"]
```

**docker-compose.yml**：

```yaml
services:
  gov-monitor:
    build: .
    container_name: gov-monitor
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      GOV_MONITOR_INTERVAL: "300"
```

然后启动：

```bash
mkdir -p data
docker compose up -d --build
```

- 服务监听宿主机 `8000` 端口，API 文档在 `http://服务器IP:8000/docs`
- SQLite 数据库和状态缓存放 `./data/` 目录，容器删了重建数据不丢
- 默认每 5 分钟自动采集一轮，改间隔改 `docker-compose.yml` 里的 `GOV_MONITOR_INTERVAL`

常用命令：

```bash
docker compose logs -f        # 看日志
docker compose restart        # 重启
docker compose down            # 停掉（数据保留在 ./data/）
docker compose up -d --build   # 升级后重新构建
```

## 开发

### 跑测试

```bash
pip install -e . pytest

# API 单元测试（快，不发外网请求，必须全过）
python -m pytest gov_monitor/tests/test_api.py -v

# 全量抓取基线测试（慢，会真实访问 136 个政府站，约 1 分钟）
python -m gov_monitor.tests.test_baseline
```

- `test_api.py`：测所有 HTTP 接口（分类回写、写作计数、stats、404），用临时 DB，不依赖外网。
- `test_baseline.py`：全量抓取回归测试，对比 `baseline.json`，检查有没有站从"能抓"退化。退出码 0=过，1=退化。



## 工作原理

1. 从 `gov-site-list` 加载所有栏目 URL
2. 用 `requests` 抓每个栏目的第一页 HTML
3. 用 BeautifulSoup 提取所有 `<a>` 链接
4. 过滤：同域名、排除导航/附件/分页链接
5. 跟 SQLite 里已有的 URL 对比
6. 新链接入库，字段：`url`（主键）、`title`、`site`、`column`、`first_seen`

## 数据存储

SQLite 文件默认叫 `notices.db`，也可以自己指定路径：

```bash
gov-monitor run /path/to/my.db
```

表结构很简单，就一张 `notices` 表：

| 字段 | 说明 |
|---|---|
| `url` | 通知详情页 URL（主键，去重用） |
| `title` | 通知标题 |
| `site` | 站点名称 |
| `column_name` | 栏目名称 |
| `first_seen` | 我们第一次抓到这条通知的时间 |

## 技术交流

扫码添加微信，交流使用问题、定制与合作：

<p align="center">
  <img src="docs/images/wechat-contact-qr.jpg" alt="微信二维码" width="240" />
</p>

## 项目赞助

本项目由以下微信公众号提供赞助，感谢支持：

**「程序员白大力」** —— 法律科技 / 自动化内容创作

<p align="center">
  <img src="docs/images/wechat-official-account-qr.png" alt="程序员白大力公众号二维码" width="240" />
</p>

**「法啊」** —— 法律科普 / 普法内容

<p align="center">
  <img src="docs/images/fa-official-account-qr.png" alt="法啊公众号二维码" width="240" />
</p>

**「极速法考」** —— 法考备考 / 法律职业资格考试

<p align="center">
  <img src="docs/images/jisu-fakao-official-account-qr.png" alt="极速法考公众号二维码" width="240" />
</p>

## License

MIT
