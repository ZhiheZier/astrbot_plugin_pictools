# 表情包素材与来源

本目录的素材以及 [core/memes.py](../../core/memes.py) 中的动画坐标、帧时长和布局移植自：

- 项目：[Lucy / astrbot_plugin_pic_toolbox](https://github.com/lirundong093-glitch/astrbot_plugin_pic_toolbox)。
- 固定版本：[4e9843e06b907c08d91fc48dd1c855668223f4d7](https://github.com/lirundong093-glitch/astrbot_plugin_pic_toolbox/tree/4e9843e06b907c08d91fc48dd1c855668223f4d7)。
- 原代码：上游 `meme/` 下的 `petpet.py`、`shoot.py`、`behead.py`、`do.py`、`lash.py`。
- 原素材：`resource/petpet_hand.png` 和 `resource/{shoot,behead,do,lash}_frames/`。
- 上游许可证：[GNU AGPL v3.0](UPSTREAM_LICENSE)，随本目录保留。项目代码继续使用仓库根目录的 AGPL-3.0 许可证。

移植时改为内存输入/输出、统一 GIF 透明调色板、异步下载和工作线程处理，并增加图片像素、输出文件大小、帧数、处理时间和并发限制。头像采用等比裁剪，圆形蒙版保留原透明度；发射优先按人脸位置裁剪，定位不可用时使用图片中心。生成结果直接返回给 AstrBot。

上游另致谢 [B1gM8c/Petpet](https://github.com/B1gM8c/Petpet) 和 [meme-generator](https://github.com/MeetWq/meme-generator) 的原始算法、素材及灵感来源。

`lbpcascade_animeface.xml` 随原文件完整保留，其文件头包含 nagadomi 的版权声明及 MIT 许可证；来源为 [nagadomi/lbpcascade_animeface](https://github.com/nagadomi/lbpcascade_animeface)。该模型供 OpenCV 人脸定位使用。真人正面和侧脸模型使用 OpenCV 安装包自带的 Haar cascades，不随本插件复制。
