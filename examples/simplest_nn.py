"""
最简单的神经网络——一个神经元，从零实现。

包含完整的 训练 → 保存 → 加载 → 推理 流程。

没有框架，保存到纯文本 JSON 文件。
"""
import json
import math
import os
import random

# ═════════════════════════════════════════════════════
# 神经元（计算单元，和之前一样）
# ═════════════════════════════════════════════════════

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def neuron(w1: float, w2: float, bias: float, x1: float, x2: float) -> float:
    z = w1 * x1 + w2 * x2 + bias
    return sigmoid(z)


# ═════════════════════════════════════════════════════
# 训练（只做一次）
# ═════════════════════════════════════════════════════

def train(save_path: str = "and_neuron_weights.json"):
    w1 = random.uniform(-1, 1)
    w2 = random.uniform(-1, 1)
    bias = random.uniform(-1, 1)

    data = [(0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 1)]
    lr = 0.5

    for epoch in range(2000):
        total_loss = 0.0
        for x1, x2, y_true in data:
            y_pred = neuron(w1, w2, bias, x1, x2)
            total_loss += (y_pred - y_true) ** 2

            d_sigmoid = y_pred * (1 - y_pred)
            d_z = 2 * (y_pred - y_true) * d_sigmoid

            w1 -= lr * d_z * x1
            w2 -= lr * d_z * x2
            bias -= lr * d_z

        if epoch % 500 == 0:
            print(f"epoch {epoch:4d}  loss={total_loss:.6f}")

    weights = {"w1": w1, "w2": w2, "bias": bias}
    with open(save_path, "w") as f:
        json.dump(weights, f, indent=2)

    print(f"\n已保存到 {save_path}")
    return w1, w2, bias


# ═════════════════════════════════════════════════════
# 加载 + 推理（每次使用只需这两步）
# ═════════════════════════════════════════════════════

def load_weights(path: str = "and_neuron_weights.json") -> dict:
    """从 JSON 文件加载训练好的权重。"""
    with open(path, "r") as f:
        return json.load(f)


def predict(w1: float, w2: float, bias: float, x1: int, x2: int) -> int:
    """使用训练好的权重做推理。—— 不再需要训练数据，不再需要反向传播。"""
    output = neuron(w1, w2, bias, x1, x2)
    return 1 if output > 0.5 else 0


# ═════════════════════════════════════════════════════

if __name__ == "__main__":
    save_path = "and_neuron_weights.json"

    # ── 训练阶段（只做一次）────────────────────
    if not os.path.exists(save_path):
        print("未找到权重文件，开始训练...\n")
        train(save_path)
    else:
        print(f"找到已有权重文件: {save_path}\n")

    # ── 推理阶段（每次使用）────────────────────
    w = load_weights(save_path)
    print(f"加载权重: w1={w['w1']:.3f}  w2={w['w2']:.3f}  bias={w['bias']:.3f}\n")

    # 现在随便用
    tests = [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    for x1, x2 in tests:
        result = predict(w["w1"], w["w2"], w["bias"], x1, x2)
        print(f"  {x1} AND {x2} → {result}")
