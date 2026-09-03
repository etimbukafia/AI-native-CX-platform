"""Small HTTP surface for customer messages and approval decisions."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cx_platform.domain.models import (
    ConversationRead,
    CXEvent,
    CXMetrics,
    ExecutionReference,
    OutcomeRead,
    Ticket,
    TicketDetail,
    TicketStatus,
)
from cx_platform.services.support import (
    SupportService,
    SupportServiceError,
    SupportTurnResult,
)


class SupportMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    customer_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decided_by: str = Field(min_length=1)
    reason_code: str = Field(default="operator_decision", min_length=1)


def create_app(service: SupportService) -> FastAPI:
    """Create the CX API around one configured support service."""

    app = FastAPI(title="AI-native CX platform")

    @app.post(
        "/conversations/{conversation_id}/messages",
        response_model=SupportTurnResult,
    )
    def handle_message(
        conversation_id: str,
        request: SupportMessageRequest,
    ) -> SupportTurnResult:
        try:
            return service.handle_message(
                conversation_id,
                request.content,
                customer_id=request.customer_id,
                session_id=request.session_id,
            )
        except SupportServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(
        "/approvals/{execution_id}/approve",
        response_model=SupportTurnResult,
    )
    def approve(
        execution_id: str,
        request: ApprovalDecisionRequest,
    ) -> SupportTurnResult:
        try:
            return service.approve(
                execution_id,
                decided_by=request.decided_by,
                reason_code=request.reason_code,
            )
        except SupportServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(
        "/approvals/{execution_id}/reject",
        response_model=SupportTurnResult,
    )
    def reject(
        execution_id: str,
        request: ApprovalDecisionRequest,
    ) -> SupportTurnResult:
        try:
            return service.reject(
                execution_id,
                decided_by=request.decided_by,
                reason_code=request.reason_code,
            )
        except SupportServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/events", response_model=list[CXEvent])
    def events(after: str | None = None, limit: int = 100) -> list[CXEvent]:
        try:
            return service.events(after=after, limit=limit)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(
        "/executions/{execution_id}",
        response_model=ExecutionReference,
    )
    def execution(execution_id: str) -> ExecutionReference:
        reference = service.execution_reference(execution_id)
        if reference is None:
            raise HTTPException(status_code=404, detail="execution was not found")
        return reference

    @app.get("/tickets", response_model=list[Ticket])
    def tickets(
        status: TicketStatus | None = None,
        customer_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[Ticket]:
        try:
            return service.tickets(
                status=status,
                customer_id=customer_id,
                after=after,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/tickets/{ticket_id}", response_model=TicketDetail)
    def ticket(ticket_id: str) -> TicketDetail:
        detail = service.ticket_detail(ticket_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="ticket was not found")
        return detail

    @app.get("/conversations/{conversation_id}", response_model=ConversationRead)
    def conversation(conversation_id: str) -> ConversationRead:
        detail = service.conversation_read(conversation_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="conversation was not found")
        return detail

    @app.get("/outcomes", response_model=list[OutcomeRead])
    def outcomes(
        ticket_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[OutcomeRead]:
        try:
            return service.outcomes(ticket_id=ticket_id, after=after, limit=limit)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/metrics", response_model=CXMetrics)
    def metrics() -> CXMetrics:
        return service.metrics()

    return app


__all__ = ["ApprovalDecisionRequest", "SupportMessageRequest", "create_app"]
