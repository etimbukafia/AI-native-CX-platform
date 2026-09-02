from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .database import Database
from .models import ActiveScenario, BusinessEvent, CancellationResult, Customer, Order, Policy, Refund, RefundRequest, ScenarioSummary, Shipment
from .service import BusinessRuleError, BusinessService, DependencyUnavailable


def create_app(database_path: str | None = None) -> FastAPI:
    database = Database(database_path or os.getenv("MOCK_BUSINESS_DB", "mock_business.db"))
    service = BusinessService(database)
    app = FastAPI(title="Reference Commerce Business", version="0.1.0")
    app.state.business_service = service

    def get_service(request: Request) -> BusinessService:
        return request.app.state.business_service

    @app.exception_handler(DependencyUnavailable)
    async def dependency_unavailable(_: Request, exc: DependencyUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(BusinessRuleError)
    async def business_rule_error(_: Request, exc: BusinessRuleError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/scenarios", response_model=list[ScenarioSummary])
    def list_scenarios(current: BusinessService = Depends(get_service)) -> list[ScenarioSummary]:
        return current.list_scenarios()

    @app.post("/scenarios/{scenario_id}/activate", response_model=ActiveScenario)
    def activate_scenario(scenario_id: str, current: BusinessService = Depends(get_service)) -> ActiveScenario:
        try:
            return current.activate_scenario(scenario_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Scenario not found") from exc

    @app.get("/customers/{customer_id}", response_model=Customer)
    def get_customer(customer_id: str, current: BusinessService = Depends(get_service)) -> Customer:
        try:
            return current.customer(customer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Customer not found") from exc

    @app.get("/customers/{customer_id}/orders", response_model=list[Order])
    def get_customer_orders(customer_id: str, current: BusinessService = Depends(get_service)) -> list[Order]:
        try:
            return current.customer_orders(customer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Customer not found") from exc

    @app.get("/orders/{order_id}", response_model=Order)
    def get_order(order_id: str, current: BusinessService = Depends(get_service)) -> Order:
        try:
            return current.order(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc

    @app.get("/orders/{order_id}/shipment", response_model=Shipment)
    def get_shipment(order_id: str, current: BusinessService = Depends(get_service)) -> Shipment:
        try:
            return current.shipment(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Shipment not found") from exc

    @app.post("/orders/{order_id}/cancel", response_model=CancellationResult)
    def cancel_order(order_id: str, current: BusinessService = Depends(get_service)) -> CancellationResult:
        try:
            return current.cancel_order(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc

    @app.post("/refunds", response_model=Refund, status_code=201)
    def request_refund(request: RefundRequest, current: BusinessService = Depends(get_service)) -> Refund:
        try:
            return current.request_refund(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc

    @app.get("/policies/{topic}", response_model=Policy)
    def get_policy(topic: str, current: BusinessService = Depends(get_service)) -> Policy:
        try:
            return current.policy(topic)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Policy not found") from exc

    @app.get("/events", response_model=list[BusinessEvent])
    def get_events(after: int = Query(default=0, ge=0), current: BusinessService = Depends(get_service)) -> list[BusinessEvent]:
        return current.database.events(after)

    return app


app = create_app()
