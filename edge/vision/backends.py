"""Inference backends (docs/05 §2-3): one interface, ONNX Runtime on the PC, HailoRT on the Pi.

Every backend takes a batch of RGB uint8 images (n, H, W, 3) at the model's input size and
returns its outputs in the model's order. The ONNX graphs expect normalized NCHW floats: the
backend normalizes. The HEF graphs carry their normalization (model script `normalization1`)
and take the uint8 images as is. `hailo_platform` (Pi, apt `hailo-all`) and
`hailo_sdk_client` (Docker "Hailo AI SW Suite", x86) are imported lazily.
"""

from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np

# ImageNet statistics, as vision.datasets.batch_augment (not imported: it pulls torch).
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

Norm = Literal["imagenet", "unit"]  # classifier: ImageNet mean/std; YOLO: [0, 1]


class Backend(Protocol):
    input_size: tuple[int, int]  # (H, W)
    output_names: list[str]

    def __call__(self, batch: np.ndarray) -> list[Any]:
        """(n, H, W, 3) uint8 RGB -> outputs in output_names order, batch dimension first."""
        ...


def normalize(batch: np.ndarray, norm: Norm) -> np.ndarray:
    """(n, H, W, 3) uint8 -> (n, 3, H, W) float32."""
    x = batch.astype(np.float32) / 255
    if norm == "imagenet":
        x = (x - np.array(MEAN, np.float32)) / np.array(STD, np.float32)
    return np.ascontiguousarray(x.transpose(0, 3, 1, 2))


class OnnxBackend:
    """ONNX Runtime on CPU. A graph exported with a fixed batch of 1 is run image by image."""

    def __init__(self, path: Path, norm: Norm = "imagenet", threads: int | None = None):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.input_name, self.norm = inp.name, norm
        self.fixed_batch = inp.shape[0] if isinstance(inp.shape[0], int) else None
        self.input_size = (int(inp.shape[2]), int(inp.shape[3]))
        self.output_names = [o.name for o in self.sess.get_outputs()]

    def __call__(self, batch: np.ndarray) -> list[np.ndarray]:
        x = normalize(batch, self.norm)
        if self.fixed_batch is None:
            return self.sess.run(None, {self.input_name: x})
        step = self.fixed_batch
        runs = [
            self.sess.run(None, {self.input_name: x[i : i + step]}) for i in range(0, len(x), step)
        ]
        return [np.concatenate(outs) for outs in zip(*runs, strict=True)]


def shared_vdevice() -> Any:
    """Hailo device with the round-robin model scheduler: several HEFs (YOLO + classifier)
    on one chip, switched by HailoRT without explicit activation."""
    from hailo_platform import HailoSchedulingAlgorithm, VDevice

    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
    return VDevice(params=params)


class HailoBackend:
    """HEF on the Hailo-8L / Hailo-8 through HailoRT (Raspberry Pi 5, apt `hailo-all`).

    Outputs dequantized to float32. An output with on-chip NMS comes back, per image, as a
    list of per-class (k, 5) arrays [ymin, xmin, ymax, xmax, score] normalized to the input.
    `device`: a shared_vdevice() (scheduler); None = own device, network activated here.
    Not testable without the board.
    """

    def __init__(self, hef_path: Path, device: Any = None):
        from hailo_platform import (
            HEF,
            ConfigureParams,
            FormatType,
            HailoStreamInterface,
            InferVStreams,
            InputVStreamParams,
            OutputVStreamParams,
            VDevice,
        )

        self._stack = ExitStack()
        hef = HEF(str(hef_path))
        scheduled = device is not None
        self.device = device if scheduled else self._stack.enter_context(VDevice())
        params = ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe)
        group = self.device.configure(hef, params)[0]
        inp = hef.get_input_vstream_infos()[0]
        self.input_name = inp.name
        self.input_size = (int(inp.shape[0]), int(inp.shape[1]))  # NHWC without batch
        self.output_names = [o.name for o in hef.get_output_vstream_infos()]
        self.pipe = self._stack.enter_context(InferVStreams(
            group,
            InputVStreamParams.make(group, format_type=FormatType.UINT8),
            OutputVStreamParams.make(group, format_type=FormatType.FLOAT32),
        ))  # fmt: skip
        if not scheduled:
            self._stack.enter_context(group.activate(group.create_params()))

    def __call__(self, batch: np.ndarray) -> list[Any]:
        out = self.pipe.infer({self.input_name: np.ascontiguousarray(batch, np.uint8)})
        return [out[name] for name in self.output_names]

    def close(self) -> None:
        self._stack.close()


class HarEmulatorBackend:
    """Quantized emulation of a HAR with the Dataflow Compiler (PC x86, Hailo Docker): gives
    the INT8 accuracy before a Pi is available. Input in 0-255 floats, as the HEF."""

    def __init__(self, har_path: Path, quantized: bool = True):
        from hailo_sdk_client import ClientRunner, InferenceContext

        self.runner = ClientRunner(har=str(har_path))
        self.context = (
            InferenceContext.SDK_QUANTIZED if quantized else InferenceContext.SDK_FP_OPTIMIZED
        )
        hn = self.runner.get_hn_model()
        shape = hn.get_input_layers()[0].output_shape  # [-1, H, W, C]
        self.input_size = (int(shape[1]), int(shape[2]))
        self.output_names = [layer.name for layer in hn.get_output_layers()]

    def __call__(self, batch: np.ndarray) -> list[np.ndarray]:
        with self.runner.infer_context(self.context) as ctx:
            out = self.runner.infer(ctx, batch.astype(np.float32))
        out = out if isinstance(out, list) else [out]
        return [o.reshape(len(batch), -1) if o.ndim > 2 else o for o in out]


def order_outputs(
    names: Sequence[str], outputs: Sequence[np.ndarray], expected: dict[str, int]
) -> list[np.ndarray]:
    """Outputs in the `expected` order (head -> number of classes).

    By name when the graph kept them (ONNX), otherwise by size: the HEF renames the outputs
    and may reorder them (docs/05 §2). Refuses an ambiguous or incomplete match.
    """
    by_name = dict(zip(names, outputs, strict=True))
    if all(h in by_name for h in expected):
        return [by_name[h] for h in expected]
    flat = [np.asarray(o).reshape(len(o), -1) for o in outputs]
    ordered = []
    for head, size in expected.items():
        hits = [o for o in flat if o.shape[1] == size]
        if len(hits) != 1:
            raise ValueError(
                f"sortie {head!r} ({size} classes) : {len(hits)} candidates parmi "
                f"{[(n, o.shape[1]) for n, o in zip(names, flat, strict=True)]}"
            )
        ordered.append(hits[0])
    return ordered
