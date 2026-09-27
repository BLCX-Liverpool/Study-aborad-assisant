# Page Quality Rules

## Native Text 可用

满足以下条件时，页面可直接进入 chunking：

- 文本长度足够表达页面内容。
- 非空白字符占比正常。
- 不存在明显乱码。

## OCR Candidate

以下情况标记为 OCR candidate：

- 页面几乎没有 native text。
- 文本长度极短但页面应包含大量内容。
- 出现大量不可读字符。

## 当前版本处理

当前版本已有 Deepdoc OCR 适配入口。对于 OCR candidate：

- 保存 page quality metadata。
- 优先调用 Deepdoc OCR 适配器补充可检索文本。
- 如果 OCR 依赖未配置或执行失败，在用户请求中提示该页仍需要后续 OCR 处理。
- 不虚构该页内容。
