# 本地任务与命令

脚本独立运行，只需要 Python 与 Pillow。先确认 `python -c "import PIL; print(PIL.__version__)"`；必要时使用当前 Codex 提供的 Python 运行时。缺依赖时将本目录 requirements.txt 的 Pillow 安装到任务专用环境，不要求用户提供 API key，不安装 GPU／OCR 模型。

## 1. Agent 准备 selection.json

图片须已由当前可用工具下载，并先看过。相对 input 路径相对于 selection.json 所在目录。每个文字位置独立记录；重复字仍有不同 index，可以选不同写法。

```json
{
  "text": "山水",
  "author_requirement": {"name": "苏轼", "strict": false},
  "notes": ["优先同一部原帖。"],
  "positions": [
    {
      "index": 0,
      "character": "山",
      "input": "downloads/shan.jpg",
      "crop": [0, 0, 200, 180],
      "polarity": "auto",
      "cutoff": 245,
      "normalize": true,
      "character_verified": true,
      "verification_note": "已查看图片，字形为山，并与原帖上下文对应。",
      "source": {
        "page_url": "https://example.org/work/1",
        "image_url": "https://example.org/images/shan.jpg",
        "author": "苏轼",
        "author_status": "source-labeled",
        "work": "原帖名称",
        "script": "行书"
      },
      "candidates": [],
      "attempts": [{"page_url": "https://example.org/work/1", "status": "selected", "note": "已读图核对。"}]
    },
    {
      "index": 1,
      "character": "水",
      "input": null,
      "missing_reason": "三个有效来源均未找到可用图。",
      "attempts": [{"page_url": "https://example.org/other", "status": "expired", "note": "已回来源页刷新，仍不可用。"}]
    }
  ]
}
```

示例地址和裁剪框不能用于实际交付，须替换为真实记录。`crop` 是 **EXIF 方向校正之后**原图中的 `[左, 上, 右, 下]` 整数像素，右／下不包含；未指定时处理整张图。页脚、邻字要在这一步排除，不能裁掉笔锋。

`polarity`：auto／light（浅底深字）／dark（深底浅字）。`cutoff` 140—254，默认245；降低可去除浅杂色，同时可能丢失淡笔，必须对照原图。normalize 估算缓慢变化的纸色，不能修复与笔画重叠的污损。padding 默认5像素。

保留可访问的来源页、稳定图片 ID、版本和出处。临时签名图像可记录域名与路径，不把签名凭据写入长期记录；记录中注明需要回来源页刷新。用户提供图片可用 `source.kind="user-provided"`，并说明无网上出处。作者状态用 source-labeled 或 unknown；只有实际做过独立来源核验才标 independently-checked。

## 2. 准备字形

```text
python <SKILL_DIR>/scripts/lettering.py prepare --selection <selection.json> --output <新的任务目录>
```

不覆盖已有任务目录。原图按 SHA-256 去重保留原始字节，单字分别输出；出错的位置写 missing。支持静态 JPEG、PNG、WEBP、TIFF、BMP、GIF，单图最多40MB／40MP。文字为1—120个汉字；超过12字会分段，超过120字由 Agent 分成多个任务并列明完整段落。

输出 task.json、originals/、glyphs/、sources.md、selection.json。task.json 保存实际处理参数、像素坐标和文件哈希；selection.json 记录输入配置，task.json 足以根据保留的原图重新构建输入。

任务内保存的 selection.json 已将 input 改为 originals/ 的相对路径，可直接用它在一个新的目录再次 prepare。即使原下载目录已删除，复制完整任务包仍可重建；重建后必须重新检查处理图。

## 3. 逐张看图，接受或退回

用当前图像查看工具检查每张 glyphs 图片，并与 originals 原图对照。只有完整、正确、无邻字／印章／页脚残留的字，才在 task.json 对应位置填写：

```json
"processing_review": {"status": "accepted", "note": "已对照原图，笔锋与飞白保留，未见邻字或页脚残片。"}
```

不能批量盲填 accepted。失败时保留原因，改 selection 的裁剪框／参数或换图，在新的版本目录重新 prepare。不得改 glyph PNG 后绕过其哈希；脚本会检测原图或字形文件被替换。

每个位置可有 `layout: {"scale": 1, "dx": 0, "dy": 0}`。scale=.25—1，不拉伸；dx/dy 为像素偏移，边界自动扩展，绝对值不超过4096。修改布局无需重新清理原图。

## 4. 生成排版

```text
python <SKILL_DIR>/scripts/lettering.py compose --job <任务目录>
```

生成 compact、airy、vertical 三种排版，各有透明底、白底 PNG；所有字等比缩放，默认不超过原素材分辨率。preview.png 用于浏览，实际导出以 exports/ 为准。composition.json 记录每个位置的实际尺寸与坐标、各段文字位置和文件。

缺字、待检查、硬性书家不符时生成明确带 DRAFT 的相应段落，不把占位版当完整成品。再次 compose 会替换上次由此命令生成的 exports PNG，清除旧的正式／草稿文件，避免交付过期成品；其他文件不清理。需要保留多个版本时复制任务目录后再调布局。

先查看 preview.png，再查看有疑问的全尺寸 PNG。交付位置用绝对文件链接；交付三种方案、透明字形和 sources.md，说明缺字／换书家／分辨率局限。不要只贴预览而不交付原文件。
