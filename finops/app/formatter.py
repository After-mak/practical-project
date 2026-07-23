from typing import List
from app.schemas import RecommendationData, PolicyResult

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
        팀원 7의 텔레그램 봇으로 즉각 전송할 수 있는 깔끔한 마크다운 형식의 
        FinOps 분석 리포트 메시지를 생성합니다.
        """
        
        # 위험 등급별 이모지 설정
        risk_emoji = "🟢"
        if risk_score == "HIGH":
            risk_emoji = "🔴"
        elif risk_score == "MEDIUM":
            risk_emoji = "🟡"
            
        status_emoji = "✅" if overall_status == "PASS" else "❌"
        
        lines = [
            "📢 *AI 기반 FinOps 리소스 최적화 권장 보고서*",
            "",
            f"📌 *대상 워크로드 정보*",
            f"• Deployment: `{deployment_name}`",
            f"• Namespace: `{namespace}`",
            "",
            "📊 *리소스 사양 비교 표*",
            "```",
            "| 항목    | CPU      | Memory   |",
            "|---------|----------|----------|",
            f"| Current | {recommendations.current.cpu:<8} | {recommendations.current.memory:<8} |",
            f"| KRR     | {recommendations.krr.cpu:<8} | {recommendations.krr.memory:<8} |",
            f"| Final   | {recommendations.final.cpu:<8} | {recommendations.final.memory:<8} |",
            "```",
            "*※ Final은 KRR 추천값에 운영 정책 및 Chronos 미래 예측을 적용해 자동 보정한 값입니다.*",
            "",
            "💰 *예상 리소스 및 비용 절감률*",
            f"• CPU 감소율: *{round(cpu_reduction_pct, 1)}%*",
            f"• Memory 감소율: *{round(memory_reduction_pct, 1)}%*",
            f"• **예상 월 비용 절감률: {round(cost_savings_pct, 1)}%**",
            "",
            "⚠️ *위험도 및 정책 검증*",
            f"• 종합 위험도: {risk_emoji} *{risk_score}*",
            f"• 최종 승인 여부: {status_emoji} *{overall_status}*",
            "",
            "🛠️ *세부 정책 검사 내역*",
        ]
        
        # 개별 정책 위반 사항들 중 중요하게 볼 만한 내역 요약
        for eval_res in policy_evaluations:
            status_symbol = "✔️" if eval_res.status == "PASS" else "⚠️" if eval_res.status == "WARN" else "🚫"
            lines.append(f"{status_symbol} *[{eval_res.rule_id}] {eval_res.name}*: _{eval_res.status}_")
            lines.append(f"  └ {eval_res.description}")
            
        lines.extend([
            "",
            "---",
            "❓ *해당 권장 사항을 EKS 클러스터에 반영 승인하시겠습니까?*" if overall_status == "PASS" else "ℹ️ *정책 위반(OOM/재시작)으로 최적화 적용이 불가능하여 승인 요청이 생략됩니다.*"
        ])
        
        return "\n".join(lines)
