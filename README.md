# 书法集字 · calligraphy-lettering

一个用于题字、牌匾和汉字标识的 Agent Skill：按需在线寻找书法字形，核对文字与出处，用本地算法清理背景，并交付PNG与SVG两种格式的单字和排版。

## 功能

- 先确认文字、视觉偏好和主要用途；关键需求不明确时先提问。
- 从可访问的单字查询及原帖资源中选字，记录逐字出处和归属可信度。
- 默认固定shufa5→9610两站，批量取候选、对重复字去重、复用按需缓存，并设置90秒取图预算；不再为普通任务全网搜索或临时写下载脚本。
- 保留原图；清理纸色、判断黑白极性，输出黑色笔画、透明背景，保留灰度边缘和飞白。
- 生成紧凑横排、疏朗横排、单列竖排，每种均含透明底与白底 PNG。
- 追加真实路径的SVG描摹版，提供渲染与差异对照，经逐字审核后交付，PNG原文件始终保留。
- 保存文件哈希、裁剪框、处理参数、检查结论与排版参数，支持重新生成。

不依赖预建字库、网站服务、GPU、OCR 模型或额外 API 密钥。Python脚本负责固定来源取图、本地清理与排版；Agent负责需求判断、看图核字和选字。

## 安装

克隆仓库后，将整个目录放到 Codex 的 `~/.codex/skills/calligraphy-lettering`，或让 Codex 从该 GitHub 仓库安装 Skill。重新开启会话后使用。

安装 Python 依赖：

```sh
python -m pip install -r requirements.txt
```

要求Python 3.10或更新版本，当前已在Python 3.12验证。安装前确认目标平台和Python版本有对应VTracer二进制包；不要求为此切换到最新Python。依赖见 [requirements.txt](requirements.txt)。

prepare与compose只依赖Pillow；SVG描摹与渲染分别使用VTracer、resvg-py，均在本机运行，无需额外API key。

## 使用

在支持 Skill 的 Agent 中显式调用：

```text
$calligraphy-lettering 为“山水清音”做一组题字，偏温润雅致，主要用于横向牌匾。
```

也可以描述用途，例如“我准备开一家粤菜馆，想做书法门头”。关键条件不够时，Agent 会先确认名称、视觉气质与主要使用位置，然后找图和制作。

默认交付同组字形的三种排列，不代表三套独立品牌方向。指定“必须某书家”时作为硬条件处理；缺字会明确报告，不擅自改字或补字。

## 本地命令

先用固定路线批量取图：

```sh
python scripts/lettering.py fetch --text "山水清音" --script 行书 --output /path/to/fetch --cache-dir /path/to/cache
```

查看fetch-report.json和候选拼图后，选字并补齐selection.json中的视觉核对说明、裁剪框。fetch不会自动核字。默认只向缺字切换备用站，缓存原字节按哈希核验；更多选项见[固定来源指南](references/sources.md)。大鹏及馆藏用于原帖／指定书家的精细需求，不进入默认自动回退。

再按[任务格式](references/task-format.md)处理：

```sh
python scripts/lettering.py prepare --selection /path/to/selection.json --output /path/to/new-job
```

逐张对照原图与 `glyphs/`，确认文字、笔画、裁剪与背景处理后，在 `task.json` 中逐字填写 `processing_review`。再生成排版：

```sh
python scripts/lettering.py compose --job /path/to/new-job
```

prepare和compose只读取已保存素材；fetch负责找图，所有命令都不能代替看图检查。未审核、缺字或不满足指定书家条件的位置只能生成标为 DRAFT 的草稿。

默认追加SVG：

```sh
python scripts/lettering.py vectorize --job /path/to/new-job
```

首次SVG为DRAFT。查看PNG/SVG/差异预览，按[矢量化说明](references/vectorization.md)填写绑定哈希的vector-review.json，再运行同一命令，审核通过的文件才作为正式SVG输出。用户可选择PNG保留灰度笔触，或SVG用于缩放和编辑；描摹不能恢复低清原图缺失的细节。

## 输出

```text
任务目录/
  originals/          原始图片
  glyphs/             逐字透明 PNG
  exports/            三种版式 × 透明底、白底
  preview.png         方案预览
  sources.md          逐字来源与检查说明
  selection.json      可重新准备素材的输入
  task.json           哈希、处理参数与审核记录
  composition.json    最终版式参数
  vectors/            单字SVG、三种SVG版式及实际渲染／差异预览
  vectorization.json  描摹参数、哈希、量化对照及审核状态
  vector-review.json  看图后填写的逐字SVG审核（生成命令不自动接受）
```

## 测试

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

测试覆盖浅底深字、深底浅字、泛黄背景、透明度与飞白、空图、裁剪越界、重复字、字序、比例、缺字草稿及独立命令运行；并实际渲染SVG检查透明孔洞、细笔、单像素点、审核失效与PNG不被覆盖。实际汉字识别与视觉质量仍需逐张看图确认。

取图测试另覆盖固定域名、书体与文字筛选、指定书家、仅缺字回退、缓存哈希、预算停止及连续网络失败后暂停来源。取图预算不等于完整交付耗时；网络、文字难度和Agent看图速度仍会影响总时间。

## 范围与素材说明

本仓库只提供 Skill、脚本、参考资料和测试，不打包第三方字库、客户成品、聊天记录或临时下载。网站标注的作者不等于原帖独立鉴定；可下载不代表获得商业授权，具体素材的使用条件须根据来源确认。

保真模式不使用生成式 AI 重绘或补笔，不擦除覆盖笔画的水印。不放大后宣称高清原稿，不承诺印刷级分辨率、商标注册或门头量产可用性；实际尺寸及工艺需另行验证。

完整操作规范见 [SKILL.md](SKILL.md)，来源入口见[素材来源指南](references/sources.md)。
