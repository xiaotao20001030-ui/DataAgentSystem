import numpy as np

# 从列表创建一个一维数组
arr = np.array([1, 2, 3, 4, 5])
print(arr)  # 输出: [1 2 3 4 5]

# 创建一个二维数组（矩阵）
arr_2d = np.array([[1, 2], [3, 4], [5, 6]])
print(arr_2d)
# 输出:
# [[1 2]
#  [3 4]
#  [5 6]]

def main():
    a = np.array([1, 2, 3])
    print("*******")
    print(a.mean())
    print(a.min())
    print(a.max())
    print(a.size)
    print(a.dtype)
    print(a.shape)
    print(a)
    print(a.dtype)

if __name__ == "__main__":
    main()

# data = [1, 2, 3, 4, 5]
# result = []
# for x in data:
#     result.append(x * 2 + 1)
# # result = [3, 5, 7, 9, 11]
# if __name__ == "__main__":
#     print(result);