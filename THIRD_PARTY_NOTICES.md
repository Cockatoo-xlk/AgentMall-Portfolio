# Third-party notices — source review scope

AgentMall原创源码、文档和合成项目素材由权利人Cockatoo-xlk选择[MIT](LICENSE)，Copyright (c) 2026 Cockatoo-xlk；第三方内容保留自己的许可证。项目MIT不替代上游通知、不授予上游商标或未拥有的权利。

## 本次实际分发的材料

本地最终审核目录仅包含项目源码、合成数据/政策、迁移、测试、依赖锁、构建配方、说明文档、脱敏摘要和三张Fixture截图。原始Git历史、Live账本/授权/对话、私有Checkpoint、本地.env、模型权重、node_modules、site-packages、dist、浏览器和Docker镜像层不在目录中。已逐文件清点；没有把未来构建产物纳入本次源码分发审查。

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

[本轮分发范围证据](docs/evidence/r5-third-party-scope.json)记录实际文件、第三方许可哈希和范围。尚未公开上传，PUBLICATION_AUTHORIZED=NO、PUBLIC_RELEASE_NOT_RUN。
