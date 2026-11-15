"""Conservative current-request actions and quantities, never model-granted authority."""

import re

from agentmall.infra.errors import DomainError

CLAUSES = re.compile(r"[，。；,;\n]|但是|但|然后|同时|并且")
NEGATIVE = re.compile(
    r"(?:(?:先别|不要|不想|不需要|不打算|不准备|不用|无需|无须|不必|暂不|取消|撤销|放弃|禁止|不得|不允许|不可以|不能|不准|切勿|勿)"
    r"[^，。；,;\n]*|(?:别|不)(?:再|先|请|帮我|直接|立即)*)\s*$"
)
CONDITION = re.compile(
    r"如果|假如|若|(?:等|待)[^，。；,;\n]{0,12}(?:再|后)|通过后|确认后|以后|考虑|犹豫"
)
INFORMATION = re.compile(
    r"是什么|什么意思|政策|定义|介绍|解释|如何|怎样|能否|是否|可不可以|请问|查看|查询|流程|记录"
    r"|采购(?:清单|部门|人员|流程|记录|合同|说明|计划)"
)
REPORTED = re.compile(r"昨天|之前|曾经|上次|已经|已(?:经)?|记录|说明|提到|写着|例如|比如|[‘“\"「]")
THIRD_PARTY = r"(?:供应商|客服|商家|卖家|平台|同事|他们|她们|他|她)"
INDIRECT = re.compile(
    r"(?:让|叫|要求|通知)\s*" + THIRD_PARTY + r"|" + THIRD_PARTY + r"(?:让|叫|要求|通知)(?:我|本人)"
)
OWN_COMMAND = re.compile(
    r"^\s*(?:(?:再|另|并|先|然后|接着|同时|也|直接|立即|马上)\s*)*"
    r"(?:请|帮我|我要|我想|我准备|我需要|本人|准备|"
    r"(?:再|另)?(?:找|推荐)(?:另一款|一款|一件|一个))"
)
PLANNED_ACTION = re.compile(
    r"^\s*(?P<subject>[^，。；,;\n]{1,24}?)(?:将(?:会)?|会|计划|打算|准备)"
    r"(?=\s*(?:采购|购买|下单|买|生成|创建|建立|申请|退货|联系|转|找))"
)
RETURN_ACTION = re.compile(
    r"(?:(?:生成|创建|建立|准备|发起|提交|办理)\s*(?:一[份个张]\s*)?"
    r"退货(?:提案|申请|请求)|申请退货|准备退货|想退掉|想退货|退货|退掉)"
)
SUPPORT_ACTION = re.compile(
    r"(?:(?:转接?|联系|找)\s*人工(?:客服)?|"
    r"(?:建立|创建|生成|开立|(?<!打)开|建)(?=[^，。；,;\n]*(?:人工|客服))"
    r"(?=[^，。；,;\n]*工单))"
)
NUMBER = r"[0-9零〇一二两三四五六七八九十百]+"
COUNT = re.compile(
    r"(?<![第0-9零〇一二两三四五六七八九十百])(" + NUMBER + r")\s*(件|只|个|台|把|副|套|支|份)"
)
RANGE = re.compile(NUMBER + r"\s*(?:到|至|[-~～])\s*" + NUMBER)


def clarification(message):
    raise DomainError(409, "CONTEXT_CLARIFICATION_REQUIRED", message)


def action_scope(message, start):
    """A condition before a comma still scopes the following action."""
    return re.split(r"[。；;\n]", message[:start])[-1]


def action_decision(clause, before, *, scope=""):
    """Classify the local action's scope; an informational topic grants nothing."""
    if REPORTED.search(before):
        return None
    if INDIRECT.search(before):
        clarification("间接动作的请求主体不明确，请说明本人的当前决定")
    if re.search(r"(?:不要|禁止|不允许|不准).*(?:让|叫|要求)(?:助手|别人|他人|模型)", before):
        clarification("间接动作的否定作用域不明确，请单独说明决定")
    if NEGATIVE.search(before):
        return False
    if CONDITION.search(clause) or CONDITION.search(scope):
        clarification("动作条件或作用域尚未明确，请单独说明当前决定")
    if INFORMATION.search(clause):
        return None
    if not OWN_COMMAND.match(before):
        if re.search(THIRD_PARTY, before):
            return None
        planned = PLANNED_ACTION.search(clause)
        if planned and planned["subject"].strip() not in {"我", "本人", "我自己", "再", "先"}:
            if not OWN_COMMAND.match(planned["subject"]):
                return None
    return True


def _request_intent(message, pattern, *, bare=(), explanatory_contact=False):
    decisions = set()
    offset = 0
    for clause in CLAUSES.split(message):
        start = message.find(clause, offset)
        offset = start + len(clause)
        for match in pattern.finditer(clause):
            scoped_clause = clause
            if (
                explanatory_contact
                and re.fullmatch(r"(?:转接?|联系|找)\s*人工(?:客服)?", match[0])
                and re.match(r"\s*(?:解释|说明)", clause[match.end() :])
                and not CONDITION.search(clause)
                and not re.search(r"请问|能否|是否|可不可以|[？?]", clause)
            ):
                # A request to contact a human may explain its purpose afterward.
                # The text before the action still excludes policy questions.
                scoped_clause = clause[: match.end()]
            decision = action_decision(
                scoped_clause,
                clause[: match.start()].strip(),
                scope=action_scope(message, start + match.start()),
            )
            if match[0] in bare and decision is True:
                continue
            if decision is not None:
                decisions.add(decision)
    if len(decisions) > 1:
        clarification("动作请求与撤销冲突，请明确当前决定")
    return next(iter(decisions), None)


def return_intent(message):
    # Here a past-time qualifier modifies the product; the explicit desire is current.
    # Already-completed/historical action markers remain visible to REPORTED.
    message = re.sub(
        r"(?:之前|上次|昨天)(?=[^，。；,;\n]*(?:订单|商品|键盘|鼠标|耳机)"
        r"[^，。；,;\n]*想退(?:掉|货))",
        "",
        message,
    )
    return _request_intent(message, RETURN_ACTION, bare={"退货", "退掉"})


def support_intent(message):
    return _request_intent(message, SUPPORT_ACTION, explanatory_contact=True)


def _number(text):
    if text.isascii() and text.isdigit():
        value = int(text)
    else:
        value = {word: index for index, word in enumerate("零一二三四五六七八九十")}.get(text)
        if text == "两":
            value = 2
    if value is None or not 1 <= value <= 10:
        clarification("购买数量须明确为一至十件商品")
    return value


def purchase_quantity(message, *, typed_quantity=None):
    """Extract quantities only after a purchase action or its explicit quantity clause."""
    from agentmall.agents.purchase_intent import ACTION, PRODUCT_ID, purchase_intent

    if typed_quantity is not None and (
        type(typed_quantity) is not int or not 1 <= typed_quantity <= 10
    ):
        clarification("结构化购买数量须为一至十")
    intent = purchase_intent(message)
    if intent.requested is False:
        return None
    values = []
    purchase_seen = False
    action_count = 0
    for clause in CLAUSES.split(message):
        clause_intent = purchase_intent(clause)
        if clause_intent.requested:
            actions = [m for m in ACTION.finditer(clause) if not m["negative"]]
            if len(actions) != 1:
                clarification("请为唯一购买动作说明数量")
            action_count += 1
            if action_count > 1:
                clarification("多个购买动作不能合并为一个商品数量")
            purchase_seen = True
            suffix = re.sub(PRODUCT_ID, " ", clause[actions[0].end() :])
            if COUNT.search(clause[: actions[0].start()]):
                clarification("购买数量作用域不明确")
            if re.search(r"和|以及|、|或", suffix) or RANGE.search(suffix):
                clarification("购买商品或数量存在多个候选")
            matches = list(COUNT.finditer(suffix))
            if len(matches) > 1:
                clarification("请明确唯一购买商品及其数量")
            values.extend(_number(m[1]) for m in matches)
        elif purchase_seen and re.match(r"\s*数量(?:是|为|[:：])?", clause):
            matches = list(COUNT.finditer(clause))
            if len(matches) != 1 or RANGE.search(clause):
                clarification("请明确唯一购买数量和单位")
            values.append(_number(matches[0][1]))
        elif purchase_seen and COUNT.search(clause) and not INFORMATION.search(clause):
            if not re.search(r"推荐|查看|查询|步骤|订单|历史", clause):
                clarification("购买动作外的商品数量作用域不明确")
    if len(set(values)) > 1:
        clarification("购买数量存在冲突")
    quantity = next(iter(values), None)
    if quantity is not None and typed_quantity is not None and quantity != typed_quantity:
        clarification("购买数量与结构化选择冲突")
    return quantity if quantity is not None else typed_quantity
