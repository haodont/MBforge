"""入库门禁：必需模型权重未就绪时阻止队列领取文档。

Extract 阶段依赖四个必须下载的模型权重。缺权重时它不会立刻失败——MolDet 缺失
只在 coordinator 里打一条 warning 然后返回空检测结果，Hiro-Layout 缺失要到
extract/text 才抛错——所以队列行和 worker 资源已经提交，文档却产出静默错误或
半成品。这个模块提供一个纯探测谓词，让队列 worker 在**领取之前**就知道该不该
动手，并把原因带给前端。

门禁只挡"领取"，不挡入队：缺模型时任务保持 ``pending`` 排队，模型一就绪 worker
下一轮轮询就自动继续，无需重启或手动重试。

必需模型集合由 catalog 层定义（``RESOURCE_CATALOG`` 旁的
``REQUIRED_PIPELINE_MODEL_IDS``），这里只经运行时端口读取，不另抄一份。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_runtime

logger = get_logger(__name__)

#: 与 ``ResourceStatus.READY`` 同值。用字符串字面量比较，service 层就不必
#: import ``mbforge.server.resource_types``，守住 service → ports 的边界。
_READY = "ready"

#: 错误信息截断长度，避免把超长异常塞进 HTTP 响应。
_MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class BlockingModel:
    """一个阻止处理的必需模型及其当前状态。"""

    id: str
    name: str
    status: str
    error: str | None = None


@dataclass(frozen=True)
class ModelGateResult:
    """门禁判定结果。``ready`` 为假时 ``missing`` 一定非空。"""

    ready: bool
    required: tuple[str, ...]
    missing: tuple[BlockingModel, ...]

    def missing_ids(self) -> tuple[str, ...]:
        """返回缺失模型的 id，供日志去重比较。"""
        return tuple(model.id for model in self.missing)

    def reason(self) -> str | None:
        """一行人类可读的原因，``ready`` 时为 ``None``。"""
        if self.ready:
            return None
        detail = ", ".join(f"{m.id} ({m.status})" for m in self.missing)
        return f"missing models: {detail}"

    def to_dict(self) -> dict[str, Any]:
        """可 JSON 序列化的形态，直接进 HTTP 响应。"""
        return {
            "ready": self.ready,
            "required": list(self.required),
            "missing": [
                {
                    "id": model.id,
                    "name": model.name,
                    "status": model.status,
                    "error": model.error,
                }
                for model in self.missing
            ],
            "reason": self.reason(),
        }


def _status_value(result: Any) -> str:
    """从 ``ResourceStatusResult`` 取出状态字符串（``ResourceStatus`` 是 StrEnum）。"""
    status = getattr(result, "status", None)
    value = getattr(status, "value", status)
    return str(value) if value is not None else "error"


def evaluate_model_gate() -> ModelGateResult:
    """判断全部必需模型是否已就绪。

    纯文件系统/import 探测：不联网、不加载权重。单个资源的探测异常被降级为一条
    ``status="error"`` 的阻塞项，绝不向上抛——门禁出错时必须偏向"挡住"，不能
    静默放行处理。

    刻意不用 ``ResourceManager.check_all()``：那条路径会 import torch 并做 CUDA
    探测，代价远超一个轮询谓词。本函数是同步的，调用方负责放进线程。
    """
    runtime = get_runtime()
    required = tuple(runtime.resource_manager.required_pipeline_model_ids)

    missing: list[BlockingModel] = []
    for resource_id in required:
        try:
            result = runtime.resource_manager.check(resource_id)
        except Exception as exc:  # noqa: BLE001 — 探测失败按阻塞处理，不放行
            logger.warning("model gate: probe failed for %s: %s", resource_id, exc)
            missing.append(
                BlockingModel(
                    id=resource_id,
                    name=resource_id,
                    status="error",
                    error=str(exc)[:_MAX_ERROR_CHARS] or type(exc).__name__,
                )
            )
            continue

        status = _status_value(result)
        if status == _READY:
            continue
        missing.append(
            BlockingModel(
                id=resource_id,
                name=getattr(result, "name", "") or resource_id,
                status=status,
                error=(getattr(result, "error", "") or None),
            )
        )

    return ModelGateResult(
        ready=not missing,
        required=required,
        missing=tuple(missing),
    )
