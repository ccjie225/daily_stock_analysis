# -*- coding: utf-8 -*-
"""
场外公募基金接口。

当前 MVP 聚焦公开基金资料和历史净值分析，不处理个人账户登录、
支付宝/天天基金自动同步或真实交易状态变更。
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.funds import FundAnalysisResponse
from src.services.fund_service import FundNotFoundError, FundService, FundServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{fund_code}/analysis",
    response_model=FundAnalysisResponse,
    responses={
        200: {"description": "基金分析结果"},
        400: {"description": "基金代码无效", "model": ErrorResponse},
        404: {"description": "基金不存在或无净值数据", "model": ErrorResponse},
        503: {"description": "基金数据源不可用", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="分析场外公募基金",
    description="基于公开基金净值和基础资料生成场外公募基金规则分析。",
)
def analyze_fund(
    fund_code: str,
    days: int = Query(365, ge=30, le=1825, description="净值观察天数，默认 365 天"),
) -> FundAnalysisResponse:
    try:
        result = FundService().analyze_fund(fund_code, days=days)
        return FundAnalysisResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": str(exc)},
        ) from exc
    except FundNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except FundServiceError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "fund_data_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error("基金分析失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "基金分析失败"},
        ) from exc
