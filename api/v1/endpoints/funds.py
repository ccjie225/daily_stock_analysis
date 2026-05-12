# -*- coding: utf-8 -*-
"""
场外公募基金接口。

当前 MVP 聚焦公开基金资料和历史净值分析，不处理个人账户登录、
支付宝/天天基金自动同步或真实交易状态变更。
"""

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.funds import (
    FundAnalysisResponse,
    FundHoldingImportItem,
    FundHoldingImportResponse,
    FundHoldingListResponse,
    FundHoldingReviewResponse,
    FundHoldingSaveRequest,
    FundHoldingSaveResponse,
    FundSavedHoldingItem,
)
from src.services.fund_holding_image_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_fund_holdings_from_image,
)
from src.services.fund_holding_review_service import FundHoldingReviewService
from src.services.fund_holding_service import FundHoldingBusyError, FundHoldingService
from src.services.fund_service import FundNotFoundError, FundService, FundServiceError

logger = logging.getLogger(__name__)

router = APIRouter()
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


@router.get(
    "/holdings",
    response_model=FundHoldingListResponse,
    responses={500: {"description": "服务器错误", "model": ErrorResponse}},
    summary="列出已保存的个人基金持仓",
    description="返回已由用户确认保存的场外基金持仓记录。金额、份额和收益字段均为字符串预览值。",
)
def list_holdings(
    limit: int = Query(200, ge=1, le=500, description="返回条数"),
) -> FundHoldingListResponse:
    try:
        rows = FundHoldingService().list_holdings(limit=limit)
        return FundHoldingListResponse(items=[FundSavedHoldingItem(**item) for item in rows])
    except Exception as exc:
        logger.error("查询个人基金持仓失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "查询个人基金持仓失败"},
        ) from exc


@router.post(
    "/holdings",
    response_model=FundHoldingSaveResponse,
    responses={
        200: {"description": "保存后的个人基金持仓"},
        400: {"description": "请求无效", "model": ErrorResponse},
        409: {"description": "持仓库繁忙", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="保存个人基金持仓",
    description="保存截图识别后由用户确认的个人基金持仓。重复基金会按基金代码/名称和平台更新，不重复新增。",
)
def save_holdings(request: FundHoldingSaveRequest) -> FundHoldingSaveResponse:
    try:
        data = FundHoldingService().save_imported_holdings(
            [item.dict() for item in request.items]
        )
        return FundHoldingSaveResponse(
            saved_count=data["saved_count"],
            items=[FundSavedHoldingItem(**item) for item in data["items"]],
        )
    except FundHoldingBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "fund_holding_busy", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error("保存个人基金持仓失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "保存个人基金持仓失败"},
        ) from exc


@router.get(
    "/holdings/review",
    response_model=FundHoldingReviewResponse,
    responses={500: {"description": "服务器错误", "model": ErrorResponse}},
    summary="复盘个人基金持仓",
    description="基于已保存持仓、最新公开净值和基金公开分析生成净值对齐、估算浮动和持仓建议。",
)
def review_holdings(
    limit: int = Query(50, ge=1, le=100, description="复盘条数"),
    use_ai: bool = Query(False, description="是否调用 LLM 生成增强组合复盘"),
) -> FundHoldingReviewResponse:
    try:
        data = FundHoldingReviewService().review_holdings(limit=limit, use_ai=use_ai)
        return FundHoldingReviewResponse(**data)
    except Exception as exc:
        logger.error("复盘个人基金持仓失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "复盘个人基金持仓失败"},
        ) from exc


@router.post(
    "/import-holdings-image",
    response_model=FundHoldingImportResponse,
    responses={
        200: {"description": "个人基金持仓截图识别结果"},
        400: {"description": "图片无效或识别失败", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从截图识别个人基金持仓",
    description="上传支付宝、天天基金、养基宝等持仓截图，通过 Vision LLM 提取可核对的个人基金持仓字段。只返回预览，不写入持仓库。",
)
def import_holdings_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> FundHoldingImportResponse:
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("读取基金持仓截图失败: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        ) from exc

    try:
        items, raw_text, warnings = extract_fund_holdings_from_image(data, content_type)
        return FundHoldingImportResponse(
            items=[FundHoldingImportItem(**item) for item in items],
            raw_text=raw_text if include_raw else None,
            warnings=warnings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(exc)}) from exc
    except Exception as exc:
        logger.error("基金持仓截图识别失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "基金持仓截图识别失败"},
        ) from exc


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
