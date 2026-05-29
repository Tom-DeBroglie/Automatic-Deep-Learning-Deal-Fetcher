# 深度学习优惠活动微信推送 Agent（GitHub Actions 版）

这个仓库用于每天自动收集 RSS 中的深度学习 / AI / 大模型优惠活动信息，并通过 PushPlus 推送到微信。

它适合监控：

- 微信公众号：先用 WeWe RSS 转成 RSS。
- B站、知乎、小红书：可以用 RSSHub 或其它 RSS 服务。
- 官方博客 / 官方公告页：只要有 RSS，也可以加入。

## 运行结果是什么？

GitHub Actions 每天自动运行一次：

1. 读取你配置的 RSS 源。
2. 筛选“免费 token / 学生优惠 / 免费额度 / 免费算力 / API 折扣”等内容。
3. 将同一活动的多篇帖子聚类去重。
4. 保留更权威、更有官方线索的一篇。
5. 用 PushPlus 推送到你的微信。
6. 把已发送记录写入 `data/sent_promos.json`，避免重复推送。

## 每天几点运行？

`.github/workflows/daily.yml` 里设置的是：

```yaml
- cron: "10 0 * * *"
```

GitHub Actions 的 cron 使用 UTC 时间，所以大约是北京时间 / 新加坡时间 **每天 08:10**。

同时保留了手动运行入口：

```text
Actions -> Daily Deep Learning Promo Monitor -> Run workflow
```

测试时建议先手动运行。

## 第一步：创建 GitHub 仓库

1. 在 GitHub 新建一个仓库，例如：`dl-promo-agent`。
2. 把本项目所有文件上传进去。
3. 确保 `.github/workflows/daily.yml` 也上传成功。

## 第二步：设置 GitHub Secrets

进入仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

至少添加两个 Secret。

### 1. PUSHPLUS_TOKEN

名称：

```text
PUSHPLUS_TOKEN
```

值：填写你自己的 PushPlus token。

### 2. RSS_URLS

名称：

```text
RSS_URLS
```

值：每行一个 RSS 链接，例如：

```text
http://你的服务器IP:4000/feeds/MP_WXS_xxxxxxxxxxxx.rss
https://rsshub.app/bilibili/user/video/UP主UID
https://rsshub.app/zhihu/people/answers/知乎用户token
```

微信公众号 RSS 需要先通过 WeWe RSS 生成。

## 可选 Secret：KEYWORDS_EXTRA

如果你想额外增加关键词，可以添加：

名称：

```text
KEYWORDS_EXTRA
```

值：每行一个正则关键词，例如：

```text
免费.*大模型
注册送.*额度
学生.*API
```

## 可选 Secret：AUTHORITY_RULES_JSON

如果你想给某些来源更高权威分，可以添加：

名称：

```text
AUTHORITY_RULES_JSON
```

值：JSON 格式，例如：

```json
{
  "机器之心": 10,
  "量子位": 10,
  "Google AI": 12,
  "小米": 11,
  "跟李沐学AI": 10
}
```

## 第三步：手动测试一次

进入：

```text
Actions -> Daily Deep Learning Promo Monitor -> Run workflow
```

`send_empty_report` 选择：

```text
true
```

然后点击绿色按钮运行。

如果配置没问题，你会收到一条微信测试报告。即使当天没有活动，也会发一条“暂无新活动”的空报告。

## 第四步：每天自动运行

手动测试成功后，不用再管。GitHub 会每天自动运行一次。

如果你想改成每周一运行，把 `.github/workflows/daily.yml` 改成：

```yaml
- cron: "10 0 * * 1"
```

这表示每周一 08:10 左右运行。

## 常见报错

### 1. Missing PUSHPLUS_TOKEN

说明你没有在 GitHub Secrets 里添加 `PUSHPLUS_TOKEN`。

### 2. 未配置 RSS_URLS

说明你没有在 GitHub Secrets 里添加 `RSS_URLS`，或者里面没有有效链接。

### 3. PushPlus returned non-success

说明 PushPlus token 错误、失效，或者 PushPlus 服务暂时异常。

### 4. RSS 抓取异常

某个 RSS 源失效、RSSHub 不稳定、WeWe RSS 没启动，都会导致单个源失败。

脚本已经做了容错：单个 RSS 源失败不会导致整个流程崩溃。

## 目录说明

```text
.github/workflows/daily.yml   GitHub Actions 每日运行配置
config/rss_urls.example.txt   RSS 链接填写示例
data/sent_promos.json         已发送记录，自动更新
data/state.json               上次运行时间，自动更新
dl_promo_monitor.py           主程序
requirements.txt              Python 依赖
```
