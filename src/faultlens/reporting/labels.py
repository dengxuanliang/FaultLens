from __future__ import annotations

STATUS_LABELS = {
    "passed": "已通过",
    "attributable_failure": "可归因失败",
    "data_issue": "数据问题",
    "join_issue": "关联问题",
    "unknown": "未知",
}

ROOT_CAUSE_LABELS = {
    "task_misunderstanding": "题意理解错误",
    "contract_or_interface_violation": "接口或契约不匹配",
    "solution_incorrect": "解答逻辑错误",
    "implementation_bug": "实现缺陷",
    "incomplete_or_truncated_solution": "解答不完整或被截断",
    "environment_or_api_mismatch": "环境或 API 不匹配",
    "possible_evaluation_mismatch": "可能是评测不一致",
    "insufficient_evidence": "证据不足",
    None: "无",
}

SIGNAL_LABELS = {
    "missing_code": "缺少代码",
    "code_extraction_failed": "代码提取失败",
    "syntax_error": "语法错误",
    "compile_error": "编译失败",
    "runtime_error": "运行时错误",
    "test_failure": "测试失败",
    "timeout": "执行超时",
    "signature_mismatch": "签名不匹配",
    "entrypoint_mismatch": "入口不匹配",
    "api_mismatch": "API 不匹配",
    "logic_mismatch": "逻辑不匹配",
    "metadata_conflict": "元数据冲突",
    "suspicious_eval_mismatch": "疑似评测不一致",
}



def display_case_status(value: str | None) -> str:
    return STATUS_LABELS.get(value, value or "未知")



def display_root_cause(value: str | None) -> str:
    return ROOT_CAUSE_LABELS.get(value, value or "无")



def display_signal(value: str) -> str:
    return SIGNAL_LABELS.get(value, value)



def display_signals(values: list[str]) -> str:
    if not values:
        return "无"
    return "、".join(display_signal(value) for value in values)
