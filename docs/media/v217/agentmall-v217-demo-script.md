# AgentMall V2.17 · 3分30秒演示讲解稿

实际成片：`agentmall-v217-demo.mp4`，3:30 / 1440×1080 / 25fps / H.264，静音字幕版。所有业务画面来自V2.16 RC1离线原片；V2.17负责剪辑、说明卡及本轮新的独立回归。全程 **OFFLINE MOCK DEMO / REAL BUSINESS API / REAL POSTGRESQL**。原片SHA256 `c2becdda2b5b33d467d3ff789a83af79d94ca1aa32d775a0bd3c90c5c70e45e1`，原录制器exit1超时保持不变，原件不覆盖。

| 成片时间 | 讲解 | 画面/证据性质 |
|---|---|---|
| 00:00–00:12 | 模型给建议，用户授权，确定性服务提交交易；技术栈与证据边界 | 新介绍卡 |
| 00:12–00:43 | 比较价格、库存、连接与数量；快照不同于独立GET；不购买就不写订单 | 原片32–51秒与事实说明卡；删除初始等待及重复比较画面 |
| 00:43–01:06 | 审查商品/数量/金额/快照，明确批准后唯一待付款订单、刷新读回 | 原片107–122秒，独立购买HITL |
| 01:06–01:58 | Supervisor协调售后/检索/购买；先退货确认，再独立购买确认，旧确认不能复用 | 原片122–152秒与双HITL说明 |
| 01:58–02:26 | 已提交业务与后续模型失败可以并存，UNKNOWN不自动补发 | 原片166–178和231–247秒；旧Mock预算不等于Live许可 |
| 02:26–02:48 | SQL：A订单+0；B订单+1；C Case+1/订单+1；三个新确认消费，付款退款增量0 | SQL回执投影卡，非终端录屏；排除Setup订单1/模拟付款1/确认2 |
| 02:48–03:12 | LangChain适配模型工具，LangGraph管理路由状态，业务服务负责事务 | 架构说明卡 |
| 03:12–03:30 | 离线与真实BGE专项分层；L8只有5评分；UNKNOWN、Holdout0与Release ON_HOLD | 真实限制说明 |

没有背景音乐、旁白或真实Provider画面；可按本稿现场口述。剪掉原片登录开头、长静态等待和重复停留，保留实际动作的顺序与状态。13个章节写入MP4元数据，具体源时间和字幕见[EDL](edit-list.json)。

## 复现剪辑

媒体工具为可选本地依赖，不加入业务锁文件：Pillow12.0.0、imageio-ffmpeg0.6.0。使用受控的新媒体环境，显式选择本地中文字体，不下载替代原片。

```sh
python scripts/render_interview_video.py \
  --source /absolute/path/agentmall-v216-rc1-offline-demo.webm \
  --edit-list docs/media/v217/edit-list.json \
  --output /absolute/path/new-agentmall-v217-demo.mp4 \
  --work-dir /absolute/path/new-owned-media-work \
  --font /absolute/path/local-chinese-font.ttc
```

输出及工作目录必须不存在，脚本拒绝覆盖；源文件SHA必须匹配EDL。脚本只读取媒体并编码，不能调用Agent或数据库。先逐段编码，再写章节、faststart并完整解码；还须人工抽帧和敏感内容检查，不能只依据编码退出码。本次媒体核验回执见[V2.17交付](../../V217_INTERVIEW_READY.md)。
