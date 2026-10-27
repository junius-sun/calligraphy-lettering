# 书法集字 · calligraphy-lettering

一个用于题字、牌匾和汉字标识的 Agent Skill：按需在线寻找书法字形，核对文字与出处，用本地算法清理背景，并交付可复用的透明单字和三种排版。

## 功能

- 先确认文字、视觉偏好和主要用途；关键需求不明确时先提问。
- 从可访问的单字查询及原帖资源中选字，记录逐字出处和归属可信度。
- 保留原图；清理纸色、判断黑白极性，输出黑色笔画、透明背景，保留灰度边缘和飞白。
- 生成紧凑横排、疏朗横排、单列竖排，每种均含透明底与白底 PNG。
- 保存文件哈希、裁剪框、处理参数、检查结论与排版参数，支持重新生成。

不依赖预建字库、网站服务、GPU、OCR 模型或额外 API 密钥。在线检索、看图核字和选字由当前 Agent 平台完成；Python 脚本负责本地清理与排版。

## 安装

克隆仓库后，将整个目录放到 Codex 的 `~/.codex/skills/calligraphy-lettering`，或让 Codex 从该 GitHub 仓库安装 Skill。重新开启会话后使用。

安装 Python 依赖：

```sh
python -m pip install -r requirements.txt
```

建议使用 Python 3.10 或更新版本。图片处理依赖见 [requirements.txt](requirements.txt)。

## 使用

在支持 Skill 的 Agent 中显式调用：

```text
$calligraphy-lettering 为“山水清音”做一组题字，偏温润雅致，主要用于横向牌匾。
```

也可以描述用途，例如“我准备开一家粤菜馆，想做书法门头”。关键条件不够时，Agent 会先确认名称、视觉气质与主要使用位置，然后找图和制作。

默认交付同组字形的三种排列，不代表三套独立品牌方向。指定“必须某书家”时作为硬条件处理；缺字会明确报告，不擅自改字或补字。

## 本地命令

先由 Agent 下载并查看原图，按[任务格式](references/task-format.md)编写 `selection.json`：

```sh
python scripts/lettering.py prepare --selection /path/to/selection.json --output /path/to/new-job
```

逐张对照原图与 `glyphs/`，确认文字、笔画、裁剪与背景处理后，在 `task.json` 中逐字填写 `processing_review`。再生成排版：

```sh
python scripts/lettering.py compose --job /path/to/new-job
```

命令不会自动找图，也不会代替看图检查。未审核、缺字或不满足指定书家条件的位置只能生成标为 DRAFT 的草稿。

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
```

## 测试

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

测试覆盖浅底深字、深底浅字、泛黄背景、透明度与飞白、空图、裁剪越界、重复字、字序、比例、缺字草稿及独立命令运行。实际汉字识别与视觉质量仍需逐张看图确认。

## 范围与素材说明

本仓库只提供 Skill、脚本、参考资料和测试，不打包第三方字库、客户成品、聊天记录或临时下载。网站标注的作者不等于原帖独立鉴定；可下载不代表获得商业授权，具体素材的使用条件须根据来源确认。

保真模式不使用生成式 AI 重绘或补笔，不擦除覆盖笔画的水印。不放大后宣称高清原稿，不承诺印刷级分辨率、商标注册或门头量产可用性；实际尺寸及工艺需另行验证。

完整操作规范见 [SKILL.md](SKILL.md)，来源入口见[素材来源指南](references/sources.md)。
