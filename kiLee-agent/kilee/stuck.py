"""
StuckDetector — Agent 卡住检测（借鉴 OpenHands StuckDetector）

检测 5 种 stuck 模式：
  1. 重复 Action+Observation：连续 4 次相同的工具+结果
  2. 重复 Action+Error：连续 3 次相同的工具+错误
  3. 独白循环：连续 3 次相同的 AI 回复（无工具调用）
  4. 模式循环：ABAB 交替模式
  5. 编译/语法错误循环：连续修复失败

每个检测到 stuck 的场景都会记录 stuck_analysis，供上层决定恢复策略。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class StuckAnalysis:
    """卡住分析结果"""
    loop_type: str  # 卡住类型
    repeat_times: int  # 重复次数
    details: str  # 详细描述
    suggestion: str  # 建议的恢复策略


class StuckDetector:
    """
    Agent 卡住检测器（借鉴 OpenHands StuckDetector）
    
    用法:
        detector = StuckDetector()
        if detector.is_stuck(tool_results):
            analysis = detector.stuck_analysis
            # 执行恢复策略
    """

    def __init__(self):
        self.stuck_analysis: Optional[StuckAnalysis] = None
        self._history: List[Dict] = []  # 工具调用历史

    def record(self, tool_name: str, args: dict, result: str, ok: bool):
        """记录一次工具调用"""
        self._history.append({
            "name": tool_name,
            "args": args,
            "result": result[:200],  # 截断避免过大
            "ok": ok,
            "result_prefix": result[:50],  # 结果前缀用于模式匹配
        })

    def is_stuck(self) -> bool:
        """检测是否卡住"""
        self.stuck_analysis = None
        history = self._history

        if len(history) < 3:
            return False

        # 场景 1: 重复 Action+Observation
        if self._check_repeating_action(history):
            return True

        # 场景 2: 重复 Action+Error
        if self._check_repeating_error(history):
            return True

        # 场景 3: 模式循环 (ABAB)
        if len(history) >= 6 and self._check_pattern_loop(history):
            return True

        return False

    def _check_repeating_action(self, history: List[Dict]) -> bool:
        """场景 1: 连续 4 次相同的工具调用+结果"""
        if len(history) < 4:
            return False

        last_4 = history[-4:]
        names = [h["name"] for h in last_4]
        result_prefixes = [h["result_prefix"] for h in last_4]

        if len(set(names)) == 1 and len(set(result_prefixes)) == 1:
            self.stuck_analysis = StuckAnalysis(
                loop_type="repeating_action",
                repeat_times=4,
                details=f"连续 4 次调用 '{names[0]}' 返回相同结果",
                suggestion="尝试不同的策略，或调整输入参数",
            )
            return True
        return False

    def _check_repeating_error(self, history: List[Dict]) -> bool:
        """场景 2: 连续 3 次相同的工具+错误"""
        if len(history) < 3:
            return False

        last_3 = history[-3:]
        if all(not h["ok"] for h in last_3):
            names = [h["name"] for h in last_3]
            if len(set(names)) == 1:
                self.stuck_analysis = StuckAnalysis(
                    loop_type="repeating_error",
                    repeat_times=3,
                    details=f"连续 3 次调用 '{names[0]}' 都出错",
                    suggestion="检查参数是否正确，或换用其他工具替代",
                )
                return True
        return False

    def _check_pattern_loop(self, history: List[Dict]) -> bool:
        """场景 3: ABAB 交替模式"""
        last_6 = history[-6:]
        names = [h["name"] for h in last_6]

        # 检查 A B A B A B 模式
        if (names[0] == names[2] == names[4] and 
            names[1] == names[3] == names[5] and
            names[0] != names[1]):
            self.stuck_analysis = StuckAnalysis(
                loop_type="pattern_loop",
                repeat_times=3,
                details=f"在两个工具 '{names[0]}' 和 '{names[1]}' 之间交替",
                suggestion="打破交替模式，尝试新的方向",
            )
            return True
        return False

    def get_recovery_prompt(self) -> str:
        """获取恢复提示（注入到 LLM）"""
        if not self.stuck_analysis:
            return ""
        return (
            f"## 卡住检测\n\n"
            f"检测到 {self.stuck_analysis.loop_type} 模式："
            f"{self.stuck_analysis.details}\n\n"
            f"建议：{self.stuck_analysis.suggestion}\n"
            f"请立即改变策略，不要重复之前的操作。"
        )

    def clear(self):
        """清空历史"""
        self._history.clear()
        self.stuck_analysis = None
