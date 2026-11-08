# Third-party notices — source review scope

AgentMall原创源码、文档和合成项目素材由权利人Cockatoo-xlk选择[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；第三方内容保留自己的许可证。项目MIT不替代上游通知、不授予上游商标或未拥有的权利。

## 本次实际分发的材料

本源码分发范围包含项目源码、合成数据/政策、迁移、测试、依赖锁、构建配方、说明文档、脱敏摘要及经审查的合成UI截图（各阶段范围见下文；V2 RC 共29张）。可达Git历史来自公开独立根及必要修订，不包含原Private研发历史。Live原始账本/授权/对话、私有Checkpoint、本地.env、模型权重、node_modules、site-packages、dist、浏览器和Docker镜像层不在本源码分发文件中。没有把未来构建产物纳入本次源码分发审查。

| 组件或素材 | 目录中的实际内容与许可处理 |
|---|---|
| Lucide / Feather | 页面import lucide-react 1.64.0；截图显示其图标。保留该版本发行包的[完整ISC/Feather MIT许可及署名](docs/third-party/lucide-react-LICENSE.txt)，包含Lucide Icons and Contributors及Cole Bemis声明。没有将其当成项目自有图标授权。[上游许可](https://lucide.dev/license)。 |
| Lightning CSS / MPL-2.0 | 锁中24条含多平台/嵌套版本；没有库源码或原生二进制文件在审核目录中。仅依赖引用，不对上游改标MIT。若以后分发库文件/构建产物，按[MPL官方FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)核对具体文件、通知和源码获得方式。 |
| caniuse-lite / CC-BY-4.0 | 锁中一个数据包引用；本目录没有复制该包的数据文件。来源[Browserslist/caniuse-lite](https://github.com/browserslist/caniuse-lite)，其[CC-BY许可](https://creativecommons.org/licenses/by/4.0/)继续适用；以后若再分发数据须保留署名、许可链接和修改说明。不能只由开发依赖推断数据已进入dist。 |
| Psycopg / psycopg-binary | 锁定3.3.6，实际发行元数据LGPL-3.0-only。本目录没有复制库、libpq或OpenSSL二进制；不能以项目MIT覆盖其[对应版本许可](https://github.com/psycopg/psycopg/blob/3.3.6/LICENSE.txt)。以后分发wheel/镜像/组合二进制须核对通知、库替换/源码获得及捆绑许可。 |
| 前端商品SVG | [ProductArt](frontend/src/components/ProductArt.tsx)是项目仓库的代码插画。权利人已确认原创/AI辅助内容经审阅并具备必要公开授权权限；未下载第三方商品照片或品牌素材。 |
| 三张Fixture截图 | 原R2及R4审阅的合成UI，保留来源/哈希及Lucide/Feather署名；没有真人、真实交易/地址、账号密钥或原始模型对话。截图不是本轮Live或录屏。 |
| Python/Node其他依赖 | 源码通过包管理器引用，未vendoring安装目录；清单保留242个前端锁条目及110个后端锁记录。上游许可证仍独立适用，参考[元数据清单](docs/evidence/dependencies.json)。 |
| Docker / BGE | 只含固定Digest构建配方及冻结embedding声明，不含镜像层、浏览器、模型文件；真实BGE测试缺权重如实跳过。发布镜像/权重需要新的审查和授权。 |

本次`THIRD_PARTY_SOURCE_SCOPE_REVIEW=PASS`，仅指已清点源码/文档/截图范围及保留声明。包锁元数据并非全平台合规证明：R4未安装的可选GPU/平台包可能仍标UNKNOWN，当前没有其文件被分发；未来新增vendoring、dist、wheel、镜像或模型权重时重新审核，不能沿用本次结论。

[本轮分发范围证据](docs/evidence/r5-third-party-scope.json)记录R5源码审核时的实际文件、第三方许可哈希和许可范围。

## T14-P0本地补充材料

T14-P0增加四张[模拟付款Fixture截图](docs/evidence/t14-p0/screenshots.json)，均来自合成数据、真实本地服务与Fake Model测试，逐张进行了隐私及PNG元数据检查。页面中的Lucide/Feather图标继续保留上表完整许可及署名；截图没有被当成上游图标的自有授权。本轮未新增第三方包、权重、分发镜像或安装目录；R5三张历史截图及其证据保持原样。


## T14-P1及本地发布候选补充

T14-P1另有三张[购物车Fixture截图](docs/evidence/t14-p1/screenshots.json)，包括待支付时已消费购物车、变化后保留商品的移动页面及查询失败的未知数量提示。本轮重新逐张检查P0/P1七张PNG，没有附带文本或EXIF元数据、真实身份/地址、凭据或模型原始对话。P0四张属于修复购物车之前的历史验收，不能用其旧徽标状态声称当前P1行为；原图和哈希保持不变。

这些截图继续使用项目合成商品插画与已有Lucide/Feather图标，原完整许可/署名文件保持原样。本轮未新增产品依赖或第三方素材，也未复制第三方源码、模型权重、wheel、浏览器或构建镜像进入拟提交树。项目内安装的审计工具及依赖缓存留在忽略目录，不属于本次源码分发。当前范围仍为SOURCE_ONLY；未来分发安装后的Psycopg、Lightning CSS、caniuse-lite数据、镜像或二进制时分别重审相应LGPL/MPL/CC-BY及捆绑许可义务。

## T15源码与截图范围

T15-A五张[SDK MockTransport截图](docs/evidence/t15-a/screenshots.json)展示离线合成Provider响应、独立人工确认、恢复和超时UNKNOWN，并非真实DeepSeek调用截图。T15-D1核验全部15张及其可达历史Blob，检查PNG元数据并逐张审阅可见内容；未发现Key、JWT、个人路径、真实身份或未经审阅的第三方图片。旧截图保持原字节与哈希，不把历史界面当成最新Live验收。[本阶段许可与截图审查](docs/evidence/t15-d1/license-and-images.json)保留具体范围。Python/Node锁文件及原Lucide/Feather完整许可未变，没有新增第三方分发物。


## V2 RC 源码分发范围

V2.1—V2.4沿用既有依赖和图标声明，没有新增第三方包或图片。当前可达历史包含29个合成UI图片Blob，15张的旧审核清单继续绑定其历史阶段，另有后续截图保持原字节。RC只分发源码和经过审查的静态评测投影；本地原始日志、Oracle快照与新验证截图留在忽略目录。


## V2.5目录与插画

本地V2.5扩展增加108条自建合成商品记录及10类原创代码SVG示意，不使用真实品牌图、外部照片或远程资产。新增3张浏览器截图只展示合成目录与TEST_OPERATOR确认页，按[目录验证摘要](docs/evidence/v25/verification.json)记录来源与哈希。原有Lucide/Feather声明继续适用；未新增第三方依赖、模型权重、二进制或镜像分发。此前29张截图属于各历史阶段；本目录新增后合计32张。


## V2.8 MCP源码接入

新增官方[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)依赖`mcp==2.3.0`及`mcp-types==2.3.0`，安装元数据声明为MIT。项目只分发调用SDK的自有适配源码和锁文件，不复制SDK源码、wheel、安装目录或镜像；捆绑分发时须保留SDK及传递依赖各自许可。本轮锁文件只增加所需依赖，没有更改既有包版本，也不修改历史依赖审计Manifest。

[客户端回执图](docs/screenshots/v28/mcp-client-receipts.png)由本轮真实合成数据JSON生成，文字和布局为项目自建，不是MCP Inspector UI截图或真实LLM结果，不含外部图片。原有图标与截图署名继续保留。


## V2.10 本地模型与检索截图

本轮仅分发自有适配代码、固定文件SHA/大小Manifest、合成相关性标签、脱敏数值与自建界面截图。公开模型[BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)和[BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base)的官方模型卡声明MIT；分别固定Revision `7999e1d3359715c523056ef9478215996d62a620`、`2cfc18c9415c912f9d8155881c133215df768a70`。实际模型仅在本地忽略缓存中使用，没有将权重、分词器文件、模型README、Torch/Transformers安装包或镜像分发进Git。Manifest记录文件哈希与来源，不以项目MIT替代模型许可；未来若分发模型/镜像仍需单独检查上游通知与依赖许可。

本轮未新增或升级包锁依赖。两张[检索截图](docs/REAL_RETRIEVAL.md#页面截图)仅显示合成商品、单标注者查询与真实本地CPU指标；不含真人、真实客户资料、原始Prompt、JWT或DSN，原Lucide/Feather完整署名继续适用。
