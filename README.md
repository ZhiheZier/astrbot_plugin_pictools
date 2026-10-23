# 图片处理工具

适用于 **AstrBot 4.22+、NapCat / OneBot v11（aiocqhttp 适配器）** 的图片处理插件。图片变换、喜报悲报和表情包使用 Pillow 本地处理；emoji 合成下载 Emoji Kitchen 现有组合图片，不需要 API Key。

## 功能

| 命令                                      | 效果                                                   |
| ----------------------------------------- | ------------------------------------------------------ |
| `左对称` / `右对称`                       | 将左侧 / 右侧镜像到另一侧                              |
| `上对称` / `下对称`                       | 将上侧 / 下侧镜像到另一侧                              |
| `对称` / `镜像` / `左右翻转` / `水平翻转` | 整张图左右翻转，与参考 Python 文件中的「对称」含义一致 |
| `上下翻转` / `垂直翻转`                   | 整张图上下翻转                                         |
| `顺时针` / `逆时针`                       | 旋转 90°                                               |
| `旋转 45`                                 | 按给定角度顺时针旋转；支持 -360~360，负数为逆时针      |
| `反色`                                    | 反转 RGB 颜色，保留透明度                              |
| `灰度` / `黑白`                           | 灰度化，保留透明度                                     |
| `倒放`                                    | 倒放 GIF，帧时长跟随对应帧逆序                         |
| `调速 2`                                  | GIF 两倍速；支持 0.1~10 倍                             |
| `喜报 今天考试通过了`                     | 生成红黄配色喜报，无需提供图片                         |
| `悲报 假期结束了`                         | 生成黑白配色悲报，无需提供图片                         |
| `摸头` / `摸头杀`                         | 生成摸头 GIF，支持发图、引用、@用户或先命令后发图      |
| `发射`                                    | 生成射击 GIF，图片来源同摸头；自动定位人脸             |
| `杀 @用户` / `砍头 @用户`                 | 用被 @ 用户头像生成砍头 GIF                            |
| `操你 @用户` / `撅人 @用户`               | 用发送者和目标头像生成双人 GIF                         |
| `抽你 @用户` / `鞭笞 @用户`               | 用发送者和目标头像生成鞭笞 GIF                         |
| `😀+😂` / `❤️ + 🔥` / `😀＋😂`            | 直接合成两个 Unicode emoji，无需命令前缀               |
| `图片帮助` / `图片工具` / `对称帮助`      | 显示帮助                                               |
| `取消图片处理`                            | 取消自己的待处理操作                                   |

变换命令支持静态 PNG、JPEG、WebP、BMP 等 Pillow 可解码的图片，以及 GIF。静态图返回 PNG，GIF 返回 GIF；动画 WebP/APNG 暂不支持，会明确提示转换为 GIF。奇数宽高的对称保留中央行/列，尺寸不变。任意角度旋转会扩展画布，新增区域透明。

GIF 使用解码后的完整画面处理，保留循环设置和正常帧时长。输出 GIF 使用最多 255 种不透明颜色和一个透明索引，半透明按 128 阈值转换，可能出现 GIF 格式固有的颜色量化。调速以 10ms 为精度、最短帧时长为 20ms；遇到过快的倍率会提示实际效果受限。不会为了调速丢帧，编码器可能合并连续相同画面并累计时长。

## 使用

普通命令默认支持带 `/` 和不带 `/` 的写法，不匹配普通句子中的命令词；关闭 `match_mode` 后需加 `/`。Emoji 合成直接发送 `emoji+emoji`，不受此设置影响。

1. **同条消息**：发送 `/左对称`，同时附上图片。
2. **引用图片**：回复一条含图片的消息，发送 `/反色`。
3. **分两步发送**：先发送 `/倒放`，收到提示后在 120 秒内发送 GIF。
4. **处理头像**：发送 `/右对称 @某人`，或 `@某人 /右对称`。

图片变换、摸头和发射每次只处理第一张图片，来源优先级为 **同条消息图片 → 引用图片 → @用户头像**。@机器人不会被当作头像目标。等待操作按平台会话和发送者隔离；普通聊天不会清空等待状态，超时后自动失效。等待期间发送另一条没有附图、引用图或头像目标的图片处理命令，可以更换待处理操作。

### 喜报、悲报

发送 `/喜报 你的内容` 或 `/悲报 你的内容` 即可生成图片；默认也支持不带 `/` 的写法。不需要上传图片或连接外部服务。正文支持中文、英文和真实换行，最多 500 字，会按实际文字宽度自动折行，长文本会缩小字号；过多换行导致无法排版时会提示缩短内容。只移除开头的命令词，正文中的「喜报」「悲报」会完整保留。

背景直接使用 [Essential 插件](https://github.com/Soulter/astrbot_plugin_essential) 的原版喜报、悲报图片，随插件提供，保留原图标题和装饰；正文使用随包提供的 Noto Sans SC 中文字体。素材来源见 [resources/reports/README.md](resources/reports/README.md)。生成任务与图片处理共用白名单、冷却间隔和并发限制；不会清空当前等待上传图片的操作。

### 表情包

已接入 pic_toolbox 的五类表情包及对应素材：摸头（5 帧）、发射（13 帧）、杀（21 帧）、操你（3 帧）、抽你（9 帧）。所有结果为循环 GIF，生成时复用现有的文件大小、像素、帧数、时间和并发限制。输入动图时使用首帧，并给出提示。

- `/摸头` 附图片、引用图片后 `/发射`，或 `/摸头 @某人`。也可先发命令，再上传图片。
- `/杀 @某人` 使用目标头像；`/操你 @某人`、`/抽你 @某人` 同时使用发送者和目标头像。这三类必须 @一个目标用户，且仅支持 NapCat / OneBot v11；关闭 `enable_at_avatar` 后不可用。
- `@机器人` 只用于唤醒，不会被选为头像目标。杀、操你、抽你均使用指定 QQ 头像并忽略消息附图；双人表情包中，发送者和目标的角色与上游一致。

`发射` 会尝试定位动漫、真人正面和侧脸。OpenCV 已包含在统一的 `requirements.txt` 中，通过插件管理器安装时会随其他依赖一起安装；手动更新插件时，在 AstrBot 使用的 Python 环境中安装依赖，然后重载插件：

```sh
python -m pip install -r requirements.txt
```

未检测到人脸或检测不可用时会回退到中心裁剪并提示。素材和人脸模型的来源、许可证见 [resources/memes/README.md](resources/memes/README.md)。

### Emoji 合成

Emoji 合成仅支持直接发送 `😀+😂`、`❤️ + 🔥` 或 `😀＋😂`。加号两侧可以有空格，支持半角 `+` 和全角 `＋`。整条文本需为两个完整的 Unicode emoji 加一个加号；普通文字、三个 emoji 或仅相邻发送 `😀😂` 不会触发。此方式不受 `match_mode` 设置影响。

在 NapCat / OneBot v11（aiocqhttp）中，合成结果以 **QQ 自定义表情包** 发送。按照 [NapCat 图片消息格式](https://napneko.github.io/develop/msg#image)设置表情子类型 `sub_type=1`，群聊、私聊均适用。其他平台仍返回普通图片。

支持显示选择符、肤色及 ZWJ 组成的完整表情；不支持 QQ 自带的编号表情。交换输入顺序会得到同一组组合结果，重复输入同一 emoji 也可查询。

组合索引随插件提供，当前包含 149,509 组组合，不支持任意两个 emoji。不支持的 emoji 或没有结果的组合会明确提示。部分肤色、性别或相近 emoji 根据上游别名规则共享素材。此功能需要访问 Google 的 `www.gstatic.com` 图片服务；下载失败会提示重试。

`emoji` 解析依赖已包含在统一的 `requirements.txt` 中，在插件加载时导入，缺失时可由 AstrBot 的依赖恢复机制安装。手动更新后需安装依赖并重载插件。合成任务与其他图片处理共用白名单、冷却和并发限制，不会清空等待上传图片的操作。来源与索引快照信息见 [resources/emoji_kitchen/README.md](resources/emoji_kitchen/README.md)。

## 安装与重载

插件目录应为 `AstrBot/data/plugins/astrbot_plugin_pictools`。在本插件目录中，使用 AstrBot 的 Python 环境执行以下命令，然后在 WebUI 的「插件」页重载本插件。通过插件管理器安装时，AstrBot 会负责安装依赖。

```sh
python -m pip install -r requirements.txt
```

在 AstrBot 中配置 `aiocqhttp` 平台，并按 NapCat 的 OneBot v11 反向 WebSocket 配置连接 AstrBot；NapCat 消息格式使用 `array`。插件复用 AstrBot 的 OneBot 连接，无须另行填写 NapCat 地址或 Token。

## WebUI 配置

配置通过 `_conf_schema.json` 暴露；修改后重载插件生效。

| 配置               | 默认值     | 说明                                                                  |
| ------------------ | ---------- | --------------------------------------------------------------------- |
| `match_mode`       | `true`     | 允许普通命令省略 `/`；不影响 `emoji+emoji` 触发                       |
| `enable_at_avatar` | `true`     | 允许通过 @用户处理 QQ 头像                                            |
| `report_font_size` | `65`       | 喜报、悲报首选正文字号（24~160）；长内容最低缩至 20                   |
| `pending_timeout`  | `120`      | 等待图片的秒数                                                        |
| `cooldown_seconds` | `3`        | 每个会话每个用户的处理间隔；0 关闭                                    |
| `max_concurrent`   | `2`        | 插件同时处理请求数；忙时直接提示重试                                  |
| `max_file_mb`      | `20`       | 单个输入或输出文件大小上限，单位 MiB                                  |
| `max_pixels`       | `16000000` | 输入/输出单帧像素上限                                                 |
| `max_frames`       | `200`      | 变换 GIF 的输入帧数、表情包的生成帧数上限                             |
| `max_total_pixels` | `24000000` | 总像素预算；变换 GIF 按输入帧累计，表情包按输出帧累计，静态图也受此限 |
| `download_timeout` | `30`       | 下载超时秒数                                                          |
| `process_timeout`  | `30`       | 图片处理时间预算；在操作之间检查，不能中断单次原生调用                |
| `allowed_groups`   | `[]`       | 群号白名单，空列表不限制，不影响私聊                                  |
| `allowed_users`    | `[]`       | 用户 QQ 号白名单，空列表不限制                                        |

下载使用异步 HTTP，检查响应头和流式读取的实际大小，逐次验证重定向及 DNS 地址。仅允许公网 HTTP/HTTPS、80/443 端口，不接受任意文本 URL 或任意本地路径；本地输入限制为 AstrBot 临时媒体目录。文件 ID 可通过 NapCat `get_image` 解析，缺少引用内容时通过 `get_msg` 获取消息。结果直接作为 Base64 图片发送，不产生输出临时文件。

## 参考与致谢

- [arnav-kr/emoji-kitchen](https://github.com/arnav-kr/emoji-kitchen)：Emoji Kitchen 组合索引来源，保留 [来源与许可证](resources/emoji_kitchen/README.md)；合成图片由 Google 提供。
- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)
- [NapCat 接口文档](https://napcat.apifox.cn/)
- [Pillow GIF 文档](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif)。

图片变换核心和事件层在本插件实现，表情包布局及素材按 AGPL-3.0 从 pic_toolbox 移植。项目代码沿用仓库原有的 [AGPL-3.0 许可证](LICENSE)。随包字体使用独立的 [SIL Open Font License 1.1](resources/OFL.txt)，来源及版权见 [resources/README.md](resources/README.md)。喜报、悲报背景的来源及权利说明见 [resources/reports/README.md](resources/reports/README.md)。
