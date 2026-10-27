# 素材来源与取图

接口记录核对日期：2026-10-28。站点和接口可能变化，使用时以当前页面为准。可查看或下载不等于统一授权；记录明确声明和未知项，不编造授权结论。

## 单字查询

- [大鹏书法字典](https://zidian.dapengshufa.com/)：按文字、书家、书体和碑帖查找，支持原帖定位。可从当前页面取得字形ID、版本、原帖坐标和图片地址。
- [书法字典](https://www.shufazidian.com/)：从可见查询控件检索，核对作者及原帖。没有稳定公开接口时使用正常网页，不伪造令牌。
- [以观](https://app.ygsf.com/)：先确认网页版是否可用及访问条件；仅凭宣传数量不算取得素材。

大鹏前端内部检索接口的请求记录：

```text
POST /api/v1/glyphs/search
```

```json
{"text":"山水","matching":"traditional_simplified","filters":{"script_tags":[],"author_ids":[],"edition_ids":[]},"limit_per_position":3,"cursors":{}}
```

返回positions及各位置的input、total_count、items；字形包含character、author、book、script、edition_id、page、thumb_url、revision、box、size。来源页格式为`/work/<edition_id>/<page>`。ID从真实页面或响应取得，不猜测。

原图接口记录为`GET /api/v1/glyphs/<glyph_id>/original?revision=<revision>`，可返回status、url、dimensions和expires_in。只有当前页面仍使用该接口时才按其实际形状请求；它不是承诺稳定的公开API，失败后转网页或换源，不扫描接口。

临时图像地址过期时回来源页刷新，以expires_in等实际字段判断有效期，不写死签名地址。原图可能与缩略图分辨率相同；扩展名与实际编码也可能不同，以解码结果为准。下载原件后裁去字区外页脚，不能裁掉笔锋。

## 原帖与馆藏

- [书法空间9610](https://www.9610.com/)：按书家浏览作品页，读取页面实际大图链接；不沿文件编号猜图或批量下载。原帖通常没有单字框，需要看图定位和核字。
- [国立故宫数字典藏](https://digitalarchive.npm.gov.tw/)：核对作品记录、馆藏号、释文和页码，再从作品页取得IIIF manifest，按其实际图像资源裁字。同名作品可能有多个版本，不能仅凭标题匹配。
- [哈佛燕京图书馆特藏](https://library.harvard.edu/libraries/harvard-yenching-library/special-collections)：沿馆方目录确认拓片来源；转载合集编号或文件名不能替代馆藏号。

## 选图与异常处理

优先同一书家或同一帖，选完整、清楚、背景简单、尺寸接近的原字。搜索缩略图只作为线索，打开来源页并尽量取得实际大图。网站标注归属仅支持source-labeled，不等于独立鉴定。

首轮每字最多3个候选。缺字查3个有效来源仍无合适结果时停止并记录。将网络错误、过期、登录／付费限制与真正无候选区分；不绕过安全警告。需要账号的来源先换可用资源，无法满足硬条件时明确报告。

邻字残边可调整裁框；红印、水印覆盖笔画、原图残缺或纸色与笔画无法分离时换图或留缺字。不得擦除压在笔画上的水印、捏造笔锋或用生成图冒充原帖。
