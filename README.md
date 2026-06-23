# resource_gif_and_image_and_other

资源与工具集合仓库。

## 目录结构

```
├── resource/          # 资源文件
│   └── arc_cute_gif/  # Arc 可爱表情包 GIF（A/B 两组，共 40 张，160×160）
├── scripts/           # 脚本工具
│   └── resize_gif.py  # 批量缩放图片脚本
└── README.md
```

## 工具说明

### resize_gif.py — 批量缩放图片

支持 GIF（保留动画）、PNG、JPG、WebP、BMP 等格式，按宽度等比缩放。

```bash
# 缩放 arc_cute_gif 中所有 GIF 到 160px 宽
python scripts/resize_gif.py -i resource/arc_cute_gif -w 160

# 指定输出目录和格式
python scripts/resize_gif.py -i resource/arc_cute_gif -o output -w 320 -f gif,png,jpg
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-i` / `--input` | 输入目录（必填） | — |
| `-o` / `--output` | 输出目录 | 覆盖原文件 |
| `-w` / `--width` | 目标宽度 (px) | 160 |
| `-f` / `--formats` | 图片格式，逗号分隔 | gif,png,jpg,jpeg,webp,bmp |
