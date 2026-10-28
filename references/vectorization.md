# SVG描摹与双格式交付

PNG保留清理后的灰度透明度；SVG将透明度二值化后描成黑色路径。它们是同一素材的两种表示，由用户按用途选择。SVG不是字体文件，也不恢复原图缺失的细节，不自动成为可量产或可注册的标识。

## 生成

在任务专用Python环境安装Skill的requirements.txt：Pillow、vtracer==0.6.15、resvg-py>=0.5,<0.6。prepare和compose仍可仅用Pillow运行；未装矢量依赖时说明原因，保留PNG，不输出伪SVG。

```text
python <SKILL_DIR>/scripts/lettering.py vectorize --job <任务目录>
```

只处理已通过processing_review的PNG。命令检查原图与PNG哈希，并要求composition.json与当前task.json的字序和布局一致；布局过期时先compose。单字描摹上限4MP，超过时不偷偷降采样，报告并保留PNG。

默认参数：alpha-threshold=96（范围1—255）、mode=spline、filter_speckle=0。阈值降低可保留较淡部分，也会纳入浅杂点；阈值提高可能丢细笔。保留所有小连通区域，不按大小自动除去点画。内部采用2倍最近邻描摹网格，再缩回原坐标，避免孤立单像素退化成零面积路径；这不产生新图像细节。

```text
python <SKILL_DIR>/scripts/lettering.py vectorize --job <任务目录> --alpha-threshold 96 --mode polygon
```

spline拟合曲线；polygon使用多边形，适合曲线拟合改变细节时比较。参数可调整，但必须对照原PNG，不以路径少或轮廓光滑作为唯一目标。SVG使用真实path/group，无外链位图和字体依赖；内部留白保持透明，白底版仅额外添加背景矩形。

## 查看与审核

输出vectorization.json及：

```text
vectors/
  glyphs/        逐位置单字SVG，未审核文件以DRAFT-开头
  exports/       三种排版 × 透明底、白底SVG
  review/        每字SVG渲染PNG、差异PNG
  previews/      排版SVG的实际渲染PNG
  preview.png    PNG / SVG / 差异的对照页，每页最多8字
  preview-02.png 更多对照页（有需要时生成）
```

差异图黑色为共同墨迹，红色为SVG相对阈值掩膜缺少的墨迹，青色为增加的墨迹。mask_iou、lost_ink_ratio与added_ink_ratio是原尺寸二值像素对照指标，不是书法质量或汉字正确率，也不能代替看图。

逐字核对笔锋、转折、内白、细笔和飞白；需要时打开review中的原尺寸图并放大SVG。看过图且可接受的项才填任务目录下的vector-review.json，哈希从vectorization.json相应字形记录复制：

```json
{
  "positions": [
    {
      "index": 0,
      "glyph_sha256": "该位置PNG的实际SHA-256",
      "svg_sha256": "该位置SVG的实际SHA-256",
      "status": "accepted",
      "note": "实际检查结论：具体说明笔锋、内白及飞白的保留或可接受变化。"
    }
  ]
}
```

再运行同一vectorize命令。仅有匹配PNG与SVG哈希、accepted及非空说明的项可以发布正式SVG；不匹配或缺少审核的仍是DRAFT。同一段内有缺字或未审核项，整个段落的SVG排版标为DRAFT。更改阈值或描摹结果导致SVG变化后，旧审核不再生效。

再次运行只清理上一轮清单列出的SVG/预览，不改原图、glyphs/或exports/下的PNG，也不删除用户自行放入的文件。对比参数前复制完整任务目录保留版本。非本命令产生的定制布局（例如两列对联）须以同组已审核路径按原版式另行组合，记录坐标并复核，不能把通用十字单列当对联主版。

## 交付说明

一并提供PNG与SVG链接，明确SVG为描摹版及其检查状态。用户可用PNG保留半透明笔触，用SVG缩放、改色与继续编辑。素材不足或矢量变化不可接受时，交付已完成PNG和明确标注的SVG草稿／缺项，不加粗、补笔、填洞或用生成式修复冒充原帖。

引擎文档：[VTracer Python](https://pypi.org/project/vtracer/)、[resvg-py](https://resvg-py.readthedocs.io/en/latest/api.html)。
