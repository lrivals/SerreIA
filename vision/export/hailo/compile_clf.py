"""ONNX -> HEF compilation of the classifier with the Hailo Dataflow Compiler (docs/05 §2).

Runs in the "Hailo AI SW Suite" Docker (x86, no board needed), see README.md:

    python vision/export/hailo/compile_clf.py --onnx edge/models/<v>/clf.onnx \\
        --calib runs/export/calib_clf_224.npy --hw-arch hailo8l

parse (translate_onnx_model) -> optimize (INT8 quantization on the calibration set) ->
compile. The model script clf.alls puts the ImageNet normalization on the chip (input
uint8 RGB 0-255) and sets the optimization level. Writes next to the ONNX <name>.har
(float), <name>.q.har (quantized, emulated on the PC by vision.export.evaluate_backend)
and <name>.hef, then prints the output names and sizes: the HEF renames them and
edge.vision.backends.order_outputs matches them back by size (espece / sante / classe
have distinct sizes).
"""

import argparse
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def main() -> None:
    from hailo_sdk_client import ClientRunner

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--calib", type=Path, required=True, help="(N, S, S, 3) uint8")
    parser.add_argument("--hw-arch", choices=["hailo8l", "hailo8"], default="hailo8l")
    parser.add_argument("--alls", type=Path, default=HERE / "clf.alls")
    parser.add_argument("--name", default="clf")
    args = parser.parse_args()

    calib = np.load(args.calib)
    size = calib.shape[1]
    out = args.onnx.with_name(args.name)
    runner = ClientRunner(hw_arch=args.hw_arch)
    runner.translate_onnx_model(
        str(args.onnx), args.name, net_input_shapes={"image": [1, 3, size, size]}
    )
    runner.save_har(str(out.with_suffix(".har")))
    runner.load_model_script(args.alls.read_text())
    runner.optimize(calib.astype(np.float32))
    runner.save_har(str(out.with_suffix(".q.har")))
    hef = runner.compile()
    out.with_suffix(".hef").write_bytes(hef)

    print(f"HEF : {out.with_suffix('.hef')} ({args.hw_arch})")
    for layer in runner.get_hn_model().get_output_layers():
        print(f"  sortie {layer.name:40s} {layer.output_shape}")


if __name__ == "__main__":
    main()
