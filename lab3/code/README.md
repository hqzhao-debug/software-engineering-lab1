# 校园循物：校园二手交易系统

这是实验三的可运行软件及技术使用说明。程序用 Python 3.11 或更新版本、标准库和 SQLite 实现，不需要安装运行依赖。每条商品代表一件物品；系统管理发布、审核、预约及卖家声明完成，付款和交付在线下进行。

本文件用于运行和维护代码，不是实验报告。实验任务书要求本人独立书写报告，并阅读检查使用的代码；本项目的自动测试、AI 复核和演示不能代替本人审阅，也不表示人工验收已完成。

## 快速运行

在当前 `code` 目录打开终端：

```sh
python3 --version
python3 -m campus_market --help
python3 -m campus_market.demo
```

演示创建独立临时数据库，注册三个虚构账号，完成邮箱开发适配器验证、商品审核、组合查询、预约、幂等重试、越权拒绝、确认、完成、取消、违规及重开数据库检查。运行结束自动删除临时数据。若要保留演示数据，使用尚未存在的新目录：

```sh
python3 -m campus_market.demo --directory local-demo
```

程序拒绝覆盖已有演示数据库。保留的数据含本地验证邮件与数据库，请勿放入公开仓库。

运行自动测试：

```sh
python3 -m unittest discover -s tests -v
```

项目也提供统一的 Make 入口：

```sh
make build
make test
make demo
make metrics
```

`make build` 生成 `dist/campus-market.pyz`，可用 `python3 dist/campus-market.pyz --help` 检查和运行。源码也可直接运行，无须先安装打包产物。`make metrics` 统计真实源码规模。

风格检查使用开发依赖 Ruff 0.14.2，可在虚拟环境安装后执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PATH="$(pwd)/.venv/bin:$PATH" make lint
```

若没有 Make，可查阅 `Makefile` 中的对应 Python 命令直接执行。开发依赖不属于软件运行依赖；更完整的构建设置见 `pyproject.toml` 和 `tools/`。

## 数据和会话

默认数据库为 `data/market.sqlite3`，默认本地验证邮件目录为 `data/outbox/`。全局参数放在子命令前：

```sh
python3 -m campus_market --db data/market.sqlite3 --session-file data/seller.json me
```

登录会话文件包含敏感凭据，创建权限为 `0600`，不在正常 JSON 输出中显示。不同角色使用不同 `--session-file`；同一会话仅更新自己的闲置时间，30 分钟没有主动请求即失效。退出只撤销当前会话，封禁撤销被封账号的全部会话。

密码默认交互输入且不回显。自动化测试可使用 `CAMPUS_PASSWORD` 环境变量；不要把真实密码写进脚本、提交记录或命令参数。高级自动化可通过 `CAMPUS_SESSION_TOKEN` 临时提供会话，正常操作使用会话文件即可。数据库与邮件目录仅供可信操作系统用户访问；本程序没有隔离不可信本地用户直接读取数据库的能力。

## 三角色操作示例

以下名称和邮箱均为虚构示例，`campus.example` 仅用于本地开发。示例里的 `ACCOUNT_ID`、`PRODUCT_ID`、`SUBMISSION_ID`、`RESERVATION_ID` 和 `ROW_VERSION` 应替换为上一条命令返回的真实值，不要原样输入。

1. 初始化管理员。此操作只能用于完全空的账号数据库，后续管理员只能由已有管理员创建。

```sh
python3 -m campus_market init-admin --username manager --email manager@campus.example --campus-id staff-demo
```

返回账号编号后，用开发邮件文件完成验证并登录：

```sh
python3 -m campus_market verify --mail-file data/outbox/ACCOUNT_ID.json
python3 -m campus_market --session-file data/admin.json login manager
```

2. 分别注册卖家、买家，每次按返回的账号编号找到对应本地邮件并验证。

```sh
python3 -m campus_market register --username seller --email seller@campus.example --campus-id seller-demo
python3 -m campus_market verify --mail-file data/outbox/SELLER_ACCOUNT_ID.json
python3 -m campus_market --session-file data/seller.json login seller

python3 -m campus_market register --username buyer --email buyer@campus.example --campus-id buyer-demo
python3 -m campus_market verify --mail-file data/outbox/BUYER_ACCOUNT_ID.json
python3 -m campus_market --session-file data/buyer.json login buyer
```

3. 卖家新建商品草稿，记录返回的 `id`、`row_version`。

```sh
python3 -m campus_market --session-file data/seller.json draft --title 软件工程教材 --category 教材书籍 --condition 九成新 --price 38.50 --description 校内面交
python3 -m campus_market --session-file data/seller.json submit PRODUCT_ID --version ROW_VERSION --key submit-book-1
```

草稿也可以用 `--content-file content.json` 提交完整 JSON 内容。修改已有草稿使用 `--product-id` 和 `--version`，每次保存提交的是完整内容对象，不是只更新填写的字段。图片先通过 `upload-image 文件路径` 上传，再把返回的编号放入 `images` 数组或 `--image` 参数。未正式提交的内容只有卖家本人可读。

```json
{
  "title": "软件工程教材",
  "category": "教材书籍",
  "condition": "九成新",
  "price": "38.50",
  "description": "校内面交，书页完整",
  "images": []
}
```

4. 管理员查看待审核商品，按本次 `submit` 返回的提交编号处理。通过和驳回都必须填写原因。

```sh
python3 -m campus_market --session-file data/admin.json products --scope admin --state REVIEW
python3 -m campus_market --session-file data/admin.json review SUBMISSION_ID approve --reason 资料完整且符合发布规则
```

5. 买家查询商品，读取 `content_version` 后预约。交互模式会显示标题和价格，输入 `yes` 才继续。

```sh
python3 -m campus_market --guest products --keyword 软件工程 --category 教材书籍 --min-price 30 --max-price 40
python3 -m campus_market --session-file data/buyer.json reserve PRODUCT_ID --content-version 1 --message 周三下午图书馆门口面交 --key reserve-book-1
```

同一次操作重试必须保持参数和 `--key` 完全一致；预约成功后商品不再公开，重试使用 `--yes` 跳过交互详情预览，服务仍会重新鉴权、校验请求摘要并返回原预约的当前状态。新预约使用新请求键。`--yes` 只表示调用者已确认标题价格，不跳过业务校验。

6. 卖家确认面交约定，线下面交后声明完成。

```sh
python3 -m campus_market --session-file data/seller.json confirm RESERVATION_ID --key confirm-book-1
python3 -m campus_market --session-file data/seller.json complete RESERVATION_ID --key complete-book-1
python3 -m campus_market --session-file data/seller.json stats
python3 -m campus_market --session-file data/admin.json stats
```

成交金额取预约快照中的标价，不表示系统核验过付款。只有卖家可完成已确认预约；管理员不能替代卖家执行交易操作。

## 其他操作

| 场景 | 子命令及关键参数 |
| --- | --- |
| 查看公开/本人/管理员商品 | `products --scope public/mine/admin --page 1` |
| 当前商品及提交审核历史 | `product PRODUCT_ID`、`product-history PRODUCT_ID` |
| 保存修改 | `draft --product-id PRODUCT_ID --version ROW_VERSION --content-file content.json` |
| 撤回未处理提交 | `withdraw PRODUCT_ID --version ROW_VERSION` |
| 本人主动下架 | `off-shelf PRODUCT_ID --version ROW_VERSION` |
| 删除从未提交的纯草稿 | `delete-draft PRODUCT_ID --version ROW_VERSION` |
| 卖家拒绝待确认预约 | `reject RESERVATION_ID --key KEY --reason 原因`，原因可不填 |
| 买家取消待确认预约 | `cancel RESERVATION_ID --key KEY`，原因可不填 |
| 双方取消已确认预约 | `cancel RESERVATION_ID --key KEY --reason 原因`，原因必填 |
| 本人相关预约 | `reservations --side buyer/seller/all --state COMPLETED --page 1` |
| 单条预约 | `reservation RESERVATION_ID` |
| 违规管理 | `violation PRODUCT_ID --reason 原因` |
| 账号管理 | `accounts`、`ban ACCOUNT_ID --reason 原因`、`unban ACCOUNT_ID --reason 原因` |
| 创建新管理员 | `create-admin --username ... --email ... --campus-id ...`，新账号仍需验证 |
| 图片保存 | `image IMAGE_ID output.png`，只导出有权访问的引用且不覆盖已有文件 |
| 查询日志 | `logs --object-id ID --operation OPERATION --result SUCCESS --actor-id ACCOUNT_ID --start UNIX_SECONDS --end UNIX_SECONDS --page 1` |
| 时间区间统计 | `stats --start UNIX_SECONDS --end UNIX_SECONDS`，含上下边界 |
| 退出 | `logout` |

表格中的斜线表示选择其中一个值，不是原样输入。每条命令可添加 `--help` 查看完整参数。命令成功退出码为 0，参数/业务/本地读写错误为 2，用户中断为 130。结果用 UTF-8 JSON 输出；状态英文名与 UML 状态一一对应。

商品状态包括 `DRAFT`、`REVIEW`、`REJECTED`、`ON_SALE`、`PENDING`、`CONFIRMED`、`OFF_SHELF`、`VIOLATION`、`SOLD`；预约状态包括 `PENDING`、`CONFIRMED`、`REJECTED`、`CANCELLED`、`COMPLETED`。旧编辑页使用错误行版本将被拒绝，避免覆盖他人的较新操作。

## 验证邮件配置

本地 `outbox` 只模拟注册验证流程，不能证明真实邮箱归属。实际校园域名尚未由项目方确认；部署时通过 `--domain 实际校园域名` 明确配置。

可选 SMTP 适配器使用 `--mail-mode smtp`，从环境读取 `CAMPUS_SMTP_HOST`、`CAMPUS_SMTP_PORT`（默认 465）、`CAMPUS_SMTP_FROM`，以及可选 `CAMPUS_SMTP_USER`、`CAMPUS_SMTP_PASSWORD`。它通过 SMTP over TLS 发送注册验证码；收到邮件后执行 `verify` 并交互输入验证码。课程演示没有配置实际校园邮箱服务，因此不宣称已完成真实邮件收发验收。

## 设计对应与范围

代码中的 `AccountMixin`、`ProductMixin`、`TradeMixin`、`AdminMixin` 对应账号、商品、交易和管理模块；日志、统计与访问控制由服务协作提供。数据库表保存账号、会话、私人内容、不可变提交版本、审核批次、预约快照、违规、封禁、幂等记录和审计日志。详细存储与边界见 `技术说明.txt`；原设计图在上一级 `UML` 目录保留。

实现采用 SQLite 单写者事务与部分唯一索引，代替实验二的 PostgreSQL 行锁；命令行界面代替实验二的浏览器 UI。实验三允许此类实现调整且不强制图形界面。本程序没有声称完成浏览器 Chrome/Edge 兼容性或首次使用者易用性验收。也没有实现支付、配送、在线聊天、推送、收藏、举报、候补或自动超时取消。

UML 图保留为实验二基线，部分技术名称仍为 PostgreSQL/浏览器；应结合本说明理解实际实现。自动生成的测试输出只是对应环境下的可重复技术证据。本人逐行阅读、判断 AI 代码及独立报告写作需要由本人完成并记录真实过程。
