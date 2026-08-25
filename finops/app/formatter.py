import html
from typing import List
from app.schemas import RecommendationData, PolicyResult

def _esc(value) -> str:
    """Telegram HTML parse_mode로 전송되므로 동적 문자열에 <, >, & 등이 섞여도
    엔티티 파싱 오류(400 Bad Request)가 나지 않도록 이스케이프합니다."""
    return html.escape(str(value), quote=False)

class ReportFormatter:
    @staticmethod
    def generate_telegram_markdown(
        deployment_name: str,
        namespace: str,
        cpu_reduction_pct: float,
        memory_reduction_pct: float,
        cost_savings_pct: float,
        risk_score: str,
        overall_status: str,
        recommendations: RecommendationData,
        policy_evaluations: List[PolicyResult]
    ) -> str:
        """
        텔레그램 봇으로 전송할 수 있는 깔끔한 HTML 형식의 FinOps 분석 리포트 메시지를 생성합니다.
        """
        
        risk_emoji = "🟢"
        if risk_score == "HIGH":
            risk_emoji = "🔴"
        elif risk_score == "MEDIUM":
            risk_emoji = "🟡"
            
        status_emoji = "✅" if overall_status == "PASS" else "❌"

        if cost_savings_pct >= 0:
            cost_line = f"• <b>예상 월 비용 절감률: {round(cost_savings_pct, 1)}%</b>"
        else:
            cost_line = f"• ⚠️ <b>예상 월 비용 증가율: {round(abs(cost_savings_pct), 1)}% (비용 증가 예상)</b>"

        def _resource_change_line(label: str, reduction_pct: float) -> str:
            """reduction_pct는 양수=절감, 음수=증가입니다. 증가인 경우에도 0%로 뭉개지 않고
            '증가율'로 라벨을 바꿔서 실제 방향과 크기를 그대로 보여줍니다."""
            if reduction_pct >= 0:
                return f"• {label} 감소율: <b>{round(reduction_pct, 1)}%</b>"
            return f"• ⚠️ {label} 증가율: <b>{round(abs(reduction_pct), 1)}%</b> (증가 예상)"

        # KRR이 사용 이력 데이터 부족으로 권장값을 산출하지 못한 리소스는 현재값을 그대로 보여주는 대신
        # "데이터부족"이라고 명시해, KRR이 실제로 그 값을 추천한 것처럼 오인하지 않도록 합니다.
        krr_cpu_display = "데이터부족" if recommendations.krr_cpu_data_insufficient else recommendations.krr.cpu
        krr_mem_display = "데이터부족" if recommendations.krr_memory_data_insufficient else recommendations.krr.memory

        lines = [
            "📢 <b>AI 기반 FinOps 리소스 최적화 권장 보고서</b>",
            "",
            "📌 <b>대상 워크로드 정보</b>",
            f"• Deployment: <code>{_esc(deployment_name)}</code>",
            f"• Namespace: <code>{_esc(namespace)}</code>",
            "",
            "📊 <b>리소스 사양 비교 표</b>",
            "<pre>",
            "| 항목    | CPU      | Memory   |",
            "|---------|----------|----------|",
            f"| Current | {recommendations.current.cpu:<8} | {recommendations.current.memory:<8} |",
            f"| KRR     | {krr_cpu_display:<8} | {krr_mem_display:<8} |",
            f"| Final   | {recommendations.final.cpu:<8} | {recommendations.final.memory:<8} |",
            "</pre>",
            "<i>※ Final은 KRR 추천값에 운영 정책 및 Chronos 미래 예측을 적용해 자동 보정한 값입니다.</i>",
            "",
            "💰 <b>예상 리소스 및 비용 변화율</b>",
            _resource_change_line("CPU", cpu_reduction_pct),
            _resource_change_line("Memory", memory_reduction_pct),
            cost_line,
            "",
            "⚠️ <b>위험도 및 정책 검증</b>",
            f"• 종합 위험도: {risk_emoji} <b>{risk_score}</b>",
            f"• 최종 승인 여부: {status_emoji} <b>{overall_status}</b>",
            "",
            "🛠️ <b>세부 정책 검사 내역</b>",
        ]

        for eval_res in policy_evaluations:
            status_symbol = "✔️" if eval_res.status == "PASS" else "⚠️" if eval_res.status == "WARN" else "🚫"
            lines.append(f"{status_symbol} <b>[{eval_res.rule_id}] {_esc(eval_res.name)}</b>: <i>{eval_res.status}</i>")
            lines.append(f"  └ {_esc(eval_res.description)}")
            
        lines.extend([
            "",
            "---------------------------------------",
            "❓ <b>해당 권장 사항을 EKS 클러스터에 반영 승인하시겠습니까?</b>" if overall_status == "PASS" else "ℹ️ <i>정책 위반으로 승인 요청이 생략됩니다.</i>"
        ])
        
        return "\n".join(lines)
