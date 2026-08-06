from app.modules.governance.consent.application.use_cases.check_consent import CheckConsent
from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult
from app.platform.inbound.graph.state import KurehaState


def make_consent_gate_node(check_consent: CheckConsent):
    async def consent_gate(state: KurehaState) -> dict:
        if state["intent"] in ("staff", "shift"):
            return {"consent_ok": True}

        ctx = state["request_ctx"]
        if ctx.patient_id is None:
            return {"consent_ok": False}

        result = await check_consent.execute(ctx.to_tenant_context(), patient_id=ctx.patient_id)
        return {"consent_ok": result is ConsentCheckResult.CURRENT}

    return consent_gate
