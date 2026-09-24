# 政府网站链接分类 + 时间提取操作手册

## 你要做什么

gov-monitor 服务采集了一批政府网站链接，还没分类也没有时间。你的任务：

1. 拉一批待分类链接
2. 拉每个链接的正文内容
3. 判断它属于哪一类（notice / news / list / error）
4. notice 和 news 都提取发布时间和成文时间，list 和 error 不需要
5. 回写分类 + 回写时间

## 接口

### 拉待分类

```
GET http://{服务地址}/items/pending-classify?limit=10
```

返回：

```json
{
  "items": [
    {
      "id": 2628,
      "url": "https://www.nx.gov.cn/...",
      "title": "宁夏回族自治区人民政府关于...的批复",
      "site": "宁夏回族自治区人民政府",
      "column_name": "自治区政府文件"
    }
  ]
}
```

### 拉正文内容

```
GET http://{服务地址}/items/{id}/content
```

返回：

```json
{
  "id": 2628,
  "url": "https://www.nx.gov.cn/...",
  "title": "宁夏回族自治区人民政府关于...的批复",
  "content": "宁夏回族自治区人民政府...\n宁政函〔2026〕54号\n..."
}
```

如果页面打不开，返回 502，直接标 `error`。

### 回写分类

```
POST http://{服务地址}/items/{id}/category
Content-Type: application/json

{"category": "notice"}
```

### 回写时间（notice 和 news 需要，list/error 不需要）

```
POST http://{服务地址}/items/{id}/times
Content-Type: application/json

{
  "publish_time": "2026-09-24",
  "document_time": "2026-09-11"
}
```

list 和 error 不需要回写时间。

## 分类标准

打开正文，读标题和内容，判断属于以下哪一类。**只输出一个词。**

### notice（政策文件/通知公告）

正式公文，有发文字号，内容是政策、规定、批复、公告、通知。

- 标题含：通知、意见、办法、规定、公告、决定、方案、条例、细则、批复、函、标准、规范、通告
- 有发文字号：如"宁政函〔2026〕54号""交通运输部公告2026年第69号"
- 正文是公文格式：开头"XX关于XX的请示收悉""现批复如下"，结尾"此复""特此公告"
- 页面带附件下载（PDF/Word）不影响，附件是公文的一部分

例子："关于印发XX办法的通知""XX省人民政府关于XX的批复"

### news（新闻动态/领导活动）

新闻稿，不是政策文件。

- 标题含：召开、出席、调研、会见、活动、动态、走访、检查、慰问、座谈
- 正文是新闻报道："X月X日，XX领导出席XX会议并讲话"
- 没有发文字号

例子："XX厅召开2026年上半年工作会议""XX局长调研XX局工作"

### list（列表页/栏目页）

不是具体文章，是栏目列表、分页、导航页。

- 没有正文内容，只有一堆链接列表
- 页面上全是"更多""下一页""上一页"

### error（打不开/内容空）

- 页面打不开（4xx、5xx、超时）
- 正文内容少于 50 字
- 404、空白页

## 时间提取标准（notice 和 news）

### publish_time（发布时间）

政府网页上"发布时间：""发布日期："旁边的日期，就是这条文章在网上公开的日期。

- 格式：`YYYY-MM-DD`
- 页面写"发布时间：2026-09-24" → `2026-09-24`
- 页面写"2026年9月24日" → `2026-09-24`

### document_time（成文时间/发文日期）

公文本身的成文日期，在正文末尾落款处，或发文字号下面。

- 格式：`YYYY-MM-DD`
- 正文末尾"2026年9月11日" → `2026-09-11`
- 有的文章标题下写"成文日期：2026-09-11" → 用这个
- 找不到就传 null，不要瞎猜

## 处理流程

1. GET `/items/pending-classify?limit=10`
2. 对每条 item：
   - GET `/items/{item.id}/content` 拿正文
   - 返回 502 → category = "error"，不回写时间
   - 拿到正文 → 按分类标准判断 → category = "notice" / "news" / "list"
   - 如果 category = "notice" 或 "news"：
     - 从正文提取 publish_time 和 document_time
     - POST `/items/{item.id}/times` 回写时间
   - POST `/items/{item.id}/category` 回写分类
3. 全部处理完就结束
