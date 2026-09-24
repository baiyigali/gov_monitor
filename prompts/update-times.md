# 政府文章时间提取回写操作手册

（notice 和 news 都需要提取时间，list 和 error 跳过）

## 你要做什么

gov-monitor 服务里已经有一批已分类为 notice 的链接，但缺发布时间和成文时间。你的任务：

1. 拉一批已分类的 notice 或 news
2. 拉每个链接的正文内容
3. 从正文里提取发布时间和成文时间
4. 回写时间

## 接口

### 拉待提取时间的链接

```
GET http://{服务地址}/v2/items/pending-write?limit=10&published_after=2020-01-01
```

用 v2 接口，`published_after` 不传则拉全部已分类 notice。也可以用 `max_count=0` 只拉还没写过的。

返回：

```json
{
  "items": [
    {
      "id": 2628,
      "url": "https://www.nx.gov.cn/...",
      "title": "宁夏回族自治区人民政府关于...的批复",
      "publish_time": null,
      "document_time": null
    }
  ]
}
```

已经有 publish_time 的跳过，只处理两个时间都为 null 的（notice 和 news 都要处理，list 和 error 不用管）。

### 拉正文内容

```
GET http://{服务地址}/items/{id}/content
```

返回正文，同 classify.md。

### 回写时间

```
POST http://{服务地址}/items/{id}/times
Content-Type: application/json

{
  "publish_time": "2026-09-24",
  "document_time": "2026-09-11"
}
```

两个字段都传，找不到的传 null。

## 时间提取标准

### publish_time（发布时间）

政府网页上"发布时间：""发布日期：""来源："旁边的日期，就是这条文章在网上公开的日期。

- 格式：`YYYY-MM-DD`
- 例子：页面写"发布时间：2026-09-24" → `2026-09-24`
- 页面写"2026年9月24日" → `2026-09-24`

### document_time（成文时间/发文日期）

公文本身的成文日期，在正文末尾落款处，或发文字号下面。

- 格式：`YYYY-MM-DD`
- 例子：正文末尾"2026年9月11日" → `2026-09-11`
- 有的文章标题下写"成文日期：2026-09-11" → 用这个
- 如果正文只有发布日期没有成文日期，document_time 传 null

### 注意

- 两个时间可能相同（当天发当天公开）
- 成文时间一般早于或等于发布时间
- 找不到就传 null，不要瞎猜
- 页面打不开（502）就跳过，不回写

## 处理流程

1. GET `/v2/items/pending-write?limit=10`
2. 对每条 item：
   - 如果 publish_time 和 document_time 都有了，跳过
   - GET `/items/{item.id}/content` 拿正文
   - 从正文提取两个时间
   - POST `/items/{item.id}/times` 回写
3. 全部处理完就结束
