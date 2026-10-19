# Emoji Kitchen 组合索引

- 上游：[arnav-kr/emoji-kitchen](https://github.com/arnav-kr/emoji-kitchen)。
- 固定版本：[152b3c690f843879cf28d9dbdee061f69e553fa8](https://github.com/arnav-kr/emoji-kitchen/tree/152b3c690f843879cf28d9dbdee061f69e553fa8)。
- 原数据：`packages/go/emoji-kitchen/data.ekbf`。
- 许可：[AGPL-3.0](UPSTREAM_LICENSE)，随本目录保留。

[index.json.gz](index.json.gz) 从原 EKBF v1 文件离线转换为压缩 JSON，包含 619 个规范 emoji、554 个别名，以及 149,509 组现有组合；索引内最近的素材日期为 2026-04-29。转换保留原图日期、文件名顺序及别名映射，插件通过 [core/emoji_kitchen.py](../../core/emoji_kitchen.py) 双向查询并统一处理 emoji 显示选择符。

用户直接发送 `😀+😂` 即可触发合成，完整用法见项目 [README](../../README.md#emoji-合成)。

组合索引随插件提供，不需要运行时下载完整元数据，也不需要 API Key。组合图片属于 Google Emoji Kitchen，运行时从 `https://www.gstatic.com/android/keyboard/emojikitchen/` 获取；图片设计者和权利仍归原权利人，数据索引的代码许可证不改变图片本身的权利。

组合可用性由此索引快照决定，不支持任意两个 emoji。部分 emoji 别名会映射到上游指定的规范 emoji，例如部分肤色、性别或相近表情会共享素材。
