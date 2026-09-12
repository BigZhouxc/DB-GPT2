# -*- coding: utf-8 -*-
"""评估模块 —— 封装 DB-GPT SDK evaluation 函数。

SDK 直接封装：run_evaluation
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.client_factory import get_client

router = APIRouter(prefix="/evaluation", tags=["评估管理"])


class EvaluationRequest(BaseModel):
    evaluate_code: Optional[str] = Field(None, description="评估代码")
    scene_key: Optional[str] = Field(None, description="场景 key")
    scene_value: Optional[str] = Field(None, description="场景值")
    datasets_name: Optional[str] = Field(None, description="数据集名称")
    datasets: Optional[List[dict]] = Field(None, description="数据集")
    evaluate_metrics: Optional[List[str]] = Field(None, description="评估指标")
    context: Optional[dict] = Field(None, description="上下文")
    user_name: Optional[str] = Field(None, description="用户名")
    user_id: Optional[str] = Field(None, description="用户 ID")
    sys_code: Optional[str] = Field(None, description="系统编码")
    parallel_num: Optional[int] = Field(None, description="并发数")


@router.post("/run")
async def run_evaluation(req: EvaluationRequest):
    """运行评估。"""
    try:
        client = get_client()
        from dbgpt_client.evaluation import EvaluateServeRequest, run_evaluation as _run
        eval_req = EvaluateServeRequest(**req.model_dump(exclude_none=True))
        result = await _run(client, eval_req)
        return {"ok": True, "results": [r.dict() if hasattr(r, "dict") else str(r) for r in result]}
    except Exception as e:
        raise HTTPException(502, detail=f"运行评估失败: {e}")
