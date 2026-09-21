# import pandas as pd
# import numpy as np
#
# data = {
#     'square_meter': [100, 160, 240, 98, 76, 200, 50, 180, 160],
#     'price': [230, 330, 450, 232, 160, 489, 98, 400, 345]
# }
# df = pd.DataFrame(data)
#
# # 查看相关性
# print("相关系数:", df['square_meter'].corr(df['price']))
#
# # 简单线性回归（最小二乘法）
# slope, intercept = np.polyfit(df['square_meter'], df['price'], 1)
# print(f"拟合直线: price = {slope:.2f} * area + {intercept:.2f}")
#
# # 预测 150 平米的房价
# pred = slope * 150 + intercept
# print(f"预测 150 平米房价: {pred:.2f} 万元")


import numpy as np
import matplotlib.pyplot as plt

# ========== 1. 数据 ==========
X = np.array([100, 160, 240, 98, 76, 200, 50, 180, 160], dtype=float)
y = np.array([230, 330, 450, 232, 160, 489, 98, 400, 345], dtype=float)

# ========== 2. 用最小二乘法求拟合直线 ==========
# 一次多项式拟合，返回 [斜率, 截距]
w, b = np.polyfit(X, y, 1)

print(f"拟合直线: y = {w:.4f} * x + {b:.4f}")

# ========== 3. 画图 ==========
plt.figure(figsize=(7, 5))

# 散点：training set
plt.scatter(X, y, color='steelblue', label='training set')

# 画拟合直线：prediction
x_line = np.linspace(X.min(), X.max(), 100)
y_line = w * x_line + b
plt.plot(x_line, y_line, color='darkblue', linewidth=2, label='prediction')

# 坐标轴
plt.xlabel('Area')
plt.ylabel('Price')
plt.legend()

plt.title('回归分析 + 拟合直线')
plt.show()
