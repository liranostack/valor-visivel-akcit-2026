"""Method-content tools: layer specs, question pools, templates and the method guide (KB)."""

from collections.abc import Callable
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from vv_contracts.common import LAYERS_ORDER, LayerId
from vv_contracts.kb import LayerSpec
from vv_contracts.ports import KnowledgeBase
from vv_contracts.tools import (
    GetLayerSpecIn,
    GetMethodGuideIn,
    GetMethodGuideOut,
    GetQuestionFromPoolIn,
    GetQuestionFromPoolOut,
    GetSynthesisTemplateIn,
    GetSynthesisTemplateOut,
)

from vv_mcp.kb import KnowledgeBaseError
from vv_mcp.telemetry import tool_span


def register(server: FastMCP, kb: KnowledgeBase | None) -> None:
    def use_kb[T](fn: Callable[[KnowledgeBase], T]) -> T:
        if kb is None:
            raise ToolError("knowledge base not configured (set KB_SOURCE)")
        try:
            return fn(kb)
        except KnowledgeBaseError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(description=GetLayerSpecIn.__doc__)
    def get_layer_spec(req: GetLayerSpecIn) -> LayerSpec:  # pyright: ignore[reportUnusedFunction]
        with tool_span("get_layer_spec") as span:
            span.set_attribute("layer_id", req.layer_id)
            return use_kb(lambda k: k.get_layer_spec(req.layer_id))

    @server.tool(description=GetQuestionFromPoolIn.__doc__)
    def get_question_from_pool(req: GetQuestionFromPoolIn) -> GetQuestionFromPoolOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("get_question_from_pool") as span:
            span.set_attribute("stage_id", req.stage_id)
            prefix = req.stage_id.split(".", 1)[0]
            if prefix not in LAYERS_ORDER:
                raise ToolError(f"unknown stage {req.stage_id!r}")
            layer_id = cast(LayerId, prefix)
            spec = use_kb(lambda k: k.get_layer_spec(layer_id))
            stage = next((s for s in spec.stages if s.stage_id == req.stage_id), None)
            if stage is None:
                raise ToolError(f"unknown stage {req.stage_id!r}")
            anchors = stage.anchors_for(req.angle) if req.angle else stage.anchors
            return GetQuestionFromPoolOut(
                stage_id=stage.stage_id, anchors=anchors, rescue_angles=stage.rescue_angles
            )

    @server.tool(description=GetSynthesisTemplateIn.__doc__)
    def get_synthesis_template(req: GetSynthesisTemplateIn) -> GetSynthesisTemplateOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("get_synthesis_template"):
            markdown = use_kb(lambda k: k.get_synthesis_template(req.kind))
            return GetSynthesisTemplateOut(kind=req.kind, markdown=markdown)

    @server.tool(description=GetMethodGuideIn.__doc__)
    def get_method_guide(req: GetMethodGuideIn) -> GetMethodGuideOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("get_method_guide"):
            return GetMethodGuideOut(markdown=use_kb(lambda k: k.get_method_guide(req.quadrant)))
