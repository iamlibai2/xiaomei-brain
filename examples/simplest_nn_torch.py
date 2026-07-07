"""
同一个神经元，用 PyTorch 写。

和 simplest_nn.py 对比着看——逻辑完全一样，只是计算和梯度交给框架了。
"""

import torch
import torch.nn as nn


# ═════════════════════════════════════════════════════
# 和手写版一一对应
# ═════════════════════════════════════════════════════

class OneNeuron(nn.Module):
    def __init__(self):
        super().__init__()
        # 这等价于手写版的 w1, w2, bias
        self.linear = nn.Linear(2, 1)   # 2 输入 → 1 输出
        self.sigmoid = nn.Sigmoid()      # 等价于手写的 sigmoid 函数

    def forward(self, x):
        # 等价于：z = w1*x1 + w2*x2 + bias; return sigmoid(z)
        return self.sigmoid(self.linear(x))


# ═════════════════════════════════════════════════════
# 训练
# ═════════════════════════════════════════════════════

def train():
    model = OneNeuron()

    # AND 真值表
    X = torch.tensor([[0., 0.], [0., 1.], [1., 0.], [1., 1.]])  # 4×2
    y = torch.tensor([[0.], [0.], [0.], [1.]])                  # 4×1

    # 损失函数（等价于手写的 (y_pred - y_true)**2）
    loss_fn = nn.MSELoss()

    # 优化器（等价于手写的 w -= lr * grad）
    optimizer = torch.optim.SGD(model.parameters(), lr=0.5)

    for epoch in range(2000):
        # 前向传播
        y_pred = model(X)
        loss = loss_fn(y_pred, y)

        # 反向传播（等价于手写的那三行链式法则）
        optimizer.zero_grad()   # 清空上一次的梯度
        loss.backward()         # 自动求导——框架帮你做了 d_loss * d_sigmoid
        optimizer.step()        # 更新权重

        if epoch % 500 == 0:
            w = model.linear.weight.data
            b = model.linear.bias.data
            print(f"epoch {epoch:4d}  loss={loss.item():.6f}  "
                  f"w={[f'{w[0,0]:+.3f}', f'{w[0,1]:+.3f}']}  bias={b[0]:+.3f}")

    return model


if __name__ == "__main__":
    model = train()

    print("\n训练后：\n")
    X = torch.tensor([[0., 0.], [0., 1.], [1., 0.], [1., 1.]])
    with torch.no_grad():
        for i, (x1, x2) in enumerate([(0,0), (0,1), (1,0), (1,1)]):
            out = model(X[i:i+1]).item()
            pred = 1 if out > 0.5 else 0
            print(f"  {x1} AND {x2} = {pred}  (raw={out:.4f})  ✓{'✗' if pred != (x1 and x2) else '✓'}")
